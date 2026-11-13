"""Local hybrid RAG: Markdown ingestion, SQLite vector cache, cosine + BM25 retrieval."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
KNOWLEDGE = ROOT / "knowledge"
DB_PATH = ROOT / "data" / "rag.sqlite3"
EMBEDDING_MODEL = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
MAX_QUERY_CHARS = 1000
CHUNK_WORDS = 145
CHUNK_OVERLAP = 24


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9_'-]*", text.lower())


def _read_documents() -> list[dict[str, str]]:
    documents = []
    for path in sorted(KNOWLEDGE.glob("*.md")):
        current_source = path.stem.upper()
        text = path.read_text(encoding="utf-8")
        sections = re.split(r"(?m)^##\s+", text)
        for section in sections:
            lines = section.splitlines()
            if not lines or not lines[0].strip():
                continue
            heading = lines[0].strip().lstrip("# ")
            body = "\n".join(lines[1:]).strip()
            source_match = re.search(r"(?m)^Source:\s*([A-Z0-9-]+)\s*$", body)
            source_id = source_match.group(1) if source_match else current_source
            body = re.sub(r"(?m)^Source:\s*[A-Z0-9-]+\s*$", "", body).strip()
            if not body:
                continue
            tokens = body.split()
            start = 0
            while start < len(tokens):
                end = min(start + CHUNK_WORDS, len(tokens))
                chunk = " ".join(tokens[start:end]).strip()
                if chunk:
                    digest = hashlib.sha256(f"{source_id}\0{heading}\0{chunk}".encode()).hexdigest()[:16]
                    documents.append({"id": f"{source_id}-{digest}", "source_id": source_id, "title": heading, "text": chunk})
                if end == len(tokens):
                    break
                start = end - CHUNK_OVERLAP
    if not documents:
        raise RuntimeError("The knowledge folder has no readable Markdown sections.")
    return documents


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("""CREATE TABLE IF NOT EXISTS chunks (
        id TEXT PRIMARY KEY, source_id TEXT NOT NULL, title TEXT NOT NULL,
        content TEXT NOT NULL, content_hash TEXT NOT NULL,
        embedding_model TEXT, embedding TEXT, tokens TEXT NOT NULL
    )""")
    connection.execute("CREATE TABLE IF NOT EXISTS index_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    return connection


def _documents_digest(documents: list[dict[str, str]]) -> str:
    blob = "\n".join(f"{doc['id']}:{doc['text']}" for doc in documents)
    return hashlib.sha256(blob.encode()).hexdigest()


def index_stats() -> dict[str, Any]:
    documents = _read_documents()
    connection = _connect()
    try:
        rows = connection.execute("SELECT COUNT(*) AS total, SUM(CASE WHEN embedding IS NOT NULL AND embedding_model=? THEN 1 ELSE 0 END) AS dense FROM chunks", (EMBEDDING_MODEL,)).fetchone()
        metadata = dict(connection.execute("SELECT key,value FROM index_meta").fetchall())
        return {
            "document_chunks": len(documents),
            "indexed_chunks": int(rows["total"] or 0),
            "dense_chunks": int(rows["dense"] or 0),
            "knowledge_digest": _documents_digest(documents),
            "indexed_digest": metadata.get("knowledge_digest"),
            "embedding_model": EMBEDDING_MODEL,
            "dense_ready": int(rows["dense"] or 0) == len(documents) and metadata.get("knowledge_digest") == _documents_digest(documents),
        }
    finally:
        connection.close()


def _api_embeddings(texts: list[str]) -> list[list[float]]:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Embedding mode requires OPENAI_API_KEY on the server.")
    if not texts or len(texts) > 2048:
        raise ValueError("Embedding batch must contain between 1 and 2,048 texts.")
    payload = json.dumps({"model": EMBEDDING_MODEL, "input": texts, "encoding_format": "float"}).encode()
    request = urllib.request.Request(
        "https://api.openai.com/v1/embeddings", data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        detail = error.read(1000).decode("utf-8", errors="replace")
        raise RuntimeError(f"Embedding API returned HTTP {error.code}: {detail}") from None
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError(f"Embedding API connection failed: {error}") from None
    data = body.get("data")
    if not isinstance(data, list) or len(data) != len(texts):
        raise RuntimeError("Embedding API returned an unexpected number of vectors.")
    data.sort(key=lambda item: item.get("index", 0))
    vectors = [item.get("embedding") for item in data]
    if any(not isinstance(vector, list) or not vector for vector in vectors):
        raise RuntimeError("Embedding API returned an invalid vector.")
    dimension = len(vectors[0])
    if any(len(vector) != dimension for vector in vectors):
        raise RuntimeError("Embedding vectors have inconsistent dimensions.")
    return vectors


def build_dense_index(force: bool = False) -> dict[str, Any]:
    """Create or refresh embeddings and save the vectors locally in SQLite."""
    documents = _read_documents()
    digest = _documents_digest(documents)
    connection = _connect()
    try:
        metadata = dict(connection.execute("SELECT key,value FROM index_meta").fetchall())
        row = connection.execute("SELECT COUNT(*) FROM chunks WHERE embedding_model=? AND embedding IS NOT NULL", (EMBEDDING_MODEL,)).fetchone()
        dense_count = int(row[0] or 0)
        if not force and dense_count == len(documents) and metadata.get("knowledge_digest") == digest:
            return {"status": "already_indexed", "chunks": dense_count, "embedding_model": EMBEDDING_MODEL}

        vectors = _api_embeddings([item["text"] for item in documents])
        connection.execute("DELETE FROM chunks")
        for doc, vector in zip(documents, vectors, strict=True):
            tokens = _tokenize(doc["text"])
            connection.execute(
                "INSERT INTO chunks(id,source_id,title,content,content_hash,embedding_model,embedding,tokens) VALUES(?,?,?,?,?,?,?,?)",
                (doc["id"], doc["source_id"], doc["title"], doc["text"], hashlib.sha256(doc["text"].encode()).hexdigest(), EMBEDDING_MODEL, json.dumps(vector, separators=(",", ":")), json.dumps(tokens)),
            )
        connection.execute("INSERT OR REPLACE INTO index_meta(key,value) VALUES('knowledge_digest',?)", (digest,))
        connection.execute("INSERT OR REPLACE INTO index_meta(key,value) VALUES('embedding_model',?)", (EMBEDDING_MODEL,))
        connection.commit()
        return {"status": "indexed", "chunks": len(documents), "embedding_model": EMBEDDING_MODEL}
    finally:
        connection.close()


def _bm25_scores(query_tokens: list[str], documents: list[dict[str, Any]]) -> dict[str, float]:
    if not documents or not query_tokens:
        return {}
    tokenized = {doc["id"]: doc.get("tokens") or _tokenize(doc["text"]) for doc in documents}
    lengths = {doc_id: len(tokens) for doc_id, tokens in tokenized.items()}
    average_length = sum(lengths.values()) / max(len(lengths), 1)
    doc_frequency = Counter(token for tokens in tokenized.values() for token in set(tokens))
    total_docs = len(documents)
    scores = {}
    k1, b = 1.5, 0.75
    for doc in documents:
        tokens = tokenized[doc["id"]]
        counts = Counter(tokens)
        score = 0.0
        for term in set(query_tokens):
            frequency = counts[term]
            if frequency == 0:
                continue
            idf = math.log(1 + (total_docs - doc_frequency[term] + 0.5) / (doc_frequency[term] + 0.5))
            denominator = frequency + k1 * (1 - b + b * lengths[doc["id"]] / max(average_length, 1))
            score += idf * (frequency * (k1 + 1)) / denominator
        scores[doc["id"]] = score
    return scores


def _cosine_scores(query_vector: list[float], documents: list[dict[str, Any]]) -> dict[str, float]:
    result = {}
    for doc in documents:
        vector = doc.get("embedding")
        if not vector or len(vector) != len(query_vector):
            continue
        dot = sum(float(a) * float(b) for a, b in zip(query_vector, vector, strict=True))
        q_norm = math.sqrt(sum(float(value) ** 2 for value in query_vector))
        d_norm = math.sqrt(sum(float(value) ** 2 for value in vector))
        result[doc["id"]] = dot / (q_norm * d_norm) if q_norm and d_norm else 0.0
    return result


def retrieve(query: str, top_k: int = 3, use_embeddings: bool = False) -> dict[str, Any]:
    """Hybrid retrieval: normalized dense cosine + BM25, with citations."""
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY_CHARS:
        raise ValueError(f"Query must contain 1–{MAX_QUERY_CHARS} characters.")
    top_k = max(1, min(int(top_k), 5))
    connection = _connect()
    try:
        rows = connection.execute("SELECT id,source_id,title,content,tokens,embedding FROM chunks").fetchall()
        documents = [
            {"id": row["id"], "source_id": row["source_id"], "title": row["title"], "text": row["content"],
             "tokens": json.loads(row["tokens"]), "embedding": json.loads(row["embedding"]) if row["embedding"] else None}
            for row in rows
        ]
        if not documents:
            documents = _read_documents()
        bm25 = _bm25_scores(_tokenize(query), documents)
        max_bm25 = max(bm25.values(), default=0.0)
        normalized_bm25 = {key: value / max_bm25 if max_bm25 else 0.0 for key, value in bm25.items()}

        dense_scores = {}
        method = "bm25"
        if use_embeddings and os.environ.get("OPENAI_API_KEY"):
            stats = index_stats()
            if not stats["dense_ready"]:
                build_dense_index()
                connection.close()
                connection = _connect()
                rows = connection.execute("SELECT id,source_id,title,content,tokens,embedding FROM chunks").fetchall()
                documents = [{"id": row["id"], "source_id": row["source_id"], "title": row["title"], "text": row["content"], "tokens": json.loads(row["tokens"]), "embedding": json.loads(row["embedding"]) if row["embedding"] else None} for row in rows]
                bm25 = _bm25_scores(_tokenize(query), documents)
                max_bm25 = max(bm25.values(), default=0.0)
                normalized_bm25 = {key: value / max_bm25 if max_bm25 else 0.0 for key, value in bm25.items()}
            query_vector = _api_embeddings([query])[0]
            dense_scores = _cosine_scores(query_vector, documents)
            method = "hybrid: cosine embeddings + BM25"

        if dense_scores:
            min_dense = min(dense_scores.values())
            max_dense = max(dense_scores.values())
            normalized_dense = {key: (value - min_dense) / (max_dense - min_dense) if max_dense > min_dense else 1.0 for key, value in dense_scores.items()}
            scores = {doc["id"]: 0.7 * normalized_dense.get(doc["id"], 0.0) + 0.3 * normalized_bm25.get(doc["id"], 0.0) for doc in documents}
        else:
            scores = normalized_bm25
        ranked = sorted(documents, key=lambda doc: scores.get(doc["id"], 0.0), reverse=True)
        results = []
        for doc in ranked[:top_k]:
            score = scores.get(doc["id"], 0.0)
            if score <= 0:
                continue
            results.append({"source_id": doc["source_id"], "title": doc["title"], "text": doc["text"], "score": round(score, 4)})
        return {"method": method, "query": query, "results": results}
    finally:
        connection.close()
