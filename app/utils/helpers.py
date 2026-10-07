# Fungsi-fungsi bantuan yang bisa digunakan di seluruh aplikasi
from typing import List, Dict, Any
from datetime import datetime
import re

class ResponseFormatter:
    # ==== Tambahan: peta bulan & parser ====
    _ID_MONTHS = {
        1:"Januari", 2:"Februari", 3:"Maret", 4:"April", 5:"Mei", 6:"Juni",
        7:"Juli", 8:"Agustus", 9:"September", 10:"Oktober", 11:"November", 12:"Desember"
    }
    
    @staticmethod
    def _clean_field(val: Any, dash_if_empty: bool = True) -> str:
        """
        Bersihkan field teks:
        - ubah None/'' jadi '-' (opsional)
        - hilangkan '\n' literal, trimming spasi, kompres spasi
        """
        s = "" if val is None else str(val)
        s = s.replace("\\n", " ").strip()
        s = re.sub(r"\s+", " ", s)
        if not s and dash_if_empty:
            s = "-"
        return s

    @staticmethod
    def _clean_title(val: Any) -> str:
        """
        Bersihkan judul mata kuliah TANPA mengubah tanda '*' di akhir,
        karena '*' bagian dari penamaan internal (mis. 'Algoritma & Pemrograman 2A *').
        Hanya hilangkan bullet/markdown di depan kalau ada.
        """
        s = ResponseFormatter._clean_field(val)
        # buang bullet/markdown diawal (•, -, * di depan)
        s = re.sub(r"^[\-\*\u2022•]+\s*", "", s)
        return s
    
    @staticmethod
    def normalize_day(name: str) -> str:
        """Samakan ejaan hari agar konsisten untuk pengelompokan & urutan."""
        if not name:
            return ""
        aliases = {
            "jum'at": "Jumat",
            "jumat": "Jumat",
            "senin": "Senin",
            "selasa": "Selasa",
            "rabu": "Rabu",
            "kamis": "Kamis",
            "sabtu": "Sabtu",
            "minggu": "Minggu",
        }
        key = name.strip().lower()
        return aliases.get(key, name.strip())

    @staticmethod
    def format_sources(docs: List[Dict[str, Any]]) -> str:
        """Buat blok 'Sumber:' dari hasil RAG."""
        if not docs:
            return ""
        lines = ["\n**Sumber:**"]
        for d in docs:
            title = (d.get("title") or "Dokumen").strip()
            section = (d.get("section") or "").strip()
            src = (d.get("source") or "").strip()
            label = title if not section else f"{title} — {section}"
            # ⬇️ perbaikan: rangkai string pakai 1 f-string
            lines.append(f"- {label}{f' ({src})' if src else ''}")
        return "\n".join(lines)

    @staticmethod
    def format_jadwal_kuliah(
        data: List[Dict[str, Any]],
        kelas: str = None,
        dosen: str = None
    ) -> str:
        """Format jadwal kuliah response."""
        if not data:
            if kelas:
                return (
                    f"❌ Jadwal kuliah untuk kelas **{kelas.upper()}** tidak ditemukan. "
                    f"Pastikan format kelas benar (contoh: 1KA01)."
                )
            elif dosen:
                return (
                    f"❌ Jadwal untuk dosen **{dosen}** tidak ditemukan. "
                    f"Coba nama lengkap atau bagian nama dosen."
                )
            else:
                return "❌ Data jadwal kuliah tidak ditemukan."

        if kelas:
            response = f"Jadwal Kuliah Kelas {data[0].get('kelas', kelas.upper())}\n\n"
        else:
            response = f"Jadwal Kuliah Dosen {dosen}\n\n"

        # Group by day (normalized)
        days_order = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
        grouped_by_day: Dict[str, List[Dict[str, Any]]] = {}

        for item in data:
            hari_raw = item.get("hari", "")
            hari = ResponseFormatter.normalize_day(hari_raw)
            grouped_by_day.setdefault(hari, []).append(item)

        # Cetak sesuai urutan standar lebih dulu
        for day in days_order:
            if day in grouped_by_day:
                response += f"{day}:\n"
                # ⬇️ urutkan per slot/jam
                day_items = sorted(
                    grouped_by_day[day],
                    key=lambda it: ResponseFormatter._slot_rank(
                        ResponseFormatter._normalize_waktu(it.get("waktu"))
                    )
                )
                for item in day_items:
                    mata_kuliah = ResponseFormatter._clean_title(item.get("mata_kuliah"))
                    waktu = ResponseFormatter._normalize_waktu(item.get("waktu"))
                    ruang = ResponseFormatter._clean_field(item.get("ruang"))
                    dosen_name = ResponseFormatter._clean_field(item.get("dosen"))
                    kelas_info = "" if kelas else f" ({item.get('kelas', '-')})"

                    response += f" {mata_kuliah}{kelas_info}\n"
                    response += f"   {waktu}\n" if waktu != "-" else ""
                    response += f"   {ruang}\n" if ruang != "-" else ""
                    response += f"   {dosen_name}\n\n" if dosen_name != "-" else "\n"

        # hari di luar daftar standar
        unknown_days = [d for d in grouped_by_day.keys() if d not in days_order]
        for day in sorted(unknown_days):
            response += f"{day or 'Hari tidak diketahui'}:\n"
            day_items = sorted(
                grouped_by_day[day],
                key=lambda it: ResponseFormatter._slot_rank(
                    ResponseFormatter._normalize_waktu(it.get("waktu"))
                )
            )
            for item in day_items:
                mata_kuliah = ResponseFormatter._clean_title(item.get("mata_kuliah"))
                waktu = ResponseFormatter._normalize_waktu(item.get("waktu"))
                ruang = ResponseFormatter._clean_field(item.get("ruang"))
                dosen_name = ResponseFormatter._clean_field(item.get("dosen"))
                kelas_info = "" if kelas else f" ({item.get('kelas', '-')})"

                response += f" {mata_kuliah}{kelas_info}\n"
                response += f"   {waktu}\n" if waktu != "-" else ""
                response += f"   {ruang}\n" if ruang != "-" else ""
                response += f"   {dosen_name}\n\n" if dosen_name != "-" else "\n"

        return response.strip()

    @staticmethod
    def format_jadwal_uas(data: List[Dict[str, Any]], kelas: str) -> str:
        """Format jadwal UAS response."""
        if not data:
            return (
                f"❌ Jadwal UAS untuk kelas **{kelas.upper()}** tidak ditemukan. "
                f"Pastikan format kelas benar (contoh: 1KA01)."
            )

        response = f"Jadwal UAS Kelas {data[0].get('kelas', kelas.upper())}\n\n"

        # Sort by date (diasumsikan 'YYYY-MM-DD' → aman di-sort string)
        sorted_data = sorted(data, key=lambda x: x.get("tanggal", ""))

        for item in sorted_data:
            mata_kuliah = ResponseFormatter._clean_title(item.get("mata_kuliah"))
            hari = ResponseFormatter.normalize_day(item.get("hari", "-"))
            tanggal = item.get("tanggal", "-")
            waktu = ResponseFormatter._normalize_waktu(item.get("waktu"))

            response += f" {mata_kuliah}\n"
            response += f"   {hari}, {tanggal}\n"
            response += f"   {waktu}\n\n"

        return response.strip()

    @staticmethod
    def format_wali_kelas(data: List[Dict[str, Any]], kelas: str) -> str:
        """Format wali kelas response."""
        if not data:
            return (
                f"❌ Data wali kelas untuk **{kelas.upper()}** tidak ditemukan. "
                f"Pastikan format kelas benar (contoh: 1KA01)."
            )

        wali = data[0]  # Harusnya satu wali per kelas
        dosen_name = wali.get("dosen", "-")
        kelas_name = wali.get("kelas", kelas.upper())

        response = f" **Wali Kelas {kelas_name}**\n\n"
        response += f"Dosen: **{dosen_name}**"

        return response

    @staticmethod
    def format_jadwal_loket(data: List[Dict[str, Any]]) -> str:
        """Format jadwal loket BAAK response."""
        if not data:
            return "❌ Data jadwal loket BAAK tidak tersedia saat ini."

        response = " **Jadwal Layanan BAAK**\n\n"

        # Group by section
        sections: Dict[str, List[Dict[str, Any]]] = {}
        for item in data:
            section = item.get("section", "Layanan BAAK")
            sections.setdefault(section, []).append(item)

        for section_name, items in sections.items():
            response += f"**{section_name}:**\n"

            for item in items:
                hari = ResponseFormatter.normalize_day(item.get("hari", "-"))
                jenis = item.get("jenis", "-")
                waktu_raw = item.get("waktu_raw", "-")

                response += f" **{jenis}**\n"
                response += f"   {hari}\n"
                response += f"   {waktu_raw}\n\n"

        return response.strip()

    @staticmethod
    def format_error_message(error_type: str, details: str = None) -> str:
        """Format error messages."""
        error_messages = {
            "kelas_not_found": "❌ Kelas tidak ditemukan. Pastikan format benar (contoh: 1KA01, 2SI02).",
            "dosen_not_found": "❌ Dosen tidak ditemukan. Coba nama lengkap atau bagian nama dosen.",
            "no_data": "❌ Data tidak tersedia saat ini.",
            "invalid_format": "❌ Format input tidak valid. Silakan coba lagi dengan format yang benar.",
            "system_error": "❌ Terjadi kesalahan sistem. Silakan coba beberapa saat lagi.",
        }

        base_message = error_messages.get(error_type, "❌ Terjadi kesalahan.")

        if details:
            return f"{base_message}\n\nDetail: {details}"

        return base_message

    @staticmethod
    def format_clarification_request(missing_param: str, intent: str) -> str:
        """Format clarification request messages."""
        clarification_messages = {
            "kelas": {
                "jadwal_kuliah": (
                    "🤔 Untuk menampilkan jadwal kuliah, silakan sebutkan kelasnya.\n\n"
                    "Contoh: **1KA01**, **2KB02**, **3KA01**"
                ),
                "jadwal_uas": (
                    "🤔 Untuk menampilkan jadwal UAS, silakan sebutkan kelasnya.\n\n"
                     "Contoh: **1KA01**, **2KB02**, **3KA01**"
                ),
                "wali_kelas": (
                    "🤔 Untuk menampilkan wali kelas, silakan sebutkan kelasnya.\n\n"
                     "Contoh: **1KA01**, **2KB02**, **3KA01**"
                ),
            },
            "dosen": {
                "jadwal_dosen": (
                    "🤔 Untuk menampilkan jadwal dosen, silakan sebutkan nama dosennya.\n\n"
                    "Contoh: **WITARI**, **DODDY ARI**, **TEAM TEACHING**"
                )
            },
        }

        if missing_param in clarification_messages and intent in clarification_messages[missing_param]:
            return clarification_messages[missing_param][intent]

        return "🤔 Silakan berikan informasi yang lebih spesifik untuk pertanyaan Anda."

    @staticmethod
    def _row_order(rec: Dict[str, Any]) -> int:
        """
        Ambil urutan preferensi dari record kalender.
        Prioritaskan kolom 'ord', fallback ke 'order'.
        Jika tidak ada / bukan angka → 9999 (taruh di belakang).
        """
        v = rec.get("ord", rec.get("order"))
        try:
            return int(v)
        except Exception:
            return 9999
    
    @staticmethod
    def _parse_iso(d: str) -> datetime | None:
        if not d: return None
        try:
            y, m, dd = d.split("-")
            return datetime(int(y), int(m), int(dd))
        except Exception:
            return None

    @staticmethod
    def _fmt_date_id(iso: str) -> str:
        if not iso or len(iso) < 10: 
            return iso or "-"
        y, m, d = iso[:4], iso[5:7], iso[8:10]
        try:
            m_int = int(m); d_int = int(d)
        except Exception:
            return iso
        month = ResponseFormatter._ID_MONTHS.get(m_int, m)
        return f"{d_int} {month} {y}"

    @staticmethod
    def _fmt_date_id_range(start: str | None, end: str | None, tanggal_raw: str | None) -> str:
        ds = ResponseFormatter._parse_iso(start)
        de = ResponseFormatter._parse_iso(end)
        if ds and de:
            if ds.date() == de.date():
                return ResponseFormatter._fmt_date_id(start)
            if ds.year == de.year:
                if ds.month == de.month:
                    bln = ResponseFormatter._ID_MONTHS[ds.month]
                    return f"{ds.day} {bln} - {de.day} {bln} {ds.year}"
                return (f"{ds.day} {ResponseFormatter._ID_MONTHS[ds.month]} - "
                        f"{de.day} {ResponseFormatter._ID_MONTHS[de.month]} {ds.year}")
            return (f"{ds.day} {ResponseFormatter._ID_MONTHS[ds.month]} {ds.year} - "
                    f"{de.day} {ResponseFormatter._ID_MONTHS[de.month]} {de.year}")
        if ds and not de:  return ResponseFormatter._fmt_date_id(start)
        if de and not ds:  return ResponseFormatter._fmt_date_id(end)
        return tanggal_raw or "-"

    @staticmethod
    def _fmt_range(start_date: str, end_date: str, tanggal_raw: str) -> str:
        # sekarang selalu pakai format Indonesia yang rapi
        return ResponseFormatter._fmt_date_id_range(start_date, end_date, tanggal_raw)

    @staticmethod
    def format_kalender_akademik(data: List[Dict[str, Any]], term: str = None, group: str = None) -> str:
        # Mode grup 'perkuliahan ... UTS'
        if group in ("sebelum_uts", "setelah_uts"):
            if not data:
                label = "Sebelum UTS" if group == "sebelum_uts" else "Setelah UTS"
                return f"❌ Data **Perkuliahan {label}** belum tersedia."
            label = "Sebelum UTS" if group == "sebelum_uts" else "Setelah UTS"
            head = f" **Perkuliahan {label}:**\n\n"
            # parent = level==1 yang mengandung 'Perkuliahan sebelum/ setelah UTS'
            def contains_key(x:str)->bool: 
                return (x or "").lower().find("perkuliahan")>=0 and (x or "").lower().find("uts")>=0
            parents = [r for r in data if str(r.get("level","")).strip() in ("1", 1) and contains_key(r.get("kegiatan"))]
            children = [r for r in data if r.get("parent_kegiatan") and contains_key(r.get("parent_kegiatan"))]
            lines = []
            # Jika ada anak, tampilkan anak; jika tidak, tampilkan parent range
            if children:
                # urutkan anak per tanggal/ord
                children_sorted = sorted(children, key=lambda r: (ResponseFormatter._row_order(r), r.get("start_date") or "9999-12-31"))
                for ch in children_sorted:
                    keg = ch.get("kegiatan", "-")
                    rng = ResponseFormatter._fmt_range(ch.get("start_date"), ch.get("end_date"), ch.get("tanggal_raw"))
                    lines.append(f" **{keg}**\n   {rng}")
            else:
                par = parents[0] if parents else data[0]
                rng = ResponseFormatter._fmt_range(par.get("start_date"), par.get("end_date"), par.get("tanggal_raw"))
                lines.append(f" **Masa Perkuliahan**\n   {rng}")
            return head + "\n".join(lines)

        # Mode umum (tanpa grup)
        if not data:
            if term:
                return f"❌ Tidak ada entri kalender untuk **{term.upper()}** saat ini."
            return "❌ Data kalender akademik belum tersedia."

        title = data[0].get("title", "Kalender Akademik")
        head = f"📆 **{title}**"
        if term:
            head += f" — *filter:* **{term.replace('_',' ').title()}**"
        head += "\n\n"

        lines, seen = [], set()
        data_sorted = sorted(
            data,
            key=lambda r: (ResponseFormatter._row_order(r), r.get("start_date") or "9999-12-31")
        )
        for row in data_sorted:
            key = (row.get("title"), row.get("kegiatan"), row.get("start_date"), row.get("end_date"), row.get("tanggal_raw"))
            if key in seen: 
                continue
            seen.add(key)
            keg = row.get("kegiatan", "-")
            rng = ResponseFormatter._fmt_range(row.get("start_date"), row.get("end_date"), row.get("tanggal_raw"))
            lines.append(f" **{keg}**\n   {rng}")

        return head + "\n".join(lines)

    @staticmethod
    def _sanitize_spaces(s: str) -> str:
        """Singkirkan spasi dobel / newline aneh agar tampilan rapi."""
        if s is None:
            return "-"
        s = str(s).replace("\\n", " ").strip()
        s = re.sub(r"\s+", " ", s)
        return s or "-"

    @staticmethod
    def _normalize_waktu(w: Any) -> str:
        """Normalisasi teks waktu: hilangkan None, perbaiki '//' jadi '/'. """
        if not w:
            return "-"
        s = str(w)
        s = s.replace("\\n", " ").strip()
        s = re.sub(r"/{2,}", "/", s)  # "7//8" -> "7/8"
        s = re.sub(r"\s+", " ", s)
        return s or "-"

    @staticmethod
    def _slot_rank(w: str) -> int:
        """
        Nilai kunci untuk sorting per hari:
        - "1/2", "3/4", "8/9/10" → ambil angka awal sebagai slot
        - "07.30 - 08.30" → konversi menit dari 00:00
        - lainnya → taruh di akhir
        """
        if not w:
            return 10_000
        w = str(w)

        # 1) Format slot "8/9/10" → 8
        m = re.match(r"\s*(\d+)\s*(?:/|$)", w)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass

        # 2) Format jam "07.30 - 08.30" atau "7.30-8.30"
        m = re.match(r"\s*(\d{1,2})[.:](\d{2})", w)
        if m:
            hh = int(m.group(1))
            mm = int(m.group(2))
            return hh * 60 + mm

        return 10_000

    # ---------- Util HTML ----------
    @staticmethod
    def _esc_html(s: Any) -> str:
        s = "" if s is None else str(s)
        return (
            s.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
        )

    # ---------- JADWAL KULIAH (HTML) ----------
    @staticmethod
    def format_jadwal_kuliah_html(
        data: List[Dict[str, Any]], 
        kelas: str = None, 
        dosen: str = None
    ) -> str:
        if not data:
            if kelas:
                return f"❌ Jadwal kuliah untuk kelas <b>{ResponseFormatter._esc_html(kelas.upper())}</b> tidak ditemukan."
            if dosen:
                return f"❌ Jadwal untuk dosen <b>{ResponseFormatter._esc_html(dosen)}</b> tidak ditemukan."
            return "❌ Data jadwal kuliah tidak ditemukan."

        # judul: pakai input user bila ada (biar alami untuk basis 3KA11 → A/B/C)
        display_kelas = (kelas or data[0].get("kelas") or "").upper()
        title = (
            f"Jadwal Kuliah Kelas {ResponseFormatter._esc_html(display_kelas)}"
            if kelas else
            f"Jadwal Kuliah Dosen {ResponseFormatter._esc_html(dosen)}"
        )

        # sort by hari + slot waktu
        days_order = ["Senin","Selasa","Rabu","Kamis","Jumat","Sabtu","Minggu"]
        day_rank = {d:i for i,d in enumerate(days_order)}
        def _norm_day(d): 
            return ResponseFormatter.normalize_day(d or "") or "Minggu"
        def _rank(row):
            d = _norm_day(row.get("hari"))
            w = ResponseFormatter._normalize_waktu(row.get("waktu"))
            return (day_rank.get(d, 999), ResponseFormatter._slot_rank(w))

        sorted_rows = sorted(data, key=_rank)

        # render table (KELAS di kolom paling depan)
        html = []
        html.append(f'<div class="font-semibold mb-2">{ResponseFormatter._esc_html(title)}</div>')
        html.append('<table class="tbl tbl--grid">')
        html.append('<thead class="text-xs text-slate-700 uppercase bg-slate-50"><tr>')
        for h in ["Kelas","Mata Kuliah","Hari","Jam","Ruang","Dosen"]:
            html.append(f'<th class="px-4 py-3">{h}</th>')
        html.append('</tr></thead><tbody>')

        for r in sorted_rows:
            kls   = ((r.get("kelas") or "-").strip().upper())
            mk    = ResponseFormatter._clean_title(r.get("mata_kuliah"))
            hari  = ResponseFormatter.normalize_day(r.get("hari") or "-")
            jam   = ResponseFormatter._normalize_waktu(r.get("waktu"))
            ruang = ResponseFormatter._clean_field(r.get("ruang"))
            dsn   = ResponseFormatter._clean_field(r.get("dosen"))

            html.append('<tr class="bg-white border-b hover:bg-slate-50">')
            html.append(f'<td class="px-4 py-3">{ResponseFormatter._esc_html(kls)}</td>')
            html.append(f'<td class="px-4 py-3">{ResponseFormatter._esc_html(mk)}</td>')
            html.append(f'<td class="px-4 py-3">{ResponseFormatter._esc_html(hari)}</td>')
            html.append(f'<td class="px-4 py-3">{ResponseFormatter._esc_html(jam)}</td>')
            html.append(f'<td class="px-4 py-3">{ResponseFormatter._esc_html(ruang)}</td>')
            html.append(f'<td class="px-4 py-3">{ResponseFormatter._esc_html(dsn)}</td>')
            html.append('</tr>')

        html.append('</tbody></table>')
        return "".join(html)


    # ---------- JADWAL UAS (HTML) ----------
    @staticmethod
    def format_jadwal_uas_html(data: List[Dict[str, Any]], kelas: str) -> str:
        if not data:
            return f"❌ Jadwal UAS untuk kelas <b>{ResponseFormatter._esc_html(kelas.upper())}</b> tidak ditemukan."

        display_kelas = (kelas or data[0].get("kelas") or "").upper()
        title = f"Jadwal UAS Kelas {ResponseFormatter._esc_html(display_kelas)}"

        sorted_rows = sorted(data, key=lambda x: (x.get("tanggal") or "", x.get("waktu") or ""))

        html = []
        html.append(f'<div class="font-semibold mb-2">{title}</div>')
        html.append('<table class="tbl tbl--grid">')
        html.append('<thead class="text-xs text-slate-700 uppercase bg-slate-50"><tr>')
        for h in ["Kelas","Mata Kuliah","Hari","Tanggal","Jam"]:
            html.append(f'<th class="px-4 py-3">{h}</th>')
        html.append('</tr></thead><tbody>')

        for r in sorted_rows:
            kls = ((r.get("kelas") or display_kelas or "-").strip().upper())
            mk  = ResponseFormatter._clean_title(r.get("mata_kuliah"))
            har = ResponseFormatter.normalize_day(r.get("hari") or "-")
            tgl = r.get("tanggal") or "-"
            tgl_id = ResponseFormatter._fmt_date_id(tgl) if tgl != "-" else "-"
            jam = ResponseFormatter._normalize_waktu(r.get("waktu"))

            html.append('<tr class="bg-white border-b hover:bg-slate-50">')
            html.append(f'<td class="px-4 py-3">{ResponseFormatter._esc_html(kls)}</td>')
            html.append(f'<td class="px-4 py-3">{ResponseFormatter._esc_html(mk)}</td>')
            html.append(f'<td class="px-4 py-3">{ResponseFormatter._esc_html(har)}</td>')
            html.append(f'<td class="px-4 py-3">{ResponseFormatter._esc_html(tgl_id)}</td>')
            html.append(f'<td class="px-4 py-3">{ResponseFormatter._esc_html(jam)}</td>')
            html.append('</tr>')
        html.append('</tbody></table>')
        return "".join(html)

    # ---------- JADWAL DOSEN (HTML) ----------
    @staticmethod
    def format_jadwal_dosen_html(data: List[Dict[str, Any]], dosen: str) -> str:
        # data = hasil get_jadwal_kuliah_by_dosen (struktur sama jadwal kuliah)
        return ResponseFormatter.format_jadwal_kuliah_html(data, kelas=None, dosen=dosen)

    # ---------- KALENDER AKADEMIK (HTML) ----------
    @staticmethod
    def format_kalender_akademik_html(
        data: List[Dict[str, Any]], 
        term: str = None, 
        group: str = None
    ) -> str:
        # Mode grup "perkuliahan sebelum/ setelah UTS"
        if group in ("sebelum_uts","setelah_uts"):
            label = "Sebelum UTS" if group == "sebelum_uts" else "Setelah UTS"
            if not data:
                return f"❌ Data <b>Perkuliahan {label}</b> belum tersedia."

            def contains_key(x: str) -> bool:
                x = (x or "").lower()
                return ("perkuliahan" in x) and ("uts" in x)

            parents  = [r for r in data if str(r.get("level","")).strip() in ("1", 1) and contains_key(r.get("kegiatan"))]
            children = [r for r in data if r.get("parent_kegiatan") and contains_key(r.get("parent_kegiatan"))]
            rows = []
            if children:
                children_sorted = sorted(
                    children,
                    key=lambda r: (ResponseFormatter._row_order(r), r.get("start_date") or "9999-12-31")
                )
                for ch in children_sorted:
                    keg = ch.get("kegiatan", "-")
                    rng = ResponseFormatter._fmt_date_id_range(ch.get("start_date"), ch.get("end_date"), ch.get("tanggal_raw"))
                    rows.append({"kegiatan": keg, "tanggal": rng})
            else:
                par = parents[0] if parents else data[0]
                rng = ResponseFormatter._fmt_date_id_range(par.get("start_date"), par.get("end_date"), par.get("tanggal_raw"))
                rows.append({"kegiatan": "Masa Perkuliahan", "tanggal": rng})

            title = f"Perkuliahan {label}"
        else:
            if not data:
                if term:
                    return f"❌ Tidak ada entri kalender untuk <b>{ResponseFormatter._esc_html(term.upper())}</b> saat ini."
                return "❌ Data kalender akademik belum tersedia."

            data_sorted = sorted(
                data,
                key=lambda r: (ResponseFormatter._row_order(r), r.get("start_date") or "9999-12-31")
            )
            rows = []
            seen = set()
            for r in data_sorted:
                key = (r.get("title"), r.get("kegiatan"), r.get("start_date"), r.get("end_date"), r.get("tanggal_raw"))
                if key in seen: 
                    continue
                seen.add(key)
                rng = ResponseFormatter._fmt_date_id_range(r.get("start_date"), r.get("end_date"), r.get("tanggal_raw"))
                rows.append({"kegiatan": r.get("kegiatan","-"), "tanggal": rng})
            title = data[0].get("title", "Kalender Akademik")
            if term:
                title += f" — filter: {term.replace('_',' ').title()}"

        # render table
        html = []
        html.append(f'<div class="font-semibold mb-2">{ResponseFormatter._esc_html(title)}</div>')
        html.append('<table class="tbl tbl--grid tbl--calendar">')
        html.append('<thead class="text-xs text-slate-700 uppercase bg-slate-50"><tr>')
        for h in ["Kegiatan","Tanggal / Periode"]:
            html.append(f'<th class="px-4 py-3">{h}</th>')
        html.append('</tr></thead><tbody>')
        for r in rows:
            html.append('<tr class="bg-white border-b hover:bg-slate-50">')
            html.append(f'<td class="px-4 py-3">{ResponseFormatter._esc_html(r.get("kegiatan","-"))}</td>')
            html.append(f'<td class="px-4 py-3">{ResponseFormatter._esc_html(r.get("tanggal","-"))}</td>')
            html.append('</tr>')
        html.append('</tbody></table>')
        return "".join(html)

    # ---------- JADWAL LOKET (HTML) ----------
    @staticmethod
    def format_jadwal_loket_html(data: List[Dict[str, Any]]) -> str:
        """Render jadwal loket BAAK dalam tabel HTML (garis tebal bila pakai .tbl--thick)."""
        if not data:
            return "❌ Data jadwal loket BAAK tidak tersedia saat ini."

        # --- NORMALISASI & URUTAN YANG DIINGINKAN ---
        def _norm_day_range(s: str) -> str:
            """Kelompokkan ke 'Senin-Kamis' / 'Jumat' / 'Sabtu' bila cocok; selain itu fallback ke nama hari normal."""
            s = (s or "").strip()
            sl = s.lower()
            if ("senin" in sl) and ("kamis" in sl):
                return "Senin-Kamis"
            if ("jumat" in sl) or ("jum'at" in sl):
                return "Jumat"
            if "sabtu" in sl:
                return "Sabtu"
            # fallback ke nama hari tunggal (jarang dipakai pada loket)
            return ResponseFormatter.normalize_day(s) or s

        # urutan utama hari/range
        DAY_ORDER = {
            "Senin-Kamis": 0,
            "Jumat": 1,
            "Sabtu": 2,
            # fallback kalau ada hari tunggal
            "Senin": 0, "Selasa": 0, "Rabu": 0, "Kamis": 0
        }
        # 'Layanan' tampil duluan daripada 'Istirahat'
        TYPE_ORDER = {"layanan": 0, "istirahat": 1}

        def _time_rank(w: str) -> int:
            """Urutkan berdasarkan jam mulai (format 'HH.MM - HH.MM ...'); jika gagal parse → taruh belakang."""
            import re
            m = re.match(r"\s*(\d{1,2})[.:](\d{2})", (w or ""))
            if not m:
                return 99999
            return int(m.group(1)) * 60 + int(m.group(2))

        def _section_rank(s: str) -> int:
            """Prioritaskan 'Pelayanan di Loket BAAK 1-8' di atas section lain (jika ada)."""
            s = (s or "").strip().lower()
            return 0 if s.startswith("pelayanan di loket baak") else 1

        def _r(x: Dict[str, Any]):
            section = (x.get("section") or "Layanan BAAK").strip()
            day     = _norm_day_range(x.get("hari"))
            jenis   = (x.get("jenis") or "").strip().lower()
            waktu   = (x.get("waktu_raw") or "").strip()
            return (
                _section_rank(section),
                DAY_ORDER.get(day, 99),
                TYPE_ORDER.get(jenis, 99),
                _time_rank(waktu),
            )

        rows = sorted(data, key=_r)

        # --- RENDER HTML (tanpa ubah struktur tabel) ---
        html = []
        html.append('<div class="font-semibold mb-2">Jadwal Layanan BAAK</div>')
        html.append('<table class="tbl tbl--grid tbl--thick">')
        html.append('<thead class="text-xs text-slate-700 uppercase bg-slate-50"><tr>')
        for h in ["Bagian / Loket","Jenis","Hari","Waktu"]:
            html.append(f'<th class="px-4 py-3">{h}</th>')
        html.append('</tr></thead><tbody>')

        for r in rows:
            section = (r.get("section") or "Layanan BAAK").strip()
            jenis   = (r.get("jenis") or "-").strip()
            hari    = ResponseFormatter.normalize_day(r.get("hari") or "-")
            waktu   = (r.get("waktu_raw") or "-").strip()

            html.append('<tr class="bg-white border-b hover:bg-slate-50">')
            html.append(f'<td class="px-4 py-3">{ResponseFormatter._esc_html(section)}</td>')
            html.append(f'<td class="px-4 py-3">{ResponseFormatter._esc_html(jenis)}</td>')
            html.append(f'<td class="px-4 py-3">{ResponseFormatter._esc_html(hari)}</td>')
            html.append(f'<td class="px-4 py-3">{ResponseFormatter._esc_html(waktu)}</td>')
            html.append('</tr>')

        html.append('</tbody></table>')
        return "".join(html)


    @staticmethod
    def format_daftar_mata_kuliah_html(items: list[dict]) -> str:
        """
        items = [{"title": "S1 - SISTEM INFORMASI", "url": "https://..."}, ...]
        """
        if not items:
            return "❌ Data daftar mata kuliah belum tersedia."

        # Urutkan: D3 dulu lalu S1, sisanya apa adanya
        def _rank(it):
            t = (it.get("title") or "").upper()
            if t.startswith("D3 - "): return (0, t)
            if t.startswith("S1 - "): return (1, t)
            return (2, t)

        items_sorted = sorted(items, key=_rank)

        html = []
        html.append('<div class="font-semibold mb-2">Daftar Mata Kuliah</div>')
        html.append('<table class="tbl tbl--grid tbl--thick"><thead><tr>')
        html.append('<th class="px-4 py-3">Program</th><th class="px-4 py-3">Unduh (PDF)</th>')
        html.append('</tr></thead><tbody>')
        for it in items_sorted:
            title = ResponseFormatter._esc_html(it.get("title","-"))
            url   = it.get("url","")
            link  = f'<a href="{url}" target="_blank" rel="noopener noreferrer">{title}</a>' if url else title
            html.append('<tr class="bg-white border-b hover:bg-slate-50">')
            # kolom 1: program singkat (mis. D3 / S1)
            prog = title.split(" - ", 1)[0] if " - " in title else "-"
            html.append(f'<td class="px-4 py-3">{ResponseFormatter._esc_html(prog)}</td>')
            # kolom 2: judul link lengkap
            html.append(f'<td class="px-4 py-3">{link}</td>')
            html.append('</tr>')
        html.append('</tbody></table>')
        return "".join(html)
    
# Singleton instance
formatter = ResponseFormatter()
