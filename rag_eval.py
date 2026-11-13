"""Small labeled retrieval evaluation for the bundled synthetic runbooks."""

from __future__ import annotations

import argparse
import json

from rag import build_dense_index, retrieve

CASES = [
    {"query": "elevated 502 and 503 rate after newest service release", "relevant": "RB-DEPLOY-5XX"},
    {"query": "high route p95 latency and CPU saturation while requests rise", "relevant": "RB-LATENCY"},
    {"query": "clients timing out while acquiring pooled database connections", "relevant": "RB-DB-POOL"},
    {"query": "login token refresh and authentication provider errors", "relevant": "RB-AUTH"},
    {"query": "separate facts from hypotheses and verify a human approval", "relevant": "RB-EVIDENCE"},
    {"query": "database is healthy but one client has connection acquire timeouts", "relevant": "RB-DB-POOL"},
    {"query": "do not assume a release caused errors just because they happened after deploy", "relevant": "RB-DEPLOY-5XX"},
    {"query": "avoid scaling if a downstream dependency is the actual bottleneck", "relevant": "RB-LATENCY"},
]


def evaluate(use_embeddings: bool) -> dict:
    reciprocal_ranks = []
    hits = 0
    rows = []
    for case in CASES:
        result = retrieve(case["query"], top_k=3, use_embeddings=use_embeddings)
        ranked_sources = [item["source_id"] for item in result["results"]]
        rank = next((index + 1 for index, source in enumerate(ranked_sources) if source == case["relevant"]), None)
        if rank is not None:
            hits += 1
            reciprocal_ranks.append(1.0 / rank)
        else:
            reciprocal_ranks.append(0.0)
        rows.append({"query": case["query"], "expected": case["relevant"], "ranked": ranked_sources, "hit_at_3": rank is not None})
    return {
        "retrieval": "hybrid dense embeddings + BM25" if use_embeddings else "BM25",
        "queries": len(CASES),
        "recall_at_3": round(hits / len(CASES), 4),
        "mrr_at_3": round(sum(reciprocal_ranks) / len(CASES), 4),
        "cases": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dense", action="store_true", help="Build/use the OpenAI dense vector index (requires OPENAI_API_KEY).")
    args = parser.parse_args()
    if args.dense:
        print(json.dumps(build_dense_index(), indent=2))
    print(json.dumps(evaluate(args.dense), indent=2))


if __name__ == "__main__":
    main()
