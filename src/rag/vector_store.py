"""ChromaDB vector store indexing and hybrid semantic retrieval for Getnet RAG."""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Any

import chromadb
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from langchain_openai import OpenAIEmbeddings
from pydantic import BaseModel, Field

from src.config.settings import settings
from src.observability.logger import get_logger
from src.rag.ingest import DocumentChunk, build_knowledge_chunks

logger = get_logger("rag.vector_store")

# Bilingual (EN/PT) domain concept clusters used to enrich embedding dimensions
_CONCEPT_CLUSTERS: list[tuple[str, tuple[str, ...]]] = [
    (
        "pos_comparison_classica_smart",
        (
            "classica",
            "clássica",
            "get smart",
            "smart pos",
            "android",
            "touchscreen",
            "touch screen",
            "physical keypad",
            "teclado fisico",
            "teclado físico",
            "getstore",
            "bobina",
            "thermal paper",
            "maquininha",
            "maquininhas",
        ),
    ),
    (
        "pos_models_lite_mini_tap",
        (
            "get lite",
            "get mini",
            "get tap",
            "tap on phone",
            "nfc",
            "contactless",
            "pocket",
            "sms receipt",
        ),
    ),
    (
        "pix_bank_account",
        (
            "pix",
            "bank account",
            "conta bancaria",
            "conta bancária",
            "domicilio bancario",
            "domicílio bancário",
            "getconta",
            "qr code",
            "receive my sales via pix",
            "cpf",
            "cnpj",
        ),
    ),
    (
        "receivables_advance_antecipacao",
        (
            "receivables advance",
            "antecipacao",
            "antecipação",
            "recebiveis",
            "recebíveis",
            "d+1",
            "d+0",
            "receba ja",
            "receba já",
            "automatic advance",
            "punctual",
            "avulsa",
            "working capital",
            "cash flow",
        ),
    ),
    (
        "crediario_installments",
        (
            "crediario",
            "crediário",
            "installments",
            "parcelas",
            "parcelar",
            "48 installments",
            "48x",
            "split a sale",
            "how many installments",
            "quantas parcelas",
        ),
    ),
    (
        "payment_link_whatsapp",
        (
            "payment link",
            "link de pagamento",
            "getpay",
            "whatsapp",
            "sell through whatsapp",
            "vender pelo whatsapp",
            "social media",
            "instagram",
            "anti-fraud",
            "antifraude",
            "3ds",
        ),
    ),
    (
        "institutional_global",
        (
            "pagonxt",
            "santander",
            "latin america",
            "europe",
            "getnet.net",
            "global",
            "omnichannel",
        ),
    ),
]


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9à-ú\+]+", text.lower())


class GetnetHybridEmbeddingFunction(EmbeddingFunction[Documents]):
    """Deterministic 128-dim bilingual domain + hashed n-gram embedding function for ChromaDB."""

    def __init__(self, dim: int = 128) -> None:
        self.dim = dim

    @staticmethod
    def name() -> str:
        return "getnet_hybrid_bilingual_v1"

    def get_config(self) -> dict[str, Any]:
        return {"dim": self.dim}

    @classmethod
    def build_from_config(cls, config: dict[str, Any]) -> "GetnetHybridEmbeddingFunction":
        return cls(dim=int(config.get("dim", 128)))

    def _embed_single(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        norm_text = _normalize_text(text)
        tokens = _tokenize(norm_text)

        # 1. Reserved concept cluster dimensions (0 .. len(_CONCEPT_CLUSTERS)*2 - 1)
        for idx, (_, keywords) in enumerate(_CONCEPT_CLUSTERS):
            hits = sum(1 for kw in keywords if kw in norm_text)
            if hits > 0:
                vec[idx * 2] = float(hits) * 3.5
                vec[idx * 2 + 1] = math.log1p(hits) * 4.0

        # 2. Hashed token unigrams and bigrams into remaining dimensions
        offset = len(_CONCEPT_CLUSTERS) * 2
        usable = self.dim - offset
        for i, tok in enumerate(tokens):
            if len(tok) < 2:
                continue
            digest = int(hashlib.md5(tok.encode("utf-8")).hexdigest()[:8], 16)
            slot = offset + (digest % usable)
            sign = 1.0 if (digest & 1) == 0 else -1.0
            vec[slot] += sign * 1.2

            if i + 1 < len(tokens):
                bigram = f"{tok}_{tokens[i + 1]}"
                b_digest = int(hashlib.md5(bigram.encode("utf-8")).hexdigest()[:8], 16)
                b_slot = offset + (b_digest % usable)
                vec[b_slot] += 0.8

        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 1e-9:
            vec = [round(v / norm, 6) for v in vec]
        else:
            vec[0] = 1.0
        return vec

    def __call__(self, input: Documents) -> Embeddings:
        return [self._embed_single(doc) for doc in input]


class OpenAIChromaEmbeddingFunction(EmbeddingFunction[Documents]):
    """ChromaDB EmbeddingFunction backed by OpenAIEmbeddings (text-embedding-3-small) with resilient fallback."""

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.model = model or settings.openai_embedding_model
        self._client = OpenAIEmbeddings(
            model=self.model,
            api_key=api_key or settings.openai_api_key,
            timeout=12.0,
            max_retries=2,
            check_embedding_ctx_length=False,
        )
        self._fallback_fn = GetnetHybridEmbeddingFunction(dim=1536)

    @staticmethod
    def name() -> str:
        return "openai_text_embedding_3_small"

    def get_config(self) -> dict[str, Any]:
        return {"model": self.model}

    @classmethod
    def build_from_config(cls, config: dict[str, Any]) -> "OpenAIChromaEmbeddingFunction":
        return cls(model=str(config.get("model", settings.openai_embedding_model)))

    def __call__(self, input: Documents) -> Embeddings:
        texts = [str(doc) for doc in input]
        if not texts:
            return []
        try:
            return self._client.embed_documents(texts)
        except Exception as exc:
            logger.warning(
                "openai_embedding_call_failed_falling_back_to_hybrid",
                error=str(exc),
            )
            return self._fallback_fn(input)


class RetrievedChunk(BaseModel):
    """A single retrieved knowledge base chunk with similarity score and source metadata."""

    chunk_id: str
    content: str
    source_url: str
    title: str
    section: str
    product_tag: str
    similarity_score: float = Field(ge=0.0, le=1.0)


class GetnetVectorStore:
    """Persistent ChromaDB wrapper with OpenAIEmbeddings and hybrid concept-aware ranking for Getnet RAG."""

    def __init__(
        self,
        persist_dir: str | Path | None = None,
        collection_name: str | None = None,
        ephemeral: bool = False,
        use_openai_embeddings: bool | None = None,
    ) -> None:
        base_collection = collection_name or settings.chroma_collection_name
        self.ephemeral = ephemeral
        should_try_openai = (
            use_openai_embeddings
            if use_openai_embeddings is not None
            else (settings.use_live_llm and not ephemeral)
        )

        self.using_openai_embeddings = False
        self.embedding_fn: EmbeddingFunction[Documents] = GetnetHybridEmbeddingFunction(dim=128)
        self.collection_name = base_collection

        if should_try_openai and settings.has_openai_key:
            try:
                candidate_fn = OpenAIChromaEmbeddingFunction(
                    model=settings.openai_embedding_model,
                    api_key=settings.openai_api_key,
                )
                # Verify live reachability with a single lightweight probe
                probe = candidate_fn(["Getnet POS"])
                if probe and len(probe[0]) > 0:
                    self.embedding_fn = candidate_fn
                    self.using_openai_embeddings = True
                    if collection_name is None:
                        self.collection_name = f"{base_collection}_openai"
            except Exception as exc:
                logger.warning(
                    "openai_embeddings_unavailable_falling_back_to_hybrid",
                    error=str(exc),
                )

        if ephemeral:
            self._client = chromadb.EphemeralClient()
            self.persist_path = None
        else:
            self.persist_path = settings.resolve_path(
                str(persist_dir or settings.chroma_persist_dir)
            )
            self.persist_path.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(self.persist_path))

        try:
            self._collection = self._client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=self.embedding_fn,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception:
            self._client.delete_collection(name=self.collection_name)
            self._collection = self._client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=self.embedding_fn,
                metadata={"hnsw:space": "cosine"},
            )

    def count(self) -> int:
        """Return total number of chunks indexed in the ChromaDB collection."""
        return int(self._collection.count())

    def ingest_chunks(self, chunks: list[DocumentChunk]) -> int:
        """Upsert DocumentChunks into ChromaDB and return total indexed count."""
        if not chunks:
            return self.count()

        ids = [c.chunk_id for c in chunks]
        documents = [c.content for c in chunks]
        metadatas = [c.to_chroma_metadata() for c in chunks]

        self._collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
        )
        total = self.count()
        logger.info(
            "chromadb_chunks_upserted",
            upserted_count=len(chunks),
            collection_total=total,
            collection_name=self.collection_name,
        )
        return total

    def ensure_initialized(self, include_live_scrape: bool = False) -> int:
        """Populate the vector store from the curated corpus if currently empty."""
        current = self.count()
        if current > 0:
            return current
        chunks = build_knowledge_chunks(include_live_scrape=include_live_scrape)
        return self.ingest_chunks(chunks)

    @staticmethod
    def _lexical_overlap_boost(query: str, content: str, product_tag: str) -> float:
        """Compute a bounded lexical + domain concept match score in [0.0, 0.45]."""
        q_norm = _normalize_text(query)
        c_norm = _normalize_text(content)
        stop_words = {
            "what",
            "whats",
            "when",
            "where",
            "who",
            "why",
            "which",
            "was",
            "were",
            "the",
            "is",
            "are",
            "between",
            "and",
            "how",
            "does",
            "work",
            "with",
            "can",
            "do",
            "need",
            "to",
            "my",
            "via",
            "into",
            "using",
            "getnet",
            "get",
            "qual",
            "quais",
            "quando",
            "onde",
            "quem",
            "foi",
            "foram",
            "como",
            "para",
            "com",
            "uma",
            "que",
            "por",
            "pelo",
            "pela",
            "dos",
            "das",
            "nos",
            "nas",
            "sobre",
            "tem",
            "ter",
            "sao",
            "são",
            "esta",
            "está",
        }
        q_tokens = [t for t in _tokenize(q_norm) if len(t) >= 3 and t not in stop_words]
        if not q_tokens:
            return 0.0

        matched = sum(1 for t in q_tokens if t in c_norm)
        token_ratio = matched / len(q_tokens)

        concept_bonus = 0.0
        for cluster_name, keywords in _CONCEPT_CLUSTERS:
            q_hits = sum(1 for kw in keywords if kw in q_norm)
            c_hits = sum(1 for kw in keywords if kw in c_norm)
            if q_hits > 0 and c_hits > 0:
                concept_bonus = max(concept_bonus, 0.25)
                if cluster_name.split("_")[0] in product_tag:
                    concept_bonus = 0.32

        return min(0.45, round(token_ratio * 0.22 + concept_bonus, 4))

    def search(self, query: str, top_k: int | None = None) -> list[RetrievedChunk]:
        """Retrieve top-k chunks ordered by hybrid semantic + concept similarity."""
        self.ensure_initialized(include_live_scrape=False)
        total = self.count()
        if total == 0:
            return []

        k = min(total, top_k or settings.rag_top_k)
        # Fetch up to all documents (small corpus) so reranking is exact
        fetch_k = min(total, max(k * 3, 12))
        raw = self._collection.query(
            query_texts=[query],
            n_results=fetch_k,
            include=["documents", "metadatas", "distances"],
        )

        ids = (raw.get("ids") or [[]])[0]
        docs = (raw.get("documents") or [[]])[0]
        metas = (raw.get("metadatas") or [[]])[0]
        distances = (raw.get("distances") or [[]])[0]

        results: list[RetrievedChunk] = []
        for cid, doc, meta, dist in zip(ids, docs, metas, distances):
            # Cosine distance in [0, 2] -> base cosine similarity in [0, 1]
            cosine_sim = max(0.0, min(1.0, 1.0 - float(dist)))
            meta_dict = meta or {}
            product_tag = str(meta_dict.get("product_tag", "general"))
            boost = self._lexical_overlap_boost(query, doc, product_tag)

            # If query has zero lexical/concept overlap with the chunk, cap score
            if boost == 0.0:
                combined_score = round(cosine_sim * 0.30, 4)
            else:
                combined_score = round(min(0.99, cosine_sim * 0.65 + boost), 4)

            results.append(
                RetrievedChunk(
                    chunk_id=str(cid),
                    content=str(doc),
                    source_url=str(meta_dict.get("source_url", "https://www.getnet.net/en")),
                    title=str(meta_dict.get("title", "Getnet Knowledge Base")),
                    section=str(meta_dict.get("section", "General")),
                    product_tag=product_tag,
                    similarity_score=combined_score,
                )
            )

        results.sort(key=lambda item: item.similarity_score, reverse=True)
        return results[:k]


_default_vector_store: GetnetVectorStore | None = None


def get_vector_store() -> GetnetVectorStore:
    """Return singleton GetnetVectorStore instance."""
    global _default_vector_store
    if _default_vector_store is None:
        _default_vector_store = GetnetVectorStore()
    return _default_vector_store
