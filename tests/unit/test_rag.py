"""Unit tests for the Getnet RAG ingestion, chunking, and ChromaDB retrieval pipeline."""

from __future__ import annotations

import pytest

from src.rag.ingest import (
    load_markdown_corpus,
    scrape_getnet_url,
    split_text_with_overlap,
)
from src.rag.vector_store import GetnetVectorStore


def test_markdown_corpus_contains_all_required_sections_and_urls() -> None:
    """Verify the curated corpus has chunks and official source_url metadata for all challenge topics."""
    chunks = load_markdown_corpus()
    assert len(chunks) >= 6

    tags = {c.product_tag for c in chunks}
    expected_tags = {
        "institutional_overview",
        "pos_terminals_comparison",
        "pix_bank_account_rules",
        "receivables_advance_antecipacao",
        "crediario_installments",
        "payment_link_whatsapp",
    }
    assert expected_tags.issubset(tags)

    urls = {c.source_url for c in chunks}
    assert "https://www.getnet.net/en" in urls
    assert "https://site.getnet.com.br/maquininhas/" in urls
    assert "https://site.getnet.com.br/link-de-pagamento/" in urls

    combined_text = "\n".join(c.content for c in chunks)
    for model_name in ("Get Tap", "Get Mini", "Get Lite", "Get Clássica", "Get Smart"):
        assert model_name in combined_text


def test_split_text_with_overlap() -> None:
    """Verify recursive paragraph splitter respects chunk size and overlap."""
    sample = "\n\n".join(
        [f"Paragraph {i}: " + ("Getnet payment solutions " * 15) for i in range(6)]
    )
    pieces = split_text_with_overlap(sample, chunk_size=450, chunk_overlap=80)
    assert len(pieces) >= 3
    assert all(len(p) <= 600 for p in pieces)


def test_chromadb_ingestion_and_top_k_retrieval_for_all_5_product_scenarios() -> None:
    """Verify ChromaDB indexes the corpus and ranks the right product chunk #1 for all 5 RAG scenarios."""
    store = GetnetVectorStore(
        collection_name="test_getnet_kb",
        ephemeral=True,
    )
    chunks = load_markdown_corpus()
    indexed_count = store.ingest_chunks(chunks)
    assert indexed_count == len(chunks)

    scenarios = [
        (
            "What's the difference between the Get Clássica and the Get Smart?",
            "pos_terminals_comparison",
            "Android",
        ),
        (
            "Do I need a bank account to receive my sales via Pix?",
            "pix_bank_account_rules",
            "domicílio bancário",
        ),
        (
            "How does receivables advance (antecipação) work with Getnet?",
            "receivables_advance_antecipacao",
            "Antecipação",
        ),
        (
            "How many installments can I split a sale into with the crediário?",
            "crediario_installments",
            "48 installments",
        ),
        (
            "Can I sell through WhatsApp using the Payment Link?",
            "payment_link_whatsapp",
            "WhatsApp",
        ),
    ]

    for query, expected_tag, expected_keyword in scenarios:
        results = store.search(query, top_k=3)
        assert len(results) >= 1
        top_hit = results[0]
        assert top_hit.product_tag == expected_tag, (
            f"Query '{query}' matched '{top_hit.product_tag}' instead of '{expected_tag}'"
        )
        assert expected_keyword.lower() in top_hit.content.lower()
        assert top_hit.similarity_score >= 0.45


def test_unlisted_product_has_low_similarity_for_fallback_detection() -> None:
    """Verify an unlisted/newly launched product query yields low similarity so live fallback triggers."""
    store = GetnetVectorStore(
        collection_name="test_getnet_fallback",
        ephemeral=True,
    )
    store.ingest_chunks(load_markdown_corpus())

    results = store.search("Quantum Holographic Satellite Orbit 2099", top_k=2)
    assert len(results) >= 1
    assert results[0].similarity_score < 0.35


def test_scrape_getnet_url_graceful_error_handling(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify live scraper handles connection errors gracefully without raising."""
    import httpx

    def _mock_get(*args: object, **kwargs: object) -> object:
        raise httpx.ConnectError("simulated network firewall")

    monkeypatch.setattr(httpx.Client, "get", _mock_get)
    scraped = scrape_getnet_url("https://www.getnet.net/en", timeout=1.0)
    assert scraped == []


def test_openai_chroma_embedding_function_integration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify OpenAIChromaEmbeddingFunction delegates to OpenAIEmbeddings when configured."""
    from langchain_openai import OpenAIEmbeddings
    from src.rag.vector_store import OpenAIChromaEmbeddingFunction

    def _mock_embed_documents(
        self: object, texts: list[str], chunk_size: int | None = None
    ) -> list[list[float]]:
        return [[0.25] * 16 for _ in texts]

    monkeypatch.setattr(OpenAIEmbeddings, "embed_documents", _mock_embed_documents)
    emb_fn = OpenAIChromaEmbeddingFunction(model="text-embedding-3-small", api_key="sk-test-key")
    vectors = emb_fn(["Get Clássica vs Get Smart", "Pix domicílio bancário"])
    assert len(vectors) == 2
    assert len(vectors[0]) == 16
    assert emb_fn.name() == "openai_text_embedding_3_small"
