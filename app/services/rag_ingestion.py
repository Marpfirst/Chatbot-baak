# app/services/rag_ingestion.py
"""
RAG Ingestion Service
- Membaca file Markdown di data/knowledge_base
- Ekstrak title & section berdasarkan heading (#, ##, ###)
- Chunking berbasis paragraf dengan overlap ringan (tanpa tiktoken)
- Upsert ke Pinecone lewat llm_service.upsert_knowledge()
- Retrieval test lewat llm_service.search_knowledge_base()

Catatan:
- Tidak menambah dependency baru
- Konsisten dengan llm_service yang sudah ada (async API)
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import settings
from app.services.llm_service import llm_service

logger = logging.getLogger(__name__)


@dataclass
class _Chunk:
    content: str
    chunk_index: int
    estimated_tokens: int


class RAGIngestionService:
    def __init__(self):
        self.knowledge_base_path = Path("data/knowledge_base")
        # Target ukuran chunk (konversi kasar 1 token ~ 4 karakter)
        self.min_tokens = 500
        self.max_tokens = 800
        self.overlap_tokens = 80
        self.chars_per_token = 4
        
        # === regex khusus "Daftar Mata Kuliah" (rapih: simpan di instance) ===
        self._re_daftar_header = re.compile(
            r'^\s{0,3}#{1,6}\s*daftar\s+mata\s*kuliah\b', re.I | re.M
        )
        self._re_daftar_item = re.compile(
            r'^\s*-\s*\[([^\]]+)\]\((https?://[^\s)]+)\)\s*$', re.M
        )
    # ---------------- Helpers ----------------

    def _estimate_tokens(self, text: str) -> int:
        """Perkiraan jumlah token dari jumlah karakter (kasar, cukup untuk heuristik)."""
        return max(1, len(text) // self.chars_per_token)

    def _extract_title(self, content: str, filename: str) -> str:
        """Ambil title dari heading pertama '# ' jika ada; jika tidak gunakan nama file."""
        m = re.search(r"^#\s+(.+)$", content, flags=re.MULTILINE)
        if m:
            return m.group(1).strip()
        return Path(filename).stem.replace("_", " ").title()

    def _extract_sections(self, content: str, default_title: str) -> List[Dict[str, str]]:
        """
        Ekstrak bagian-bagian (section) berdasarkan heading markdown (#, ##, ###, dst).
        Menghasilkan list dict: { 'heading': '## Judul', 'content': '...' }.
        """
        sections: List[Dict[str, str]] = []
        lines = content.splitlines()
        current_heading = f"# {default_title}"
        current_buffer: List[str] = []

        header_re = re.compile(r"^#{1,6}\s+")
        for line in lines:
            if header_re.match(line):
                # simpan section sebelumnya
                if current_buffer:
                    sections.append(
                        {"heading": current_heading.strip(), "content": "\n".join(current_buffer).strip()}
                    )
                current_heading = line.strip()
                current_buffer = []
            else:
                current_buffer.append(line)

        # section terakhir
        if current_buffer:
            sections.append(
                {"heading": current_heading.strip(), "content": "\n".join(current_buffer).strip()}
            )

        # fallback jika tidak ada heading sama sekali
        if not sections:
            sections.append({"heading": f"# {default_title}", "content": content.strip()})

        return sections

    def _last_overlap_text(self, text: str) -> str:
        """
        Ambil overlap dari akhir chunk sebelumnya.
        Strategi ringan: ambil ~overlap_chars terakhir yang dipotong di batas kalimat.
        """
        overlap_chars = self.overlap_tokens * self.chars_per_token
        tail = text[-overlap_chars:]
        # potong di awal kalimat terdekat
        parts = re.split(r"(?<=[.!?])\s+", tail)
        if len(parts) > 1:
            return " ".join(parts[-2:]).strip()
        return tail.strip()

    def _chunk_paragraphs(self, content: str) -> List[_Chunk]:
        """
        Chunk berbasis paragraf dengan overlap antar-chunk.
        - Usahakan panjang di antara min_tokens..max_tokens (perkiraan)
        - Jika total konten kecil, tetap hasilkan 1 chunk
        """
        min_chars = self.min_tokens * self.chars_per_token
        max_chars = self.max_tokens * self.chars_per_token

        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
        chunks: List[_Chunk] = []
        buf: List[str] = []
        size = 0
        idx = 0

        def flush(force: bool = False):
            nonlocal buf, size, idx
            if not buf:
                return
            text = "\n\n".join(buf).strip()
            if not text:
                buf, size = [], 0
                return
            # untuk chunk terakhir yang pendek, tetap keluarkan jika force=True
            if force or len(text) >= min_chars or not chunks:
                chunks.append(
                    _Chunk(content=text, chunk_index=idx, estimated_tokens=self._estimate_tokens(text))
                )
                idx += 1
                buf, size = [], 0

        for para in paragraphs:
            candidate_size = size + (2 if buf else 0) + len(para)
            if candidate_size > max_chars and buf:
                # finalize chunk
                flush(force=True)
                # overlap
                if chunks:
                    overlap = self._last_overlap_text(chunks[-1].content)
                    if overlap:
                        buf.append(overlap)
                        size += len(overlap)
            # tambahkan paragraf
            buf.append(para)
            size += (2 if len(buf) > 1 else 0) + len(para)

        # final flush
        flush(force=True)
        return chunks
    
    # ---------- KHUSUS: Daftar Mata Kuliah ----------
    def _is_daftar_mk_section(self, heading: str, text: str) -> bool:
        """True kalau section ini adalah 'Daftar Mata Kuliah' (berdasarkan heading atau banyak bullet link)."""
        h = (heading or "").strip()
        t = (text or "").strip()
        if self._re_daftar_header.search(h):
            return True
        # fallback: anggap daftar lengkap jika ≥ 5 bullet link
        return len(self._re_daftar_item.findall(t)) >= 5

    def _normalize_daftar_mk_list(self, text: str) -> str:
        """
        Tarik SEMUA bullet '- [Label](URL)' → kembalikan markdown bersih,
        urutkan D3 dulu, lalu S1, lalu lainnya. Hilangkan duplikat.
        """
        items = self._re_daftar_item.findall(text or "")
        if not items:
            return (text or "").strip()

        uniq = {(label.strip(), url.strip()) for (label, url) in items}

        def _rank(it):
            lab = it[0].upper()
            if lab.startswith("D3 "): return (0, lab)
            if lab.startswith("S1 "): return (1, lab)
            return (2, lab)

        ordered = sorted(uniq, key=_rank)
        return "\n".join(f"- [{label}]({url})" for (label, url) in ordered)

    # ---------------- Document processing ----------------
    def _process_file(self, file_path: Path) -> List[Dict[str, Any]]:
        try:
            text = file_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Gagal membaca {file_path}: {e}")
            return []

        if not text.strip():
            logger.warning(f"File kosong: {file_path.name}")
            return []

        title = self._extract_title(text, file_path.name)
        sections = self._extract_sections(text, title)

        docs: List[Dict[str, Any]] = []

        # (1) BUFFER untuk agregasi "Daftar Mata Kuliah"
        daftar_mk_buffers: List[str] = []

        for sec in sections:
            sec_heading = sec["heading"].strip()
            sec_text = (sec["content"] or "").strip()
            if not sec_text:
                continue

            # (2) KHUSUS: "Daftar Mata Kuliah" → SATU dokumen utuh, TANPA chunking
            if self._is_daftar_mk_section(sec_heading, sec_text):
                normalized = self._normalize_daftar_mk_list(sec_text)

                # koleksi ke buffer agregat juga
                daftar_mk_buffers.append(normalized)

                raw_id = f"{file_path.stem}|{sec_heading}|daftar_mk|{hashlib.md5(normalized.encode('utf-8')).hexdigest()[:8]}"
                doc_id = hashlib.sha1(raw_id.encode("utf-8")).hexdigest()[:20]
                docs.append({
                    "id": doc_id,
                    "content": normalized,
                    "title": title,
                    "source": file_path.name,
                    "section": sec_heading,
                    "chunk_index": 0,
                    "estimated_tokens": self._estimate_tokens(normalized),
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                    "doc_key": "daftar_mk", 
                })
                continue

            # DEFAULT: chunking biasa
            sec_chunks = self._chunk_paragraphs(sec_text) or [
                _Chunk(content=sec_text, chunk_index=0, estimated_tokens=self._estimate_tokens(sec_text))
            ]
            for ch in sec_chunks:
                raw_id = f"{file_path.stem}|{sec_heading}|{ch.chunk_index}|{hashlib.md5(ch.content.encode('utf-8')).hexdigest()[:8]}"
                doc_id = hashlib.sha1(raw_id.encode("utf-8")).hexdigest()[:20]
                
                # Base document structure
                doc = {
                    "id": doc_id,
                    "content": ch.content,
                    "title": title,
                    "source": file_path.name,
                    "section": sec_heading,
                    "chunk_index": ch.chunk_index,
                    "estimated_tokens": ch.estimated_tokens,
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                }
                
                # === AUTO-TAGGING doc_key berdasarkan heading ===
                sec_h = (sec_heading or "").strip()
                
                # Definisi jadwal kuliah
                if re.search(r"^\s*####\s*Jadwal\s+Kuliah\b", sec_h, flags=re.I):
                    doc["doc_key"] = "definisi_jadwal"
                
                # Cara membaca jadwal kuliah
                elif re.search(r"^\s*#####\s*Cara\s+Membaca\s+Jadwal\s+Kuliah\b", sec_h, flags=re.I):
                    doc["doc_key"] = "cara_baca_jadwal"
                
                # Waktu kuliah (tabel jam kuliah)
                elif re.search(r"^\s*#####\s*Waktu\s+Kuliah\b", sec_h, flags=re.I):
                    doc["doc_key"] = "waktu_kuliah"
                
                # Info ujian umum
                elif re.search(r"^\s*####\s*Jadwal\s+Ujian\b", sec_h, flags=re.I):
                    doc["doc_key"] = "info_ujian"
                
                # Tata tertib ujian
                elif re.search(r"\bTata\s+Tertib\s+Ujian\b", sec_h, flags=re.I):
                    doc["doc_key"] = "tata_tertib_ujian"
                
                # Ujian susulan
                elif re.search(r"\bUjian\s+Susulan\b", sec_h, flags=re.I):
                    doc["doc_key"] = "ujian_susulan"
                
                # Ujian bentrok
                elif re.search(r"\bUjian\s+Bentrok\b", sec_h, flags=re.I):
                    doc["doc_key"] = "ujian_bentrok"
                
                docs.append(doc)

        # (3) DOKUMEN AGREGAT (SATU dokumen besar berisi seluruh daftar dari file ini)
        if daftar_mk_buffers:
            full_text = "\n\n".join(daftar_mk_buffers).strip()
            raw_id = f"{file_path.stem}|DAFTAR_MK_INDEX|{hashlib.md5(full_text.encode('utf-8')).hexdigest()[:8]}"
            doc_id = hashlib.sha1(raw_id.encode("utf-8")).hexdigest()[:20]
            docs.append({
                "id": doc_id,
                "content": full_text,
                "title": "Daftar Mata Kuliah",
                "source": file_path.name,
                "section": "# Daftar Mata Kuliah (Index)",
                "chunk_index": -1,
                "estimated_tokens": self._estimate_tokens(full_text),
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                # (opsional) tag
                "doc_key": "daftar_mk_index",
                "text": full_text,  # memudahkan di collector prompt
            })
            logger.info("Added DAFTAR_MK aggregate doc (%d chars) from %s", len(full_text), file_path.name)

        logger.info(f"Processed {file_path.name}: {len(docs)} chunks")
        return docs

    # ---------------- Public API ----------------

    async def ingest_knowledge_base(self, pattern: str = "*.md") -> Dict[str, Any]:
        """
        Ingest seluruh file markdown di data/knowledge_base.
        Mengembalikan ringkasan proses dan stats indeks Pinecone.
        """
        if not self.knowledge_base_path.exists():
            msg = f"Knowledge base directory not found: {self.knowledge_base_path}"
            logger.error(msg)
            return {"success": False, "error": msg, "stats": {}}

        files = sorted(self.knowledge_base_path.glob(pattern))
        if not files:
            msg = f"No markdown files found in {self.knowledge_base_path}"
            logger.warning(msg)
            return {"success": False, "error": msg, "stats": {}}

        logger.info(f"Found {len(files)} markdown files to process")

        all_docs: List[Dict[str, Any]] = []
        processed = 0
        for fp in files:
            docs = self._process_file(fp)
            if docs:
                all_docs.extend(docs)
                processed += 1

        if not all_docs:
            return {
                "success": False,
                "error": "No valid chunks generated",
                "stats": {"files_found": len(files), "files_processed": processed},
            }

        logger.info(f"Upserting {len(all_docs)} chunks to Pinecone (ns='{settings.PINECONE_NAMESPACE}')...")
        ok = await llm_service.upsert_knowledge(all_docs)

        idx_stats = await llm_service.get_index_stats()
        return {
            "success": ok,
            "stats": {
                "files_found": len(files),
                "files_processed": processed,
                "chunks_generated": len(all_docs),
                "chunks_upserted": len(all_docs) if ok else 0,
                "index_stats": idx_stats,
                "finished_at": datetime.now().isoformat(),
            },
        }

    async def test_retrieval(self, queries: List[str], top_k: int = 3) -> Dict[str, Any]:
        """
        Uji retrieval RAG untuk beberapa query.
        Mengembalikan ringkasan hasil (judul/sumber/score/preview).
        """
        out: Dict[str, Any] = {"tests": []}
        for q in queries:
            hits = await llm_service.search_knowledge_base(q, top_k=top_k)
            out["tests"].append(
                {
                    "query": q,
                    "count": len(hits),
                    "results": [
                        {
                            "title": (h.get("title") or ""),
                            "source": (h.get("source") or ""),
                            "score": float(h.get("score") or 0.0),
                            "content_preview": (h.get("content") or "")[:160] + ("..." if (h.get("content") and len(h["content"]) > 160) else ""),
                        }
                        for h in hits
                    ],
                }
            )
        return out


# Singleton
rag_ingestion_service = RAGIngestionService()
