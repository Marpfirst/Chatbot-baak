# Logika untuk integrasi dengan OpenAI (untuk jawaban) dan Pinecone (untuk RAG)
from openai import OpenAI
from pinecone import Pinecone
from typing import List, Dict, Optional, Any
import os
from app.config import settings
import logging
import asyncio

logger = logging.getLogger(__name__)

class LLMService:
    def __init__(self):
        # === OpenAI ===
        self.openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)

        # === Pinecone v5 (serverless/PC2) ===
        self.pc = Pinecone(api_key=settings.PINECONE_API_KEY)
        self.index = None
        self.pinecone_mode = None  # "v5-host" | "v5-name" | None

        index_name: Optional[str] = getattr(settings, "PINECONE_INDEX_NAME", None)
        # PENTING: host TANPA "https://"
        index_host: Optional[str] = getattr(settings, "PINECONE_INDEX_HOST", None)

        try:
            if index_host:
                host = index_host.replace("https://", "").strip()
                self.index = self.pc.Index(host=host)
                self.pinecone_mode = "v5-host"
                logger.info(f"Connected to Pinecone by HOST: {host}")
            elif index_name:
                # Coba resolve host dari controller → lalu konek by host
                try:
                    details = self.pc.describe_index(index_name)
                    host = getattr(details, "host", None)
                    if host is None and isinstance(details, dict):
                        host = details.get("host")
                    if host:
                        self.index = self.pc.Index(host=host)
                        self.pinecone_mode = "v5-host"
                        logger.info(f"Connected to Pinecone by RESOLVED HOST: {host}")
                    else:
                        # Fallback: biarkan SDK resolve by name
                        self.index = self.pc.Index(index_name)
                        self.pinecone_mode = "v5-name"
                        logger.info(f"Connected to Pinecone by NAME: {index_name}")
                except Exception as e:
                    # Fallback langsung by name
                    self.index = self.pc.Index(index_name)
                    self.pinecone_mode = "v5-name"
                    logger.warning(f"Host resolve failed, using name='{index_name}': {e}")
            else:
                logger.error("Pinecone index is not configured (no INDEX_HOST or INDEX_NAME).")
        except Exception as e:
            logger.error(f"Failed to connect to Pinecone index: {e}")
            self.index = None
    
    # ========= Embedding =========
    async def create_embedding(self, text: str) -> List[float]:
        """Create text embedding using OpenAI"""
        try:
            response = self.openai_client.embeddings.create(
                model=settings.OPENAI_EMBEDDING_MODEL,  # pastikan dim=1536 utk index kamu
                input=text.strip()
            )
            emb = response.data[0].embedding
            # (opsional) sanity check dimensi:
            # if len(emb) != 1536: logger.warning(f"Unexpected embedding dim: {len(emb)}")
            return emb
        except Exception as e:
            logger.error(f"Error creating embedding: {e}")
            return []

    # ========= RAG Search =========
    async def search_knowledge_base(
        self,
        query: str,
        top_k: int = 3,
        min_score: float = 0.50,
        prefer_doc_key: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        if not self.index:
            logger.warning("Pinecone index not available")
            return []

        try:
            query_embedding = await self.create_embedding(query)
            if not query_embedding:
                return []

            namespace = getattr(settings, "PINECONE_NAMESPACE", "") or ""
            res = self.index.query(
                vector=query_embedding,
                top_k=top_k,
                namespace=namespace,
                include_metadata=True,
            )

            matches = res.get("matches", []) if isinstance(res, dict) else getattr(res, "matches", []) or []
            results: List[Dict[str, Any]] = []

            for m in matches:
                meta = m.get("metadata") if isinstance(m, dict) else getattr(m, "metadata", None)
                score = m.get("score") if isinstance(m, dict) else getattr(m, "score", None)
                if not meta:
                    continue
                if (score is not None) and (float(score) < float(min_score)):
                    continue

                # ambil semua metadata penting; pakai 'text' jika ada agar konten tidak kependekan
                row = {
                    "content": meta.get("text") or meta.get("content", ""),
                    "title": meta.get("title", ""),
                    "source": meta.get("source", ""),
                    "section": meta.get("section", ""),
                    "doc_key": meta.get("doc_key"),  # <-- penting untuk prioritas
                    "score": float(score) if score is not None else 0.0,
                }
                results.append(row)

            # === RE-RANK (ganti blok lama kamu dengan blok ini) ===
            if prefer_doc_key:
                order = {k: i for i, k in enumerate(prefer_doc_key)}
                def _rank(d: Dict[str, Any]):
                    grp = order.get(d.get("doc_key"), 999)  # prioritas urutan sesuai prefer_doc_key
                    sc  = d.get("score") or 0.0
                    return (grp, -sc)  # dalam grup, score desc
                results.sort(key=_rank)
            else:
                # tanpa preferensi: urut score desc
                results.sort(key=lambda d: -(d.get("score") or 0.0))

            return results

        except Exception as e:
            logger.error(f"Error searching knowledge base: {e}")
            return []

    async def clear_namespace(self, namespace: Optional[str] = None) -> dict:
        """Hapus semua vektor di namespace (untuk re-ingest bersih)."""
        if not self.index:
            return {"ok": False, "error": "Index not available"}
        ns = namespace if namespace is not None else (getattr(settings, "PINECONE_NAMESPACE", "") or "")
        try:
            self.index.delete(delete_all=True, namespace=ns)
            return {"ok": True, "namespace": ns}
        except Exception as e:
            logger.error(f"Error clearing namespace '{ns}': {e}")
            return {"ok": False, "namespace": ns, "error": str(e)}
    # ========= LLM Generate =========
    async def generate_response(
        self,
        user_query: str,
        conversation_context: Optional[List[Dict]] = None,
        knowledge_context: Optional[List[Dict]] = None,
        strict: bool = False,                         # ⬅️ baru
    ) -> str:
        """Generate response using GPT-4o mini with RAG context"""
        try:
            system_prompt = self._build_system_prompt(knowledge_context, strict=strict)  # ⬅️ pass strict
            messages = [{"role": "system", "content": system_prompt}]

            # Catatan: dalam STRICT mode, kita sengaja tidak bawa terlalu banyak history
            if conversation_context and not strict:
                messages.extend(conversation_context[-6:])  # last 3 exchanges

            messages.append({"role": "user", "content": user_query})

            response = self.openai_client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=messages,
                temperature=0 if strict else 0.7,          # ⬅️ kunci: deterministic
                top_p=1.0,
                max_tokens=800,
            )
            answer = response.choices[0].message.content.strip()

            # (opsional) tambahkan footer sumber—biar konsisten, bisa biarkan routes yang nambah
            return answer

        except Exception as e:
            logger.error(f"Error generating LLM response: {e}")
            return "Maaf, saya mengalami kendala teknis. Silakan coba lagi dalam beberapa saat."


    def _build_system_prompt(
        self,
        knowledge_context: Optional[List[Dict]] = None,
        strict: bool = False
    ) -> str:
        if strict:
            base_prompt = (
                "Anda adalah asisten BAAK dalam **STRICT EXTRACTIVE MODE**.\n"
                "Aturan WAJIB di mode ini:\n"
                "1) Jawab **hanya** menggunakan kutipan isi dari `Knowledge Base Excerpts` di bawah.\n"
                "2) Jangan menambah, mengurangi, menggabungkan makna, atau mengubah redaksi penting (angka/biaya/istilah).\n"
                "3) Pertahankan urutan poin seperti pada sumber.\n"
                "4) Format jawaban markdown yang rapi (heading & bullet), tanpa sapaan/penutup dan **tanpa emoji**.\n"
                "5) Jika informasi yang diminta tidak ditemukan di excerpts, jawab singkat: "
                "\"Maaf, saya tidak menemukan informasi tersebut di basis pengetahuan.\"\n"
                "6) Jika ada beberapa potongan relevan, tampilkan semuanya berurutan. Hindari parafrase.\n"
            )
        else:
            base_prompt = (
                "Anda adalah asisten virtual BAAK.\n"
                "- Bantu pertanyaan seputar prosedur akademik.\n"
                "- Jawab ringkas, rapi, dan ramah. Hindari halusinasi; jika tidak yakin, arahkan ke BAAK.\n"
                "- Jika ada Knowledge Base, gunakan isinya untuk menolong jawaban.\n"
            )

        if knowledge_context:
            kb = knowledge_context[:5]  # ambil lebih banyak agar lengkap
            if kb:
                base_prompt += "\n### Knowledge Base Excerpts\n"
                for i, doc in enumerate(kb, 1):
                    title = (doc.get("title") or "-")
                    source = (doc.get("source") or "")
                    # ambil konten agak panjang agar tidak terpotong
                    content = (doc.get("content") or "")[:2000]
                    base_prompt += (
                        f"\n[{i}] Title: {title} (source: {source})\n"
                        "```\n" + content + "\n```\n"
                    )
        return base_prompt


    # ========= Upsert (minimal metadata) =========
    async def upsert_knowledge(self, documents: List[Dict[str, Any]]) -> bool:
        """Upsert documents to Pinecone knowledge base (lean metadata)."""
        if not self.index:
            logger.warning("Pinecone index not available for upserting")
            return False

        try:
            vectors_to_upsert = []
            namespace = getattr(settings, "PINECONE_NAMESPACE", "") or ""

            for i, doc in enumerate(documents):
                content = (doc.get("content") or "").strip()
                if not content:
                    continue

                emb = await self.create_embedding(content)
                if not emb:
                    continue

                # ❗️Sengaja TIDAK menyalin semua field doc → metadata dibuat eksplisit & ringan
                meta = {
                    "content": content,                          # <-- sumber kebenaran untuk retrieval/STRICT mode
                    "title":   doc.get("title", ""),
                    "source":  doc.get("source", ""),
                    "section": doc.get("section", ""),           # opsional tapi berguna
                }

                vectors_to_upsert.append({
                    "id": doc.get("id", f"doc_{i}"),
                    "values": emb,
                    "metadata": meta,
                })

            if not vectors_to_upsert:
                return False

            self.index.upsert(vectors=vectors_to_upsert, namespace=namespace)
            logger.info(f"Successfully upserted {len(vectors_to_upsert)} documents (ns='{namespace}')")
            return True

        except Exception as e:
            logger.error(f"Error upserting knowledge: {e}")
            return False

    # ========= Stats =========
    async def get_index_stats(self) -> Dict[str, Any]:
        """Get Pinecone index statistics"""
        if not self.index:
            return {"error": "Index not available"}
        try:
            ns = getattr(settings, "PINECONE_NAMESPACE", "") or ""
            stats = self.index.describe_index_stats()
            if isinstance(stats, dict):
                namespaces = stats.get("namespaces") or {}
                ns_count = (namespaces.get(ns) or {}).get("vector_count", 0)
                total = stats.get("total_vector_count", ns_count) or ns_count
                dim = stats.get("dimension") or stats.get("dimensions")
            else:
                namespaces = getattr(stats, "namespaces", {}) or {}
                ns_count = (namespaces.get(ns) or {}).get("vector_count", 0)
                total = getattr(stats, "total_vector_count", ns_count) or ns_count
                dim = getattr(stats, "dimension", None) or getattr(stats, "dimensions", None)

            return {
                "total_vectors": total,
                "namespace_vectors": {ns: ns_count},
                "namespaces": namespaces,
                "dimension": dim or "unknown",
                "mode": self.pinecone_mode,
            }
        except Exception as e:
            logger.error(f"Error getting index stats: {e}")
            return {"error": str(e)}

# Singleton instance
llm_service = LLMService()
