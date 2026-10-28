"""CLI script to ingest the Getnet Knowledge Base (curated corpus + live web scraping) into ChromaDB."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.rag.ingest import DEFAULT_GETNET_URLS, build_knowledge_chunks
from src.rag.vector_store import get_vector_store


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingest Getnet product corpus and live web URLs into persistent ChromaDB."
    )
    parser.add_argument(
        "--skip-live-scrape",
        action="store_true",
        help="Only ingest the curated local markdown corpus without scraping live URLs.",
    )
    parser.add_argument(
        "--query",
        type=str,
        default="What's the difference between the Get Clássica and the Get Smart?",
        help="Optional sample query to test retrieval after indexing.",
    )
    args = parser.parse_args()

    include_scrape = not args.skip_live_scrape
    print(
        f"[Getnet RAG] Building chunks (include_live_scrape={include_scrape}, "
        f"urls={len(DEFAULT_GETNET_URLS)})..."
    )
    chunks = build_knowledge_chunks(include_live_scrape=include_scrape)
    store = get_vector_store()
    total = store.ingest_chunks(chunks)
    print(f"[Getnet RAG] Successfully indexed {len(chunks)} chunks (Collection total: {total}).")

    if args.query:
        results = store.search(args.query, top_k=2)
        print(f"\n[Sample Query] {args.query}")
        for idx, item in enumerate(results, start=1):
            print(
                f"  #{idx} [{item.product_tag}] score={item.similarity_score:.3f} "
                f"source={item.source_url} ({item.section})"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
