"""RAG ingestion pipeline: multi-URL live web scraper, markdown loader, and semantic chunker."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from src.config.settings import settings
from src.observability.logger import get_logger

logger = get_logger("rag.ingest")

DEFAULT_GETNET_URLS: list[str] = [
    "https://www.getnet.net/en",
    "https://site.getnet.com.br/maquininhas/",
    "https://site.getnet.com.br/link-de-pagamento/",
    "https://site.getnet.com.br/duvidas/",
]

DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8,pt;q=0.7",
}


class DocumentChunk(BaseModel):
    """Normalized text chunk with provenance metadata for ChromaDB indexing."""

    chunk_id: str
    content: str
    source_url: str
    title: str
    section: str
    product_tag: str = "general"
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_chroma_metadata(self) -> dict[str, str]:
        """Return flat string metadata compatible with ChromaDB."""
        return {
            "source_url": self.source_url,
            "title": self.title,
            "section": self.section,
            "product_tag": self.product_tag,
        }


def _compute_chunk_id(prefix: str, section: str, text: str) -> str:
    digest = hashlib.sha256(f"{prefix}::{section}::{text}".encode("utf-8")).hexdigest()[:14]
    slug = re.sub(r"[^a-z0-9]+", "-", section.lower()).strip("-")[:28] or "chunk"
    return f"{slug}-{digest}"


def split_text_with_overlap(
    text: str,
    chunk_size: int = 850,
    chunk_overlap: int = 140,
) -> list[str]:
    """Split text along paragraph/sentence boundaries while preserving overlap."""
    cleaned = re.sub(r"\n{3,}", "\n\n", text.strip())
    if len(cleaned) <= chunk_size:
        return [cleaned] if cleaned else []

    paragraphs = [p.strip() for p in cleaned.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        candidate = f"{current}\n\n{para}".strip() if current else para
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            if current:
                chunks.append(current)
                tail = current[-chunk_overlap:] if chunk_overlap > 0 else ""
                current = f"{tail}\n\n{para}".strip()
            else:
                # Single very long paragraph: slice by character window
                step = max(100, chunk_size - chunk_overlap)
                for idx in range(0, len(para), step):
                    piece = para[idx : idx + chunk_size].strip()
                    if piece:
                        chunks.append(piece)
                current = ""

    if current:
        chunks.append(current)

    return chunks


def scrape_getnet_url(url: str, timeout: float = 8.0) -> list[DocumentChunk]:
    """Fetch and parse an official Getnet URL into clean DocumentChunks."""
    try:
        with httpx.Client(
            headers=DEFAULT_HEADERS,
            timeout=timeout,
            follow_redirects=True,
        ) as client:
            response = client.get(url)
            response.raise_for_status()
            html = response.text
    except Exception as exc:
        logger.warning(
            "live_scrape_skipped_or_blocked",
            url=url,
            reason=f"{type(exc).__name__}: {exc}",
        )
        return []

    soup = BeautifulSoup(html, "html.parser")
    page_title = (
        soup.title.string.strip()
        if soup.title and soup.title.string
        else f"Getnet Official Page ({url})"
    )

    for tag in soup(["script", "style", "noscript", "svg", "iframe", "footer", "nav"]):
        tag.decompose()

    blocks: list[str] = []
    for elem in soup.find_all(["h1", "h2", "h3", "p", "li"]):
        txt = " ".join(elem.get_text(" ", strip=True).split())
        if len(txt) < 25:
            continue
        if elem.name in ("h1", "h2", "h3"):
            blocks.append(f"\n### {txt}")
        else:
            blocks.append(txt)

    combined = "\n".join(blocks).strip()
    if len(combined) < 80:
        return []

    raw_pieces = split_text_with_overlap(combined, chunk_size=800, chunk_overlap=120)
    chunks: list[DocumentChunk] = []
    for idx, piece in enumerate(raw_pieces):
        section_name = f"Live Web Scrape ({page_title}) #{idx + 1}"
        content_with_header = f"[{page_title} - {url}]\n{piece}"
        chunks.append(
            DocumentChunk(
                chunk_id=_compute_chunk_id("web", url, content_with_header),
                content=content_with_header,
                source_url=url,
                title=page_title,
                section=section_name,
                product_tag="live_web_scrape",
            )
        )

    logger.info("live_scrape_succeeded", url=url, chunks_created=len(chunks))
    return chunks


def parse_markdown_file(file_path: Path) -> list[DocumentChunk]:
    """Parse a structured Getnet markdown corpus file into metadata-enriched DocumentChunks."""
    raw = file_path.read_text(encoding="utf-8")
    doc_title = "Getnet Official Product & Institutional Knowledge Base"
    first_h1 = re.search(r"^#\s+(.+)$", raw, flags=re.MULTILINE)
    if first_h1:
        doc_title = first_h1.group(1).strip()

    # Split by top-level "## " sections
    sections = re.split(r"(?m)^##\s+", raw)
    chunks: list[DocumentChunk] = []

    for sec in sections[1:]:
        lines = sec.strip().splitlines()
        if not lines:
            continue
        section_title = lines[0].strip()
        source_url = "https://www.getnet.net/en"
        product_tag = "getnet_general"
        body_lines: list[str] = []

        for line in lines[1:]:
            stripped = line.strip()
            if stripped.lower().startswith("source_url:"):
                source_url = stripped.split(":", 1)[1].strip()
                continue
            if stripped.lower().startswith("product_tag:"):
                product_tag = stripped.split(":", 1)[1].strip()
                continue
            if stripped == "---":
                continue
            body_lines.append(line)

        body_text = "\n".join(body_lines).strip()
        if not body_text:
            continue

        pieces = split_text_with_overlap(body_text, chunk_size=1450, chunk_overlap=180)
        for piece in pieces:
            contextualized = f"## {section_title}\nSource: {source_url}\n\n{piece}"
            chunks.append(
                DocumentChunk(
                    chunk_id=_compute_chunk_id(product_tag, section_title, contextualized),
                    content=contextualized,
                    source_url=source_url,
                    title=doc_title,
                    section=section_title,
                    product_tag=product_tag,
                )
            )

    return chunks


def load_markdown_corpus(kb_dir: Path | str | None = None) -> list[DocumentChunk]:
    """Load all markdown files from the configured knowledge base directory."""
    resolved_dir = settings.resolve_path(str(kb_dir or settings.knowledge_base_dir))
    if not resolved_dir.exists():
        logger.warning("knowledge_base_dir_missing", path=str(resolved_dir))
        return []

    all_chunks: list[DocumentChunk] = []
    for md_file in sorted(resolved_dir.glob("*.md")):
        all_chunks.extend(parse_markdown_file(md_file))

    logger.info(
        "markdown_corpus_loaded",
        directory=str(resolved_dir),
        chunks_count=len(all_chunks),
    )
    return all_chunks


def build_knowledge_chunks(
    include_live_scrape: bool = True,
    urls: list[str] | None = None,
    kb_dir: Path | str | None = None,
) -> list[DocumentChunk]:
    """Build the complete deduplicated list of DocumentChunks from corpus + live Getnet URLs."""
    chunks = load_markdown_corpus(kb_dir=kb_dir)
    seen_ids = {c.chunk_id for c in chunks}

    if include_live_scrape:
        target_urls = urls if urls is not None else DEFAULT_GETNET_URLS
        for url in target_urls:
            for web_chunk in scrape_getnet_url(url):
                if web_chunk.chunk_id not in seen_ids:
                    chunks.append(web_chunk)
                    seen_ids.add(web_chunk.chunk_id)

    return chunks
