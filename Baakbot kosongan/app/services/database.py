from supabase import create_client, Client
from typing import List, Dict, Optional, Any
import os, re
import asyncio
from app.config import settings


class DatabaseService:
    def __init__(self):
        self.supabase: Client = create_client(
            settings.SUPABASE_URL, 
            settings.SUPABASE_KEY
        )
    
    def normalize_kelas(self, kelas: str) -> str:
        """Normalize class input: 1ka01 -> 1KA01"""
        return kelas.upper().strip()
    
    async def _to_thread(self, fn):
        """Jalankan fungsi sync di thread agar tidak memblok event loop."""
        return await asyncio.to_thread(fn)

    async def ping(self) -> bool:
        """Ping ringan ke DB (dipakai health check)."""
        try:
            def _q():
                return self.supabase.table("jadwal_loket").select("id").limit(1).execute()
            _ = await self._to_thread(_q)
            return True
        except Exception:
            return False
    async def get_kelas_by_prefix(self, prefix: str, include_uas: bool = True) -> List[str]:
        """
        Ambil daftar kelas unik yang diawali prefix (mis. '4KA' → ['4KA01','4KA02',...]).
        Menggabungkan dari tabel jadwal_kuliah (UPPER) dan opsional jadwal_uas (lower).
        """
        prefix = (prefix or "").strip()
        if not prefix:
            return []

        p_upper = prefix.upper()
        p_lower = prefix.lower()

        try:
            # jadwal_kuliah: kelas disimpan uppercase (berdasar fungsi-fungsi yang ada)
            resp1 = self.supabase.table("jadwal_kuliah") \
                .select("kelas") \
                .ilike("kelas", f"{p_upper}%") \
                .execute()
            rows1 = resp1.data or []
        except Exception:
            rows1 = []

        rows2 = []
        if include_uas:
            try:
                # jadwal_uas: kelas disimpan lowercase (lihat get_jadwal_uas_by_kelas)
                resp2 = self.supabase.table("jadwal_uas") \
                    .select("kelas") \
                    .ilike("kelas", f"{p_lower}%") \
                    .execute()
                rows2 = resp2.data or []
            except Exception:
                rows2 = []

        # Gabungkan, normalisasi ke UPPER, dedup
        kelas_set = set()
        for r in rows1:
            k = (r.get("kelas") or "").strip()
            if k:
                kelas_set.add(k.upper())
        for r in rows2:
            k = (r.get("kelas") or "").strip()
            if k:
                kelas_set.add(k.upper())

        # Urutkan secara natural berdasarkan suffix 2 digit (kalau ada)
        def _suffix_num(k: str) -> int:
            m = re.search(r"(\d{2})$", k)
            return int(m.group(1)) if m else -1

        kelas_sorted = sorted(k for k in kelas_set if k.startswith(p_upper))
        kelas_sorted = sorted(kelas_sorted, key=lambda x: (_suffix_num(x), x))
        return kelas_sorted

    async def get_kelas_prefix_stats(self, prefix: str) -> Dict[str, Any]:
        """
        Hitung min/max nomor kelas untuk prefix (mis. 3KA, 3KB, 2TI, 4MI, dst).
        Menghitung dari tabel jadwal_kuliah. Bisa kamu perluas ke UAS bila mau.
        """
        p = (prefix or "").strip().upper()
        if not re.fullmatch(r"[1-6][A-Z]{2,3}", p):
            return {"exists": False, "min": None, "max": None, "count": 0}

        try:
            def _q():
                return (self.supabase.table("jadwal_kuliah")
                        .select("kelas")
                        .ilike("kelas", f"{p}%")
                        .execute())
            resp = await self._to_thread(_q)
            rows = resp.data or []

            nums = []
            bases = set()
            for r in rows:
                kls = (r.get("kelas") or "").upper().strip()
                m = re.match(rf"^{re.escape(p)}(\d{{2}})", kls)  # ambil 2 digit setelah prefix
                if m:
                    n = int(m.group(1))
                    nums.append(n)
                    bases.add(f"{p}{m.group(1)}")

            if not nums:
                return {"exists": False, "min": None, "max": None, "count": 0}

            return {
                "exists": True,
                "min": min(nums),
                "max": max(nums),
                "count": len(bases)
            }
        except Exception as e:
            print(f"Error prefix stats: {e}")
            return {"exists": False, "min": None, "max": None, "count": 0}
        
    async def get_jadwal_kuliah_by_kelas(self, kelas: str) -> List[Dict[str, Any]]:
        k = self.normalize_kelas(kelas)  # upper + strip
        try:
            # 3 pola: base+2digit(+opsi huruf)
            base2 = re.fullmatch(r"[1-6][A-Z]{2,3}\d{2}", k)              # 3KA11 / 3KB08 / 2MI03 ...
            with_suffix = re.fullmatch(r"[1-6][A-Z]{2,3}\d{2}[A-Z]$", k)  # 3KA11A / 3KB08B ...
            if with_suffix:
                q = self.supabase.table("jadwal_kuliah").select("*").eq("kelas", k)
            elif base2:
                q = self.supabase.table("jadwal_kuliah").select("*").ilike("kelas", f"{k}%")
            else:
                # fallback: exact
                q = self.supabase.table("jadwal_kuliah").select("*").eq("kelas", k)

            resp = await self._to_thread(lambda: q.execute())
            return resp.data or []
        except Exception as e:
            print(f"Error querying jadwal_kuliah: {e}")
            return []
    
    async def get_jadwal_kuliah_by_dosen(self, dosen: str) -> List[Dict[str, Any]]:
        """Get schedule by lecturer (partial matching)"""
        dosen_normalized = dosen.upper().strip()
        
        try:
            response = self.supabase.table("jadwal_kuliah")\
                .select("*")\
                .ilike("dosen", f"%{dosen_normalized}%")\
                .execute()
            
            return response.data
        except Exception as e:
            print(f"Error querying jadwal_kuliah by dosen: {e}")
            return []
    
    async def get_jadwal_uas_by_kelas(self, kelas: str) -> List[Dict[str, Any]]:
        """Get UAS schedule by class (data disimpan lowercase, dukung 3KA11A/B/C)."""
        k = (kelas or "").strip().lower()
        try:
            def _q():
                q = self.supabase.table("jadwal_uas").select("*")
                if re.search(r"[a-z]$", k):
                    q = q.eq("kelas", k)        # exact kalau ada huruf
                else:
                    q = q.ilike("kelas", f"{k}%")  # basis -> semua varian
                return q.execute()
            resp = await self._to_thread(_q)
            return resp.data or []
        except Exception as e:
            print(f"Error querying jadwal_uas: {e}")
            return []
    
    async def get_wali_kelas_by_kelas(self, kelas: str) -> List[Dict[str, Any]]:
        """Get homeroom teacher by class"""
        normalized_kelas = self.normalize_kelas(kelas)
        
        try:
            response = self.supabase.table("wali_kelas")\
                .select("*")\
                .eq("kelas", normalized_kelas)\
                .execute()
            
            return response.data
        except Exception as e:
            print(f"Error querying wali_kelas: {e}")
            return []
    
    async def get_jadwal_loket(self) -> List[Dict[str, Any]]:
        """Get BAAK service counter schedule (static data)"""
        try:
            response = self.supabase.table("jadwal_loket")\
                .select("*")\
                .execute()
            
            return response.data
        except Exception as e:
            print(f"Error querying jadwal_loket: {e}")
            return []

    async def get_kalender_akademik(self, term: Optional[str] = None, group: Optional[str] = None) -> List[Dict[str, Any]]:
        """Ambil entri kalender; bisa difilter istilah (uts, uas, cuti, krs, daftar_ulang, libur, uji_kompetensi)."""
        try:
            # Khusus grup 'perkuliahan sebelum/setelah UTS' → ambil parent  anak
            if group in ("sebelum_uts", "setelah_uts"):
                key = "sebelum uts" if group == "sebelum_uts" else "setelah uts"
                patt = f"%perkuliahan {key}%"
                # parent
                parent = self.supabase.table("kalender_akademik")\
                    .select("*")\
                    .ilike("kegiatan", patt)\
                    .execute()
                # children
                children = self.supabase.table("kalender_akademik")\
                    .select("*")\
                    .ilike("parent_kegiatan", patt)\
                    .order("start_date", desc=False)\
                    .order("ord", desc=False)\
                    .execute()
                p = (parent.data or [])
                c = (children.data or [])
                return p + c

            # Fallback: filter by term (uts/uas/...)
            q = self.supabase.table("kalender_akademik").select("*")
            if term == "uts":
                q = q.ilike("kegiatan", "%ujian tengah%")
            elif term == "uas":
                q = q.ilike("kegiatan", "%ujian akhir%")
            elif term == "cuti":
                q = q.ilike("kegiatan", "%cuti%")
            elif term == "krs":
                q = q.ilike("kegiatan", "%krs%")
            elif term == "daftar_ulang":
                q = q.ilike("kegiatan", "%daftar ulang%")
            elif term == "libur":
                q = q.ilike("kegiatan", "%libur%")
            elif term == "uji_kompetensi":
                q = q.ilike("kegiatan", "%uji kompetensi%")

            resp = q.order("start_date", desc=False).order("ord", desc=False).execute()
            return resp.data
        except Exception as e:
            print(f"Error querying kalender_akademik: {e}")
            return []

# Singleton instance
db_service = DatabaseService()