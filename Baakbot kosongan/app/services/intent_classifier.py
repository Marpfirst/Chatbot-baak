# app/services/intent_classifier.py
import re
from typing import Dict, Optional, Tuple
from enum import Enum

class IntentType(str, Enum):
    DAFTAR_MATA_KULIAH = "daftar_mata_kuliah"
    INFO_JADWAL_KULIAH = "info_jadwal_kuliah"     # NEW
    CARA_BACA_JADWAL   = "cara_baca_jadwal"       # NEW
    KALENDER_AKADEMIK  = "kalender_akademik"
    JADWAL_KULIAH      = "jadwal_kuliah"
    JADWAL_UAS         = "jadwal_uas"
    JADWAL_DOSEN       = "jadwal_dosen"
    WALI_KELAS         = "wali_kelas"
    JADWAL_LOKET       = "jadwal_loket"
    LLM_FALLBACK       = "llm_fallback"
    NEED_CLARIFICATION = "need_clarification"

class IntentClassifier:
    # ===== Regex (disimpan sebagai atribut class) =====
    RE_CLASS_FULL         = re.compile(r"\b(?P<lvl>[1-4])(?P<prodi>[A-Za-z]{2})(?P<num>\d{2})(?P<suffix>[A-Ea-e])?\b", re.I)
    RE_CLASS_PREFIX_ONLY  = re.compile(r"^\s*(?P<lvl>[1-4])(?P<prodi>[A-Za-z]{2})\s*$", re.I)
    RE_CLASS_BARE         = re.compile(r"^\s*[1-4][A-Za-z]{2}\d{2}([A-Ea-e])?\s*$", re.I)

    def __init__(self):
        # Pola kata kunci utama
        self.patterns = {
            IntentType.DAFTAR_MATA_KULIAH: [
                r'\b(daftar|list)\s+(mata\s+kuliah|matkul)\b',
                r'\b(mata\s+kuliah|matkul)\b.*\b(daftar|list)\b',
            ],
            # INFO definisi jadwal kuliah (tanpa kelas)
            IntentType.INFO_JADWAL_KULIAH: [
                r'\b(jadwal\s+kuliah)\s*(adalah|apa\s+itu|pengertian|definisi)\b',
                r'\b(kapan|bagaimana)\s+(jadwal\s+kuliah)\b',
            ],
            # Cara membaca jadwal (tanpa kelas)
            IntentType.CARA_BACA_JADWAL: [
                r'\b(cara|bagaimana)\s+(membaca|baca)\s+(jadwal\s+kuliah)\b',
                r'\b(jadwal\s+kuliah)\b.*\b(cara\s+membaca|cara\s+baca)\b',
            ],
            IntentType.KALENDER_AKADEMIK: [
                r'\bkalender\s+akademik\b',
                r'(?=.*\b(kapan|tanggal|periode|rentang)\b)(?=.*\b(uts|uas|libur|daftar ulang|cuti|krs|frs|uji kompetensi|perkuliahan)\b)(?!.*\bkelas\b)',
            ],
            IntentType.JADWAL_KULIAH: [
                r'\bjadwal\s+(kuliah|perkuliahan)\b',
                r'\b(kuliah|perkuliahan)\b.*\bkelas\b',
                r'\bkelas\b.*\bjadwal\b',
            ],
            IntentType.JADWAL_UAS: [
                r'\bjadwal\s+(uas|ujian)\b',
                r'\b(uas|ujian)\b.*\bkelas\b',
                r'\bujian\s+akhir\b',
            ],
            IntentType.JADWAL_DOSEN: [
                r'\bjadwal\s+dosen\b',
                r'\bdosen\b.*\bjadwal\b',
                r'\bmengajar\b.*\bdosen\b',
            ],
            IntentType.WALI_KELAS: [
                r'\bwali\s+kelas\b',
                r'\bdosen\s+wali\b',
                r'\bpembimbing\s+kelas\b',
            ],
            IntentType.JADWAL_LOKET: [
                r'\bloket\s+baak\b',
                r'\blayanan\s+baak\b',
                r'\bjam\s+buka\s+baak\b',
                r'\boperasional\s+baak\b',
            ],
        }

        # ✅ whitelist kode prodi
        self.allowed_prodi = {
            "KA","KB","EA","EB","EC",
            "IA","IB","IC","ID","IE",
            "TA","TB","TC",
            "PA",
            "SA","SC","SB",
            "HB","HC","HA",
            "DA","DB","DC","DD","DF",
        }

        self.dosen_trigger = re.compile(r'\b(jadwal\s+dosen|dosen|pak|bu|bapak|ibu)\b', re.I)
        self.knowledge_keywords = {
            "prosedur","cara","syarat","cuti","bimbingan","skripsi",
            "krs","khs","registrasi","wisuda","magang","pindah","alih","tugas akhir"
        }

    # ---------- Ekstraksi ----------
    def extract_kelas_detail(self, text: str):
        """Return dict: {base:'3KA02', full:'3KA02A', suffix:'A'|None} atau None."""
        if not text:
            return None
        m = self.RE_CLASS_FULL.search(text)
        if not m:
            return None
        lvl    = m.group("lvl")
        prodi  = m.group("prodi").upper()
        if prodi not in self.allowed_prodi:
            return None
        num    = m.group("num")
        suffix = (m.group("suffix") or "").upper() or None
        base   = f"{lvl}{prodi}{num}"
        full   = base + (suffix or "")
        return {"base": base, "full": full, "suffix": suffix}

    def extract_dosen_name(self, text: str) -> Optional[str]:
        if not text:
            return None
        m = self.dosen_trigger.search(text)
        if not m:
            return None
        after = text[m.end():].strip()
        m2 = re.match(r"([A-Za-zÀ-ÿ.'\- ]{2,})", after)
        if not m2:
            return None
        name = re.sub(r"\s+", " ", m2.group(1).strip())
        return name if len(name) >= 2 else None

    def extract_calendar_group(self, text: str) -> Optional[str]:
        q = (text or "").lower()
        if "perkuliahan" in q and "uts" in q:
            if re.search(r"\b(sebelum|pra)\b", q): return "sebelum_uts"
            if re.search(r"\b(setelah|sesudah|pasca)\b", q): return "setelah_uts"
        return None

    def extract_calendar_term(self, text: str) -> Optional[str]:
        q = (text or "").lower()
        if "uts" in q: return "uts"
        if "uas" in q: return "uas"
        if "cuti" in q: return "cuti"
        if "krs" in q or "frs" in q: return "krs"
        if "daftar ulang" in q: return "daftar_ulang"
        if "libur" in q: return "libur"
        if "uji kompetensi" in q: return "uji_kompetensi"
        return None

    # ---------- Klasifikasi ----------
    def classify_intent(self, text: str) -> Tuple[IntentType, Dict]:
        q  = (text or "").strip()
        ql = q.lower()
        params: Dict = {}

        # A) Prefix-only: "4KB" → minta rentang
        m_pref = self.RE_CLASS_PREFIX_ONLY.fullmatch(q)
        if m_pref:
            return IntentType.NEED_CLARIFICATION, {
                "ask": "kelas_range",
                "prefix": (m_pref.group("lvl") + m_pref.group("prodi")).upper()
            }

        # B) Loket (deterministik)
        for pat in self.patterns[IntentType.JADWAL_LOKET]:
            if re.search(pat, ql, flags=re.I):
                return IntentType.JADWAL_LOKET, params

        # C) Bare class: “3KA11”/“3KA11A” → tanya jenis jadwal
        if self.RE_CLASS_BARE.fullmatch(q):
            det = self.extract_kelas_detail(q)
            return IntentType.NEED_CLARIFICATION, {
                "ask": "jenis_jadwal",
                "kelas": (det["full"] if det else q.upper())
            }

        # D) Info edukatif (tanpa kelas) — definisi & cara baca
        if not self.RE_CLASS_FULL.search(q):
            for pat in self.patterns[IntentType.CARA_BACA_JADWAL]:
                if re.search(pat, ql, flags=re.I):
                    return IntentType.CARA_BACA_JADWAL, {}
            for pat in self.patterns[IntentType.INFO_JADWAL_KULIAH]:
                if re.search(pat, ql, flags=re.I):
                    return IntentType.INFO_JADWAL_KULIAH, {}

        # E) Jadwal Kuliah
        for pat in self.patterns[IntentType.JADWAL_KULIAH]:
            if re.search(pat, ql, flags=re.I):
                det = self.extract_kelas_detail(q)
                if det:
                    return IntentType.JADWAL_KULIAH, {"kelas": det["full"]}
                return IntentType.NEED_CLARIFICATION, {"missing": "kelas", "intent": IntentType.JADWAL_KULIAH.value}

        # F) Jadwal UAS
        for pat in self.patterns[IntentType.JADWAL_UAS]:
            if re.search(pat, ql, flags=re.I):
                det = self.extract_kelas_detail(q)
                if det:
                    return IntentType.JADWAL_UAS, {"kelas": det["base"]}
                return IntentType.NEED_CLARIFICATION, {"missing": "kelas", "intent": IntentType.JADWAL_UAS.value}

        # G) Wali Kelas
        for pat in self.patterns[IntentType.WALI_KELAS]:
            if re.search(pat, ql, flags=re.I):
                det = self.extract_kelas_detail(q)
                if det:
                    return IntentType.WALI_KELAS, {"kelas": det["base"]}
                return IntentType.NEED_CLARIFICATION, {"missing": "kelas", "intent": IntentType.WALI_KELAS.value}

        # H) Jadwal Dosen
        for pat in self.patterns[IntentType.JADWAL_DOSEN]:
            if re.search(pat, ql, flags=re.I):
                dosen = self.extract_dosen_name(q)
                if dosen:
                    return IntentType.JADWAL_DOSEN, {"dosen": dosen}
                return IntentType.NEED_CLARIFICATION, {"missing": "dosen", "intent": IntentType.JADWAL_DOSEN.value}

        # I) Kalender Akademik (hindari jika ada kelas)
        grp = self.extract_calendar_group(ql)
        if grp:
            return IntentType.KALENDER_AKADEMIK, {"group": grp}
        for pat in self.patterns.get(IntentType.KALENDER_AKADEMIK, []):
            if re.search(pat, ql, flags=re.I):
                if self.RE_CLASS_FULL.search(q):
                    break
                term = self.extract_calendar_term(q)
                p = {}
                if term: p["term"] = term
                return IntentType.KALENDER_AKADEMIK, p

        # J) Prosedural → LLM
        if any(k in ql for k in self.knowledge_keywords):
            return IntentType.LLM_FALLBACK, {}

        # K) Default
        return IntentType.LLM_FALLBACK, {}

# Singleton
intent_classifier = IntentClassifier()
