from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse

import fitz  # type: ignore[reportMissingImports]
import requests
from bs4 import BeautifulSoup
from django.conf import settings
from django.utils import timezone

from sketches.models import BridgeStandard, StandardChunk
from sketches.pipeline.pgvector_store import upsert_embedding

try:
    import pytesseract  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    pytesseract = None

try:
    from PIL import Image
except ImportError:  # pragma: no cover - Pillow is already required but stay defensive
    Image = None


@dataclass(slots=True)
class DiscoveredDocument:
    title: str
    url: str
    source_type: str = "pdf"
    category: str = "General"
    section_id: str = ""


class StandardIngestor:
    BASE_URL = "https://dot.ca.gov/programs/engineering-services/manuals/bridge-standard-details"

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "scadforge-standards-ingestor/1.0",
        })
        self.storage_dir = Path(settings.STANDARDS_STORAGE_DIR)
        self.pdf_dir = self.storage_dir / "pdfs"
        self.pdf_dir.mkdir(parents=True, exist_ok=True)

    def discover_documents(self, limit: int | None = None) -> list[DiscoveredDocument]:
        response = self.session.get(self.BASE_URL, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        docs: list[DiscoveredDocument] = []
        seen: set[str] = set()
        for tag in soup.find_all("a", href=True):
            href_value = tag.get("href")
            href = href_value.strip() if isinstance(href_value, str) else ""
            if not href.lower().endswith(".pdf"):
                continue
            url = urljoin(self.BASE_URL, href)
            if url in seen:
                continue
            seen.add(url)
            title = tag.get_text(" ", strip=True) or Path(urlparse(url).path).name
            docs.append(DiscoveredDocument(
                title=title,
                url=url,
                source_type="pdf",
                category=self._categorize_doc(title),
                section_id=self._section_id(title, url),
            ))
            if limit and len(docs) >= limit:
                break
        return docs

    def ingest(self, *, limit: int | None = None, refresh: bool = False,
               with_embeddings: bool = True) -> dict[str, int]:
        stats = {
            "discovered": 0,
            "downloaded": 0,
            "extracted": 0,
            "chunked": 0,
            "embedded": 0,
            "failed": 0,
        }
        documents = self.discover_documents(limit=limit)
        stats["discovered"] = len(documents)

        for doc in documents:
            standard, _ = BridgeStandard.objects.update_or_create(
                source_url=doc.url,
                defaults={
                    "title": doc.title,
                    "source_type": doc.source_type,
                    "category": doc.category,
                    "section_id": doc.section_id,
                    "status": "discovered",
                },
            )

            if not refresh and standard.status in {"chunked", "embedded"} and StandardChunk.objects.filter(standard=standard).exists():
                continue

            try:
                pdf_path, pdf_bytes = self._download_document(doc.url)
                stats["downloaded"] += 1
                text, page_count, extraction_meta = self._extract_pdf_text(pdf_bytes)
                stats["extracted"] += 1

                standard.local_path = str(pdf_path)
                standard.page_count = page_count
                standard.text_content = text
                standard.summary = self._summarize_text(text)
                standard.content_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
                standard.metadata_json = {
                    **(standard.metadata_json or {}),
                    **extraction_meta,
                    "document_size_bytes": len(pdf_bytes),
                }
                standard.fetched_at = timezone.now()
                standard.extracted_at = timezone.now()
                standard.error = ""
                standard.status = "extracted"
                standard.save()

                chunk_count = self._store_chunks(standard, text)
                stats["chunked"] += chunk_count
                standard.status = "chunked"
                standard.save(update_fields=["status", "updated"])

                if with_embeddings and settings.OPENAI_API_KEY:
                    embedded = self._embed_chunks(standard)
                    stats["embedded"] += embedded
                standard.save(update_fields=["status", "embedded_at", "updated"])
            except Exception as exc:  # noqa: BLE001
                standard.status = "failed"
                standard.error = str(exc)
                standard.save(update_fields=["status", "error", "updated"])
                stats["failed"] += 1
        return stats

    def _download_document(self, url: str) -> tuple[Path, bytes]:
        response = self.session.get(url, timeout=60)
        response.raise_for_status()
        data = response.content
        suffix = Path(urlparse(url).path).suffix or ".pdf"
        filename = f"{hashlib.sha1(url.encode('utf-8')).hexdigest()}{suffix}"
        path = self.pdf_dir / filename
        path.write_bytes(data)
        return path, data

    def _extract_pdf_text(self, pdf_bytes: bytes) -> tuple[str, int, dict]:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages: list[str] = []
        ocr_pages = 0
        extraction_method = "text"
        for page_index in range(doc.page_count):
            page = doc.load_page(page_index)
            raw_text = page.get_text("text")
            text = raw_text.strip() if isinstance(raw_text, str) else ""
            if not text:
                ocr_text = self._ocr_page(page)
                if ocr_text:
                    text = ocr_text.strip()
                    ocr_pages += 1
                    extraction_method = "text+ocr"
            if text:
                pages.append(f"\n\n[page {page_index + 1}]\n{text}")
        return "".join(pages).strip(), doc.page_count, {
            "extraction_method": extraction_method,
            "ocr_pages": ocr_pages,
        }

    def _ocr_page(self, page: fitz.Page) -> str:
        if pytesseract is None or Image is None:
            return ""
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        image = Image.open(io.BytesIO(pix.tobytes("png")))
        try:
            return pytesseract.image_to_string(image)
        except Exception:  # noqa: BLE001
            return ""

    def _store_chunks(self, standard: BridgeStandard, text: str) -> int:
        chunks = self._chunk_text(text)
        StandardChunk.objects.filter(standard=standard).delete()
        objs = []
        for idx, chunk in enumerate(chunks):
            objs.append(StandardChunk(
                standard=standard,
                chunk_index=idx,
                text=chunk,
                char_count=len(chunk),
                token_estimate=max(1, len(chunk) // 4),
                metadata_json={
                    "section_id": standard.section_id,
                    "category": standard.category,
                },
            ))
        StandardChunk.objects.bulk_create(objs)
        return len(objs)

    def _embed_chunks(self, standard: BridgeStandard) -> int:
        chunks = list(StandardChunk.objects.filter(standard=standard).order_by("chunk_index"))
        if not chunks:
            return 0
        vectors = self._embed_texts(chunk.text for chunk in chunks)
        for chunk, vector in zip(chunks, vectors, strict=False):
            chunk.embedding = vector
            chunk.embedding_model = settings.OPENAI_EMBED_MODEL
        StandardChunk.objects.bulk_update(chunks, ["embedding", "embedding_model", "updated"])
        for chunk, vector in zip(chunks, vectors, strict=False):
            upsert_embedding(chunk.pk, vector)
        standard.status = "embedded"
        standard.embedded_at = timezone.now()
        return len(vectors)

    def _embed_texts(self, texts: Iterable[str]) -> list[list[float]]:
        inputs = [text for text in texts if text.strip()]
        if not inputs:
            return []
        response = requests.post(
            f"{settings.OPENAI_BASE_URL.rstrip('/')}/embeddings",
            headers={
                "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.OPENAI_EMBED_MODEL,
                "input": inputs,
            },
            timeout=120,
        )
        response.raise_for_status()
        payload = response.json()
        return [item["embedding"] for item in payload.get("data", [])]

    def _chunk_text(self, text: str) -> list[str]:
        cleaned = re.sub(r"\n{3,}", "\n\n", text).strip()
        if not cleaned:
            return []
        paragraphs = [part.strip() for part in cleaned.split("\n\n") if part.strip()]
        chunks: list[str] = []
        current = ""
        chunk_size = settings.STANDARDS_CHUNK_SIZE
        overlap = settings.STANDARDS_CHUNK_OVERLAP
        for para in paragraphs:
            candidate = f"{current}\n\n{para}".strip() if current else para
            if len(candidate) <= chunk_size:
                current = candidate
                continue
            if current:
                chunks.append(current)
            if len(para) <= chunk_size:
                current = para
                continue
            start = 0
            while start < len(para):
                end = min(len(para), start + chunk_size)
                piece = para[start:end].strip()
                if piece:
                    chunks.append(piece)
                if end >= len(para):
                    current = ""
                    break
                start = max(end - overlap, start + 1)
            else:
                current = ""
        if current:
            chunks.append(current)
        return chunks

    def _summarize_text(self, text: str) -> str:
        clipped = re.sub(r"\s+", " ", text).strip()
        return clipped[:500]

    def _categorize_doc(self, title: str) -> str:
        title_lower = title.lower()
        if any(x in title_lower for x in ["suspension", "cable", "catenary"]):
            return "Suspension Bridges"
        if any(x in title_lower for x in ["arch", "bow"]):
            return "Arch Bridges"
        if any(x in title_lower for x in ["truss", "beam", "girder"]):
            return "Truss & Beam Bridges"
        if any(x in title_lower for x in ["steel", "material"]):
            return "Materials"
        if any(x in title_lower for x in ["foundation", "pier", "abutment"]):
            return "Foundations & Supports"
        if any(x in title_lower for x in ["load", "force", "stress", "design"]):
            return "Design & Loading"
        if any(x in title_lower for x in ["safety", "rail", "guard"]):
            return "Safety"
        return "General"

    def _section_id(self, title: str, url: str) -> str:
        for value in (title, urlparse(url).path):
            match = re.search(r"(xs[\w-]+)", value, re.IGNORECASE)
            if match:
                return match.group(1).lower()
        return ""
