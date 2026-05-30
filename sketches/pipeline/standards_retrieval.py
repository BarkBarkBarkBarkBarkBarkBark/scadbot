from __future__ import annotations

import math
import re
from collections import Counter
from typing import Iterable

from django.conf import settings
from django.db.models import Q

from sketches.models import StandardChunk
from sketches.pipeline.standards_ingest import StandardIngestor
from sketches.pipeline.pgvector_store import search_similar, vector_row_count

def retrieve_relevant_chunks(query: str, limit: int = 5) -> list[dict]:
    query = (query or "").strip()
    if not query:
        return []

    if settings.OPENAI_API_KEY and vector_row_count() > 0:
        query_vectors = StandardIngestor()._embed_texts([query])
        if query_vectors:
            ranked = search_similar(query_vectors[0], limit=limit)
            if ranked:
                chunk_ids = [chunk_id for chunk_id, _ in ranked]
                chunk_map = {
                    chunk.pk: chunk
                    for chunk in StandardChunk.objects.filter(pk__in=chunk_ids).select_related("standard")
                }
                matches = []
                for chunk_id, score in ranked:
                    chunk = chunk_map.get(chunk_id)
                    if chunk is not None:
                        matches.append(_serialize_chunk(chunk, score))
                if matches:
                    return matches[:limit]

    embedded_chunks = list(
        StandardChunk.objects.exclude(embedding=[])
        .select_related("standard")
        .order_by("standard_id", "chunk_index")[:500]
    )
    if embedded_chunks and settings.OPENAI_API_KEY:
        query_vectors = StandardIngestor()._embed_texts([query])
        if query_vectors:
            query_vector = query_vectors[0]
            scored = []
            for chunk in embedded_chunks:
                if not isinstance(chunk.embedding, list) or not chunk.embedding:
                    continue
                score = _cosine_similarity(query_vector, chunk.embedding)
                if score > 0:
                    scored.append((score, chunk))
            scored.sort(key=lambda item: item[0], reverse=True)
            return [_serialize_chunk(chunk, score) for score, chunk in scored[:limit]]

    tokens = _tokens(query)
    if not tokens:
        return []

    q = Q()
    for token in tokens:
        q |= Q(text__icontains=token)
        q |= Q(standard__title__icontains=token)
        q |= Q(standard__category__icontains=token)

    chunks = list(
        StandardChunk.objects.filter(q)
        .select_related("standard")
        .order_by("standard_id", "chunk_index")[:200]
    )
    scored = []
    for chunk in chunks:
        haystack = f"{chunk.standard.title} {chunk.standard.category} {chunk.text}".lower()
        counts = Counter(token for token in tokens if token in haystack)
        score = float(sum(counts.values()))
        if score > 0:
            scored.append((score, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [_serialize_chunk(chunk, score) for score, chunk in scored[:limit]]


def build_standards_context(query: str, limit: int = 5) -> str:
    matches = retrieve_relevant_chunks(query, limit=limit)
    if not matches:
        return ""
    lines = []
    for idx, match in enumerate(matches, start=1):
        lines.append(
            f"[{idx}] {match['title']} | section={match['section_id'] or 'n/a'} | "
            f"category={match['category'] or 'General'} | score={match['score']:.3f}"
        )
        lines.append(match["text"])
    return "\n\n".join(lines)


def _serialize_chunk(chunk: StandardChunk, score: float) -> dict:
    return {
        "standard_id": chunk.standard.pk,
        "title": chunk.standard.title,
        "category": chunk.standard.category,
        "section_id": chunk.standard.section_id,
        "score": score,
        "text": chunk.text[:1200],
    }


def _tokens(text: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9_]{4,}", text.lower()) if token not in {"with", "from", "that", "this", "bridge"}]


def _cosine_similarity(left: Iterable[float], right: Iterable[float]) -> float:
    left_list = [float(value) for value in left]
    right_list = [float(value) for value in right]
    if len(left_list) != len(right_list) or not left_list:
        return 0.0
    numerator = sum(a * b for a, b in zip(left_list, right_list, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left_list))
    right_norm = math.sqrt(sum(b * b for b in right_list))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)
