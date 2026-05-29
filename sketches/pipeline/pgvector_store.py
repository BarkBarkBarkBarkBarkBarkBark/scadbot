from __future__ import annotations

from typing import Iterable

from django.conf import settings
from django.db import connection


def using_pgvector() -> bool:
    return connection.vendor == "postgresql"


def ensure_pgvector() -> bool:
    if not using_pgvector():
        return False
    dim = int(settings.OPENAI_EMBED_DIM)
    with connection.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS sketches_standardchunkvector (
                standard_chunk_id bigint PRIMARY KEY
                    REFERENCES sketches_standardchunk(id) ON DELETE CASCADE,
                embedding vector({dim}) NOT NULL,
                updated_at timestamptz NOT NULL DEFAULT NOW()
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS sketches_standardchunkvector_embedding_ivfflat
            ON sketches_standardchunkvector
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100)
            """
        )
    return True


def upsert_embedding(chunk_id: int, vector: Iterable[float]) -> bool:
    if not ensure_pgvector():
        return False
    values = [float(value) for value in vector]
    expected_dim = int(settings.OPENAI_EMBED_DIM)
    if len(values) != expected_dim:
        raise ValueError(
            f"embedding dimension mismatch: got {len(values)}, expected {expected_dim}. "
            "Set OPENAI_EMBED_DIM to match the embedding model."
        )
    literal = "[" + ",".join(f"{value:.9f}" for value in values) + "]"
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO sketches_standardchunkvector (standard_chunk_id, embedding, updated_at)
            VALUES (%s, %s::vector, NOW())
            ON CONFLICT (standard_chunk_id)
            DO UPDATE SET embedding = EXCLUDED.embedding, updated_at = NOW()
            """,
            [chunk_id, literal],
        )
    return True


def search_similar(vector: Iterable[float], limit: int = 5) -> list[tuple[int, float]]:
    if not using_pgvector():
        return []
    values = [float(value) for value in vector]
    expected_dim = int(settings.OPENAI_EMBED_DIM)
    if len(values) != expected_dim:
        return []
    ensure_pgvector()
    literal = "[" + ",".join(f"{value:.9f}" for value in values) + "]"
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT standard_chunk_id,
                   1 - (embedding <=> %s::vector) AS score
            FROM sketches_standardchunkvector
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            [literal, literal, int(limit)],
        )
        rows = cursor.fetchall()
    return [(int(chunk_id), float(score)) for chunk_id, score in rows]


def vector_row_count() -> int:
    if not using_pgvector():
        return 0
    ensure_pgvector()
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM sketches_standardchunkvector")
        row = cursor.fetchone()
    return int(row[0] if row else 0)
