from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
from ..models.schemas import ChatRequest, ChatResponse, SessionClearRequest
from ..services.rag_ingestion import rag_ingestion_service
from ..services.database import db_service
from ..services.intent_classifier import intent_classifier, IntentType
from ..services.llm_service import llm_service
from ..services.memory_manager import memory_manager
from ..utils.helpers import formatter
import logging,re

router = APIRouter()
templates = Jinja2Templates(directory="templates")
logger = logging.getLogger(__name__)

LINK_LINE_RE = re.compile(
    r'^\s*[-*]\s*\[(?P<title>[^\]]+)\]\((?P<url>https?://[^\s)]+)\)\s*$',
    re.I | re.M
)

def _shape(session_id: str, *, answer: str, source: str, intent, has_data: bool) -> dict:
    # intent bisa Enum atau string, ubah ke string
    intent_str = intent.value if hasattr(intent, "value") else str(intent)
    return {
        "answer": answer,
        "source": source,
        "intent": intent_str,
        "session_id": session_id,
        "has_data": has_data,
    }

async def _collect_daftar_mk_from_kb() -> list[dict]:
    """
    Ambil semua bullet link 'Daftar Mata Kuliah' dari vector store.
    Tidak butuh file lokal.
    """
    # Kalau llm_service mendukung filter metadata, pakai ini:
    try:
        docs = await llm_service.search_knowledge_base(
            "daftar mata kuliah",
            top_k=100,
            min_score=0.05,
            # kalau ada dukungan filter, aktifkan salah satu:
            # metadata_filter={"doc_key": {"$in": ["daftar_mk", "daftar_mk_index"]}},
            include_text=True  # kalau API-mu ada flag ini
        )
    except TypeError:
        # fallback signature lama
        docs = await llm_service.search_knowledge_base("daftar mata kuliah", top_k=100, min_score=0.05)

    texts = []
    for d in docs or []:
        meta = d.get("metadata", {})
        title   = (d.get("title") or meta.get("title") or "")
        section = (d.get("section") or meta.get("section") or "")
        doc_key = (meta.get("doc_key") or "")
        text    = d.get("content") or d.get("text") or meta.get("text") or ""
        if not text:
            continue

        title_l, section_l, text_l = title.lower(), section.lower(), text.lower()

        if (doc_key.lower() in ("daftar_mk", "daftar_mk_index")) or \
        ("daftar mata kuliah" in title_l) or \
        ("daftar mata kuliah" in section_l) or \
        ("daftar mata kuliah" in text_l):
            texts.append(text)
    fulltext = "\n".join(texts)

    items = []
    seen = set()
    for m in LINK_LINE_RE.finditer(fulltext):
        title = m.group("title").strip()
        url   = m.group("url").strip()
        key = (title, url)
        if key in seen:
            continue
        seen.add(key)
        items.append({"title": title, "url": url})
    return items

@router.get("/", response_class=HTMLResponse)
async def get_home(request: Request):
    """Redirect ke chat page"""
    return templates.TemplateResponse("index.html", {"request": request})

@router.get("/chat", response_class=HTMLResponse)
async def get_chat_page(request: Request):
    """Endpoint untuk menampilkan halaman chat"""
    return templates.TemplateResponse("index.html", {"request": request})

@router.post("/api/chat", response_model=ChatResponse)
async def handle_chat(request: ChatRequest):
    """
    Endpoint utama untuk logika chatbot hybrid:
    1. Session management
    2. Intent classification (rule-based)
    3. Route to appropriate service (DB atau LLM+RAG)
    4. Memory management
    5. Return structured response
    """
    try:
        # 1. Session Management
        session = memory_manager.get_session(request.session_id)
        if not session:
            session_id = memory_manager.create_session()
            logger.info(f"Created new session: {session_id}")
        else:
            session_id = request.session_id
            memory_manager.update_session_activity(session_id)
        
        user_question = request.question.strip()
        
        # 2. Check for pending clarification
        pending = memory_manager.get_pending_clarification(session_id)
        if pending:
            return await _handle_clarification_response(user_question, session_id, pending)
        
        # 3. Intent Classification
        intent_type, parameters = intent_classifier.classify_intent(user_question)
        logger.info(f"[chat] q={user_question!r} intent={intent_type} params={parameters}")
        
        # 4. Route to appropriate handler
        if intent_type == IntentType.NEED_CLARIFICATION:
            response_data = await _handle_clarification_request(user_question, session_id, parameters)
        elif intent_type == IntentType.LLM_FALLBACK:
            response_data = await _handle_llm_query(user_question, session_id)
        elif intent_type in (IntentType.INFO_JADWAL_KULIAH, IntentType.CARA_BACA_JADWAL):   # NEW
            response_data = await _handle_info_intent(intent_type, user_question, session_id) # NEW
        else:
            response_data = await _handle_rule_based_query(intent_type, parameters, session_id)
        
        # 5. Update conversation memory
        memory_manager.add_exchange(
            session_id, 
            user_question, 
            response_data['answer'], 
            intent_type.value,
            parameters
        )
        
        # 6. Return response
        resp = ChatResponse(
            answer=response_data['answer'],
            source=response_data.get('source', 'system'),
            intent=intent_type.value,
            session_id=session_id,
            has_data=response_data.get('has_data', False)
        )
        logger.info(f"[chat] session={session_id} source={resp.source} has_data={resp.has_data} ans_len={len(resp.answer or '')}")
        return resp
        
    except Exception as e:
        logger.error(f"Error in chat handler: {e}")
        return ChatResponse(
            answer=formatter.format_error_message('system_error'),
            source="error",
            intent="error",
            session_id=request.session_id or memory_manager.create_session(),
            has_data=False
        )

async def _handle_rule_based_query(intent_type: IntentType, parameters: dict, session_id: str) -> dict:
    try:
        if intent_type == IntentType.JADWAL_KULIAH:
            kelas = (parameters.get('kelas') or "").upper()
            data = await db_service.get_jadwal_kuliah_by_kelas(kelas)
            if not data:
                # hitung saran berdasarkan prefix
                m = re.match(r"^([1-6][A-Za-z]{2,3})", kelas)
                if m:
                    prefix = m.group(1).upper()
                    stats = await db_service.get_kelas_prefix_stats(prefix)
                    if stats["exists"]:
                        rng = f"{prefix}{stats['min']:02d}–{prefix}{stats['max']:02d}"
                        hint = (f"❌ Kelas <b>{kelas}</b> tidak ditemukan.\n"
                                f"Untuk prefix <b>{prefix}</b>, tersedia: <b>{rng}</b>.")
                        return _shape(session_id, answer=hint, source="database",
                                    intent=IntentType.JADWAL_KULIAH, has_data=False)
            html = formatter.format_jadwal_kuliah_html(data, kelas=kelas)
            return _shape(session_id, answer=html, source="database",
                        intent=IntentType.JADWAL_KULIAH, has_data=len(data) > 0)

        elif intent_type == IntentType.JADWAL_UAS:
            kelas = (parameters.get('kelas') or "").upper()
            data = await db_service.get_jadwal_uas_by_kelas(kelas)
            if not data:
                m = re.match(r"^([1-6][A-Za-z]{2,3})", kelas)
                if m:
                    prefix = m.group(1).upper()
                    stats = await db_service.get_kelas_prefix_stats(prefix)
                    if stats["exists"]:
                        rng = f"{prefix}{stats['min']:02d}–{prefix}{stats['max']:02d}"
                        hint = (f"❌ Jadwal UAS untuk kelas <b>{kelas}</b> tidak ditemukan.<br>"
                                f"Untuk prefix <b>{prefix}</b>, tersedia: <b>{rng}</b>.")
                        return _shape(session_id, answer=hint, source="database",
                                    intent=IntentType.JADWAL_UAS, has_data=False)
            html = formatter.format_jadwal_uas_html(data, kelas)
            return _shape(session_id, answer=html, source="database",
                        intent=IntentType.JADWAL_UAS, has_data=len(data) > 0)

        elif intent_type == IntentType.JADWAL_DOSEN:
            dosen = parameters.get('dosen')
            data = await db_service.get_jadwal_kuliah_by_dosen(dosen)
            html = formatter.format_jadwal_dosen_html(data, dosen=dosen)
            return _shape(session_id,
                        answer=html,
                        source="database",
                        intent=IntentType.JADWAL_DOSEN,
                        has_data=len(data) > 0)

        elif intent_type == IntentType.WALI_KELAS:
            kelas = parameters.get('kelas')
            data = await db_service.get_wali_kelas_by_kelas(kelas)
            txt = formatter.format_wali_kelas(data, kelas)
            return _shape(session_id,
                        answer=txt,
                        source="database",
                        intent=IntentType.WALI_KELAS,
                        has_data=len(data) > 0)

        elif intent_type == IntentType.JADWAL_LOKET:
            data = await db_service.get_jadwal_loket()
            html = formatter.format_jadwal_loket_html(data)   # <-- pakai HTML
            return _shape(session_id,
                        answer=html,
                        source="database",
                        intent=IntentType.JADWAL_LOKET,
                        has_data=len(data) > 0)


        elif intent_type == IntentType.KALENDER_AKADEMIK:
            term  = parameters.get('term')
            group = parameters.get('group')
            data  = await db_service.get_kalender_akademik(term=term, group=group)
            html  = formatter.format_kalender_akademik_html(data, term=term, group=group)
            logger.info(f"[kalender] term={term} group={group} rows={len(data)}")
            return _shape(session_id,
                        answer=html,
                        source="database",
                        intent=IntentType.KALENDER_AKADEMIK,
                        has_data=len(data) > 0)

        elif intent_type == IntentType.DAFTAR_MATA_KULIAH:
            items = await _collect_daftar_mk_from_kb()
            html  = formatter.format_daftar_mata_kuliah_html(items)
            return _shape(session_id,
                        answer=html,
                        source="llm_rag",   # sumber tetap KB, tapi tanpa generasi LLM
                        intent=IntentType.DAFTAR_MATA_KULIAH,
                        has_data=len(items) > 0)
            
        # fallback salah intent
        return _shape(session_id,
                    answer=formatter.format_error_message('invalid_format'),
                    source="error",
                    intent="error",
                    has_data=False)

    except Exception as e:
        logger.error(f"Error in rule-based query: {e}")
        return _shape(session_id,
                    answer=formatter.format_error_message('system_error'),
                    source="error",
                    intent="error",
                    has_data=False)

async def _handle_clarification_request(user_question: str, session_id: str, parameters: dict) -> dict:
    # A) Ambigu jenis jadwal (sudah ada)
    if parameters.get("ask") == "jenis_jadwal" and parameters.get("kelas"):
        kelas = parameters["kelas"].upper()
        memory_manager.set_pending_clarification(session_id, "jadwal_ambiguous", {"kelas": kelas})
        return {
            "answer": (
                f"Untuk kelas <b>{kelas}</b>, mau lihat <b>jadwal kuliah</b> atau <b>jadwal UAS</b>?<br>"
                f"Contoh cepat: <code>jadwal kuliah {kelas}</code> atau <code>jadwal uas {kelas}</code>"
            ),
            "source": "clarification",
            "intent": "need_clarification",
            "session_id": session_id,
            "has_data": False
        }
    # B) Prefix-only atau format salah → tampilkan rentang yang tersedia berdasar DB
    if parameters.get("ask") == "kelas_range" and parameters.get("prefix"):
        prefix = parameters["prefix"].upper()
        stats = await db_service.get_kelas_prefix_stats(prefix)
        memory_manager.set_pending_clarification(session_id, "kelas_range", {"prefix": prefix})
        if not stats["exists"]:
            msg = (
                f"Tidak menemukan kelas dengan prefix <b>{prefix}</b> di database saat ini. "
                f"Silakan periksa kembali."
            )
        else:
            rng = (f"{prefix}{stats['min']:02d}–{prefix}{stats['max']:02d}"
                if stats["min"] is not None else f"{prefix}..??")
            msg = (
                f"Untuk prefix <b>{prefix}</b>, kelas yang tersedia saat ini berkisar <b>{rng}</b> "
                f"(total {stats['count']} kelas).<br>"
                f"Tulis lengkap salah satu, contoh: "
                f"<code>jadwal kuliah {prefix}{stats['min']:02d}</code> atau "
                f"<code>jadwal uas {prefix}{stats['max']:02d}</code>."
            )
        return {
            "answer": msg,
            "source": "clarification",
            "intent": "need_clarification",
            "session_id": session_id,
            "has_data": False
        }
    # C) Cabang generik (jangan dihapus): untuk intent lain yg butuh param
    missing_param = parameters.get("missing")
    intended_intent = parameters.get("intent")
    if missing_param and intended_intent:
        memory_manager.set_pending_clarification(session_id, str(intended_intent), parameters)
        answer = formatter.format_clarification_request(missing_param, str(intended_intent))
        return {
            "answer": answer,
            "source": "clarification",
            "intent": "need_clarification",
            "session_id": session_id,
            "has_data": False
        }

    # default
    return {
        "answer": formatter.format_error_message("invalid_format"),
        "source": "error",
        "intent": "error",
        "session_id": session_id,
        "has_data": False
    }
    
async def _handle_clarification_response(user_question: str, session_id: str, pending: tuple) -> ChatResponse:
    # --- EARLY OVERRIDE: jika user kirim query baru yang valid, gantikan alur pending lama ---
    new_intent, new_params = intent_classifier.classify_intent(user_question or "")
    # --- EARLY OVERRIDE untuk query edukatif saat sedang pending  ---
    if new_intent in (IntentType.INFO_JADWAL_KULIAH, IntentType.CARA_BACA_JADWAL):
        memory_manager.clear_pending_clarification(session_id)
        resp = await _handle_info_intent(new_intent, user_question, session_id)
        return ChatResponse(
            answer=resp["answer"], source=resp["source"],
            intent=(new_intent.value if hasattr(new_intent, "value") else str(new_intent)),
            session_id=session_id, has_data=resp["has_data"]
        )
    # 1) Sudah intent final (langsung eksekusi)
    if new_intent in (IntentType.JADWAL_KULIAH, IntentType.JADWAL_UAS):
        memory_manager.clear_pending_clarification(session_id)
        resp = await _handle_rule_based_query(new_intent, new_params, session_id)
        return ChatResponse(answer=resp["answer"], source=resp["source"],
                            intent=new_intent.value, session_id=session_id,
                            has_data=resp["has_data"])

    # 2) Prefix-only / bare-class (tetap di alur klarifikasi yg tepat)
    if new_intent == IntentType.NEED_CLARIFICATION and new_params.get("ask") == "kelas_range":
        memory_manager.clear_pending_clarification(session_id)
        resp = await _handle_clarification_request(user_question, session_id, new_params)
        return ChatResponse(answer=resp["answer"], source=resp["source"],
                            intent="need_clarification", session_id=session_id, has_data=False)
    if new_intent == IntentType.NEED_CLARIFICATION and new_params.get("ask") == "jenis_jadwal" and new_params.get("kelas"):
        memory_manager.clear_pending_clarification(session_id)
        resp = await _handle_clarification_request(user_question, session_id, {"ask":"jenis_jadwal","kelas":new_params["kelas"]})
        return ChatResponse(answer=resp["answer"], source=resp["source"],
                            intent="need_clarification", session_id=session_id, has_data=False)

    # 3) Intent RULE-BASED lain → keluar dari pending & rute sesuai intent
    if new_intent in (IntentType.KALENDER_AKADEMIK, IntentType.JADWAL_LOKET, IntentType.WALI_KELAS, IntentType.JADWAL_DOSEN):
        memory_manager.clear_pending_clarification(session_id)
        # jika butuh param dan belum ada → minta klarifikasi param tsb
        need = None
        if new_intent == IntentType.WALI_KELAS and not new_params.get("kelas"): need = "kelas"
        if new_intent == IntentType.JADWAL_DOSEN and not new_params.get("dosen"): need = "dosen"
        if need:
            ans = formatter.format_clarification_request(need, new_intent.value)
            return ChatResponse(answer=ans, source="clarification", intent="need_clarification",
                                session_id=session_id, has_data=False)
        resp = await _handle_rule_based_query(new_intent, new_params, session_id)
        return ChatResponse(answer=resp["answer"], source=resp["source"],
                            intent=new_intent.value, session_id=session_id,
                            has_data=resp["has_data"])

    # 4) LLM fallback / daftar-mk / prosedur → keluar dari pending & ke LLM
    if new_intent in (IntentType.DAFTAR_MATA_KULIAH, IntentType.LLM_FALLBACK):
        memory_manager.clear_pending_clarification(session_id)
        resp = await _handle_llm_query(user_question, session_id)
        return ChatResponse(answer=resp["answer"], source=resp["source"],
                           intent="llm_fallback", session_id=session_id,
                           has_data=resp["has_data"])

    # ---------- Lanjut alur pending lama ----------
    pending_intent, payload = pending[0], (pending[1] or {})
    low = (user_question or "").lower()

    # 1) Pending: kelas_range
    if pending_intent == "kelas_range":
        # Jika user sudah menentukan “jadwal uas 4KB03” / “jadwal kuliah 4KA02”
        det = intent_classifier.extract_kelas_detail(user_question or "")
        if det:
            itype = IntentType.JADWAL_UAS if "uas" in low else IntentType.JADWAL_KULIAH
            kelas = det["base"] if itype == IntentType.JADWAL_UAS else det["full"]
            memory_manager.clear_pending_clarification(session_id)
            resp = await _handle_rule_based_query(itype, {"kelas": kelas}, session_id)
            return ChatResponse(
                answer=resp["answer"], source=resp["source"], intent=itype.value,
                session_id=session_id, has_data=resp["has_data"]
            )

        # Belum lengkap → ulangi dengan prefix sebelumnya
        prefix = (payload.get("prefix") or "").upper()
        stats  = await db_service.get_kelas_prefix_stats(prefix) if prefix else None
        msg = f"Tulis lengkap kelas {prefix} + 2 digit. "
        if stats and stats["exists"]:
            msg += (f"Contoh: <code>jadwal kuliah {prefix}{stats['min']:02d}</code> "
                    f"atau <code>jadwal uas {prefix}{stats['max']:02d}</code>.")
        else:
            msg += f"Misal: <code>jadwal kuliah {prefix}01</code>."
        return ChatResponse(
            answer=msg, source="clarification", intent="need_clarification",
            session_id=session_id, has_data=False
        )

    # 2) Izinkan user mengganti pilihan (kuliah ⇄ UAS) meski pending intent beda
    if ("uas" in low) or ("kuliah" in low):
        target_intent = IntentType.JADWAL_UAS if "uas" in low else IntentType.JADWAL_KULIAH
        det = intent_classifier.extract_kelas_detail(user_question or "")
        if det:
            kelas = det["base"] if target_intent == IntentType.JADWAL_UAS else det["full"]
            memory_manager.clear_pending_clarification(session_id)
            resp = await _handle_rule_based_query(target_intent, {"kelas": kelas}, session_id)
            return ChatResponse(
                answer=resp["answer"], source=resp["source"], intent=target_intent.value,
                session_id=session_id, has_data=resp["has_data"]
            )

        # Tidak ada kelas → minta kelas untuk intent baru (UAS/Kuliah)
        memory_manager.set_pending_clarification(session_id, target_intent.value, {})
        msg = formatter.format_clarification_request("kelas", target_intent.value)
        return ChatResponse(
            answer=msg, source="clarification", intent="need_clarification",
            session_id=session_id, has_data=False
        )

    # 3) Pending: jadwal_ambiguous (punya {kelas} sebelumnya)
    if pending_intent == "jadwal_ambiguous":
        kelas = (payload.get("kelas") or "").upper()

        if "uas" in low:
            memory_manager.clear_pending_clarification(session_id)
            resp = await _handle_rule_based_query(IntentType.JADWAL_UAS, {"kelas": kelas}, session_id)
            return ChatResponse(
                answer=resp["answer"], source=resp["source"], intent=IntentType.JADWAL_UAS.value,
                session_id=session_id, has_data=resp["has_data"]
            )
        if "kuliah" in low:
            memory_manager.clear_pending_clarification(session_id)
            resp = await _handle_rule_based_query(IntentType.JADWAL_KULIAH, {"kelas": kelas}, session_id)
            return ChatResponse(
                answer=resp["answer"], source=resp["source"], intent=IntentType.JADWAL_KULIAH.value,
                session_id=session_id, has_data=resp["has_data"]
            )

        det = intent_classifier.extract_kelas_detail(user_question or "")
        if "uas" in low and det:
            memory_manager.clear_pending_clarification(session_id)
            resp = await _handle_rule_based_query(IntentType.JADWAL_UAS, {"kelas": det["base"]}, session_id)
            return ChatResponse(
                answer=resp["answer"], source=resp["source"], intent=IntentType.JADWAL_UAS.value,
                session_id=session_id, has_data=resp["has_data"]
            )
        if "kuliah" in low and det:
            memory_manager.clear_pending_clarification(session_id)
            resp = await _handle_rule_based_query(IntentType.JADWAL_KULIAH, {"kelas": det["full"]}, session_id)
            return ChatResponse(
                answer=resp["answer"], source=resp["source"], intent=IntentType.JADWAL_KULIAH.value,
                session_id=session_id, has_data=resp["has_data"]
            )

        # Masih ambigu
        msg = (f"Masih ambigu. Ketik saja: <code>jadwal kuliah {kelas}</code> "
               f"atau <code>jadwal uas {kelas}</code> 🙂")
        return ChatResponse(
            answer=msg, source="clarification", intent="need_clarification",
            session_id=session_id, has_data=False
        )

    # 4) Fallback: klasifikasi lagi dan rute sesuai pending intent lama
    intent_type, new_parameters = intent_classifier.classify_intent(user_question)
    memory_manager.clear_pending_clarification(session_id)

    if pending_intent == 'jadwal_kuliah' and new_parameters.get('kelas'):
        resp = await _handle_rule_based_query(IntentType.JADWAL_KULIAH, new_parameters, session_id)
        final_intent = IntentType.JADWAL_KULIAH.value
    elif pending_intent == 'jadwal_uas' and new_parameters.get('kelas'):
        resp = await _handle_rule_based_query(IntentType.JADWAL_UAS, new_parameters, session_id)
        final_intent = IntentType.JADWAL_UAS.value
    elif pending_intent == 'wali_kelas' and new_parameters.get('kelas'):
        resp = await _handle_rule_based_query(IntentType.WALI_KELAS, new_parameters, session_id)
        final_intent = IntentType.WALI_KELAS.value
    elif pending_intent == 'jadwal_dosen' and new_parameters.get('dosen'):
        resp = await _handle_rule_based_query(IntentType.JADWAL_DOSEN, new_parameters, session_id)
        final_intent = IntentType.JADWAL_DOSEN.value
    elif pending_intent == 'kalender_akademik':
        term = new_parameters.get('term')
        params = {'term': term} if term else {}
        resp = await _handle_rule_based_query(IntentType.KALENDER_AKADEMIK, params, session_id)
        final_intent = IntentType.KALENDER_AKADEMIK.value
    else:
        resp = {
            "answer": formatter.format_error_message("invalid_format", f"Format tidak sesuai untuk {pending_intent}"),
            "source": "error",
            "has_data": False
        }
        final_intent = "error"

    memory_manager.add_exchange(session_id, user_question, resp["answer"], pending_intent, new_parameters)

    return ChatResponse(
        answer=resp["answer"],
        source=resp["source"],
        intent=final_intent,
        session_id=session_id,
        has_data=resp["has_data"]
    )

async def _handle_llm_query(user_question: str, session_id: str) -> dict:
    low = (user_question or "").lower().strip()

    # 0) KHUSUS: "daftar mata kuliah" → guard + strict extractive
    if any(k in low for k in ("daftar mata kuliah", "list mata kuliah", "daftar mk")):
        try:
            # kalau llm_service.search_knowledge_base sudah kamu tambah argumen prefer_doc_key, pakai;
            # kalau belum, hapus argumen itu saja.
            kb = await llm_service.search_knowledge_base(
                "daftar mata kuliah",
                top_k=30,
                min_score=0.30,
                prefer_doc_key=["daftar_mk_index", "daftar_mk"]
            )
            if not kb:
                return {
                    "answer": "Maaf, data 'Daftar Mata Kuliah' belum tersedia di basis pengetahuan.",
                    "source": "llm_rag",
                    "has_data": False
                }

            answer = await llm_service.generate_response(
                user_query="Tampilkan *seluruh* daftar mata kuliah sebagai daftar link markdown tanpa memotong.",
                conversation_context=None,
                knowledge_context=kb,
                strict=True,   # wajib agar tidak terpotong/di-parafrase
            )
            sources_note = formatter.format_sources(kb)
            if sources_note:
                answer = f"{answer}\n\n{sources_note}"
            return {"answer": answer, "source": "llm_rag", "has_data": True}

        except Exception as e:
            logger.error(f"Error daftar mata kuliah flow: {e}")
            return {
                "answer": "Maaf, terjadi kendala saat memuat daftar mata kuliah.",
                "source": "llm_error",
                "has_data": False
            }

    # 1) FAILSAFE: user menyebut kode kelas lengkap → minta pilih kuliah/UAS
    det = intent_classifier.extract_kelas_detail(user_question or "")
    if det:
        kelas = det["full"]  # kuliah boleh bawa suffix
        memory_manager.set_pending_clarification(session_id, "jadwal_ambiguous", {"kelas": kelas})
        return {
            "answer": (
                f"Untuk kelas <b>{kelas}</b>, mau lihat <b>jadwal kuliah</b> atau <b>jadwal UAS</b>?<br>"
                f"Contoh cepat: <code>jadwal kuliah {kelas}</code> atau <code>jadwal uas {kelas}</code>"
            ),
            "source": "clarification",
            "intent": "need_clarification",
            "session_id": session_id,
            "has_data": False
        }

    # 2) FAILSAFE: prefix saja (mis. 4KA / 4KB) → tampilkan rentang yang tersedia
    m_pref = intent_classifier.RE_CLASS_PREFIX_ONLY.fullmatch(user_question or "")
    if m_pref:
        prefix = (m_pref.group("lvl") + m_pref.group("prodi")).upper()
        memory_manager.set_pending_clarification(session_id, "kelas_range", {"prefix": prefix})
        stats = await db_service.get_kelas_prefix_stats(prefix)
        if not stats["exists"]:
            msg = f"Tidak menemukan kelas dengan prefix <b>{prefix}</b> di database saat ini."
        else:
            rng = (f"{prefix}{stats['min']:02d}–{prefix}{stats['max']:02d}"
                if stats["min"] is not None else f"{prefix}..??")
            msg = (f"Untuk prefix <b>{prefix}</b>, kelas yang tersedia berkisar <b>{rng}</b> "
                f"(total {stats['count']} kelas).<br>"
                f"Tulis lengkap salah satu, contoh: "
                f"<code>jadwal kuliah {prefix}{stats['min']:02d}</code> atau "
                f"<code>jadwal uas {prefix}{stats['max']:02d}</code>.")
        return {
            "answer": msg,
            "source": "clarification",
            "intent": "need_clarification",
            "session_id": session_id,
            "has_data": False
        }

    # 3) RAG umum
    try:
        knowledge_docs = await llm_service.search_knowledge_base(user_question, top_k=5, min_score=0.45)
        answer = await llm_service.generate_response(
            user_query=user_question,
            conversation_context=None,
            knowledge_context=knowledge_docs,
            strict=(len(knowledge_docs) > 0),
        )
        sources_note = formatter.format_sources(knowledge_docs)
        if sources_note:
            answer = f"{answer}\n\n{sources_note}"
        return {'answer': answer, 'source': 'llm_rag', 'has_data': len(knowledge_docs) > 0}
    except Exception as e:
        logger.error(f"Error in LLM query: {e}")
        return {
            'answer': "🤖 Maaf, saya sedang mengalami kendala teknis. Untuk informasi prosedur akademik, silakan hubungi BAAK langsung.",
            'source': 'llm_error',
            'has_data': False
        }

async def _handle_info_intent(intent_type: IntentType, user_question: str, session_id: str) -> dict:
    """
    Jawaban edukatif/penjelasan dari KB (STRICT), tidak meminta kelas.
    - INFO_JADWAL_KULIAH → definisi + (opsional) waktu kuliah
    - CARA_BACA_JADWAL   → cara membaca + (opsional) waktu kuliah
    """
    try:
        if intent_type == IntentType.CARA_BACA_JADWAL:
            prefer = ["cara_baca_jadwal", "waktu_kuliah"]
            title  = "Cara Membaca Jadwal Kuliah"
        else:
            prefer = ["definisi_jadwal", "waktu_kuliah"]
            title  = "Informasi Jadwal Kuliah"

        kb = await llm_service.search_knowledge_base(
            user_question or title,
            top_k=20,
            min_score=0.30,
            prefer_doc_key=prefer
        )

        answer = await llm_service.generate_response(
            user_query=user_question or title,
            conversation_context=None,
            knowledge_context=kb,
            strict=True,  # pastikan mengutip dari KB saja
        )

        sources_note = formatter.format_sources(kb)
        if sources_note:
            answer = f"{answer}\n\n{sources_note}"

        return _shape(session_id,
                        answer=answer,
                        source="llm_rag",
                        intent=intent_type,
                        has_data=len(kb) > 0)
    except Exception as e:
        logger.error(f"Error handle info intent: {e}")
        return _shape(session_id,
                        answer="Maaf, terjadi kendala saat memuat informasi.",
                        source="llm_error",
                        intent=intent_type,
                        has_data=False)
        
@router.post("/api/session/clear")
async def clear_session(request: SessionClearRequest):
    """Clear session data"""
    try:
        success = memory_manager.cleanup_session(request.session_id)
        return {
            "success": success,
            "message": "Session cleared successfully" if success else "Session not found"
        }
    except Exception as e:
        logger.error(f"Error clearing session: {e}")
        raise HTTPException(status_code=500, detail="Failed to clear session")

@router.get("/api/health")
async def health_check():
    """Health check endpoint"""
    try:
        try:
            memory_stats = memory_manager.get_session_stats()
        except Exception:
            memory_stats = {"timestamp": None, "active_sessions": 0}

        try:
            pinecone_stats = await llm_service.get_index_stats()
            pine_ok = not bool(pinecone_stats.get("error"))
        except Exception:
            pinecone_stats = {"error": "unavailable", "total_vectors": None}
            pine_ok = False

        try:
            db_ok = await db_service.ping()
        except Exception:
            db_ok = False

        try:
            kb_probe = await llm_service.search_knowledge_base("daftar mata kuliah", top_k=1, min_score=0.2)
            kb_status = "seeded" if kb_probe else "empty"
        except Exception:
            kb_status = "error"

        status = "healthy" if (db_ok and pine_ok) else "degraded"
        return {
            "status": status,
            "timestamp": memory_stats.get("timestamp"),
            "active_sessions": memory_stats.get("active_sessions", 0),
            "db_status": "ok" if db_ok else "error",
            "pinecone_status": "connected" if pine_ok else "error",
            "pinecone_vectors": pinecone_stats.get("total_vectors"),
            "knowledge_status": kb_status,
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"status": "unhealthy", "error": str(e)}
