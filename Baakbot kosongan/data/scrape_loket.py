import csv, re, time, sys
from datetime import datetime
from typing import Optional, Tuple, List, Dict
from pathlib import Path

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup, Tag

# ====== KONFIGURASI =========================================================
URL_PAGE = "https://baak.gunadarma.ac.id"     # Halaman yang memuat section Loket
SECTION_TARGET = "Pelayanan di Loket BAAK"    # Kata kunci heading (dibuat fleksibel)

# Folder output RELATIF ke lokasi file script ini
SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR_CSV = SCRIPT_DIR / "data_scrap" / "csv"
OUTPUT_DIR_MD  = SCRIPT_DIR / "data_scrap" / "md"
OUTPUT_DIR_CSV.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR_MD.mkdir(parents=True, exist_ok=True)

OUT_CSV = OUTPUT_DIR_CSV / "loket_baak_1_8.csv"
OUT_MD  = OUTPUT_DIR_MD  / "loket_baak_1_8.md"

HEADLESS = False                 # True jika mau headless
CHROME_VERSION_MAIN = None       # contoh 139; biarkan None agar auto
USER_DATA_DIR = None             # contoh: r"C:\Users\ASUS\AppData\Local\Google\Chrome\User Data"
PROFILE_DIR   = None             # contoh: "Default" atau "Profile 1"
# ===========================================================================

HYPHENS = "\u2010\u2011\u2012\u2013\u2014\u2015-"

def clean_text(s: str) -> str:
    if not s: 
        return ""
    s = re.sub(rf"[{HYPHENS}]", "-", s).replace("\xa0"," ")
    return re.sub(r"\s+"," ", s).strip()

def parse_waktu_range(w: str) -> Tuple[Optional[str], Optional[str]]:
    """
    '10.00-15.00 WIB' -> ('10:00','15:00')
    '11.30-13.30 WIB' -> ('11:30','13:30')
    """
    if not w:
        return (None, None)
    txt = clean_text(w).upper().replace("WIB","").strip()
    m = re.match(r"^(\d{1,2})[.:](\d{2})\s*-\s*(\d{1,2})[.:](\d{2})$", txt)
    if not m:
        # fallback: hanya satu jam?
        m2 = re.match(r"^(\d{1,2})[.:](\d{2})$", txt)
        if m2:
            hh, mm = m2.groups()
            t = f"{int(hh):02d}:{int(mm):02d}"
            return (t, t)
        return (None, None)
    h1, m1, h2, m2 = m.groups()
    return (f"{int(h1):02d}:{int(m1):02d}", f"{int(h2):02d}:{int(m2):02d}")

def get_page_source_via_uc(url: str) -> str:
    options = uc.ChromeOptions()
    options.add_argument("--lang=id-ID")
    options.add_argument("--disable-blink-features=AutomationControlled")
    if USER_DATA_DIR: options.add_argument(rf"--user-data-dir={USER_DATA_DIR}")
    if PROFILE_DIR:   options.add_argument(rf"--profile-directory={PROFILE_DIR}")
    if HEADLESS:      options.add_argument("--headless=new")
    driver = uc.Chrome(version_main=CHROME_VERSION_MAIN, options=options)
    driver.set_window_size(1366, 900)
    try:
        driver.get(url)
        WebDriverWait(driver, 45).until(
            EC.any_of(
                EC.presence_of_element_located((By.XPATH,"//h6")),
                EC.presence_of_element_located((By.CSS_SELECTOR,"table"))
            )
        )
        time.sleep(1.0)  # beri waktu render
        return driver.page_source
    finally:
        try: driver.quit()
        except: pass

def find_loket_heading(soup: BeautifulSoup, keyword: str) -> Optional[Tag]:
    """
    Cari <h6> (atau <h5>) yang memuat frasa 'Pelayanan di Loket BAAK'.
    Dibuat toleran agar tak sensitif spasi/angka.
    """
    kws = keyword.lower()
    for tag in soup.find_all(["h6","h5"]):
        t = clean_text(tag.get_text(" ", strip=True)).lower()
        if "pelayanan di loket baak" in t:    # inti frasa
            return tag
        if kws in t:  # fallback
            return tag
    return None

def has_class_part(tag: Tag, part: str) -> bool:
    """Cek apakah class mengandung fragmen tertentu (mis. 'large-only' atau 'small-only')."""
    if not tag or not tag.has_attr("class"):
        return False
    classes = [str(c).lower() for c in tag.get("class", [])]
    return any(part.lower() in c for c in classes)

def parse_large_table(tb: Tag) -> List[Dict]:
    """
    Tabel versi desktop (large-only): kolom [Hari, Waktu]
    Baris '(Istirahat)' mengacu ke 'Hari' sebelumnya.
    """
    out: List[Dict] = []
    current_day: Optional[str] = None

    for tr in tb.find_all("tr"):
        tds = tr.find_all(["td","th"])
        if not tds or len(tds) < 2:
            continue

        hari = clean_text(tds[0].get_text(" ", strip=True))
        waktu = clean_text(tds[1].get_text(" ", strip=True))

        # Lewati header
        if hari.lower() == "hari" and waktu.lower() == "waktu":
            continue

        if hari and hari != "(Istirahat)":
            current_day = hari
            jenis = "Layanan"
        else:
            # (Istirahat) -> gunakan current_day
            jenis = "Istirahat"

        # Safety: jika belum ada current_day (misal markup tak terduga)
        if not current_day:
            current_day = "Tidak diketahui"

        start, end = parse_waktu_range(waktu)
        out.append({
            "section": "Pelayanan di Loket BAAK 1-8",
            "hari": current_day,
            "jenis": jenis,
            "waktu_raw": waktu,
            "start_time": start,
            "end_time": end
        })
    return out

def parse_small_stacktable(tb: Tag) -> List[Dict]:
    """
    Tabel versi mobile (small-only).
    Pola: TH 'Hari' (header), lalu TH 'Senin-Kamis', lalu row 'Waktu' (td,td),
          lalu TH '(Istirahat)', lalu row 'Waktu', dst.
    """
    out: List[Dict] = []
    current_day: Optional[str] = None
    pending_jenis: Optional[str] = None

    for tr in tb.find_all("tr"):
        ths = tr.find_all("th")
        tds = tr.find_all("td")

        if ths and len(ths) == 1:
            label = clean_text(ths[0].get_text(" ", strip=True))
            if label.lower() == "hari":
                continue  # header
            if label == "(Istirahat)":
                pending_jenis = "Istirahat"
                # current_day tetap mengacu ke hari sebelumnya
            else:
                current_day = label
                pending_jenis = "Layanan"
            continue

        if tds and len(tds) == 2:
            k = clean_text(tds[0].get_text(" ", strip=True))
            v = clean_text(tds[1].get_text(" ", strip=True))
            if k.lower() == "waktu" and pending_jenis:
                start, end = parse_waktu_range(v)
                out.append({
                    "section": "Pelayanan di Loket BAAK 1-8",
                    "hari": current_day or "Tidak diketahui",
                    "jenis": pending_jenis,
                    "waktu_raw": v,
                    "start_time": start,
                    "end_time": end
                })
                pending_jenis = None
    return out

def extract_loket_records(soup: BeautifulSoup) -> List[Dict]:
    h = find_loket_heading(soup, SECTION_TARGET)
    if not h:
        return []

    # Prefer 'large-only' (desktop)
    large = None
    small = None

    # Cari table di dalam/sekitar container <div> setelah h6
    # Ambil hanya tabel2 sesudah heading yang dekat (offset-top-30 wrapper).
    container = h.find_parent("div")
    search_root = container if container else h

    for tb in search_root.find_all_next("table", limit=4):
        if has_class_part(tb, "large-only"):
            large = tb
            break
        if not small and has_class_part(tb, "small-only"):
            small = tb

        # stop jika sudah melewati section berikutnya (ada heading lain)
        nxt = tb.find_next_sibling()
        if nxt and nxt.name in ("h5","h6","h3"):
            break

    if large:
        return parse_large_table(large)
    if small:
        return parse_small_stacktable(small)

    # fallback: kalau tidak ketemu class, coba tabel pertama setelah heading
    any_tb = h.find_next("table")
    return parse_large_table(any_tb) if any_tb else []

def write_csv(rows: List[Dict], path: Path) -> None:
    cols = ["section","hari","jenis","waktu_raw","start_time","end_time"]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in cols})

def write_markdown(rows: List[Dict], path: Path) -> None:
    # Kelompokkan per hari agar enak dibaca
    by_day: Dict[str, List[Dict]] = {}
    for r in rows:
        by_day.setdefault(r["hari"], []).append(r)

    lines = []
    lines.append("# Pelayanan di Loket BAAK 1-8")
    for day in sorted(by_day.keys(), key=lambda x: x or ""):
        lines.append(f"\n## {day}")
        for r in by_day[day]:
            jenis = r["jenis"]
            jam = r["waktu_raw"]
            st, et = r.get("start_time"), r.get("end_time")
            if st and et:
                lines.append(f"- **{jenis}**: {st}–{et} WIB (raw: {jam})")
            else:
                lines.append(f"- **{jenis}**: {jam}")
    path.write_text("\n".join(lines), encoding="utf-8")

def main():
    print("[i] Membuka:", URL_PAGE)
    html = get_page_source_via_uc(URL_PAGE)
    soup = BeautifulSoup(html, "html.parser")

    loket_rows = extract_loket_records(soup)
    if not loket_rows:
        print("! Section 'Pelayanan di Loket BAAK' tidak ditemukan. Cek URL_PAGE/markup situs.")
        sys.exit(1)

    write_csv(loket_rows, OUT_CSV)
    write_markdown(loket_rows, OUT_MD)

    print(f"✔ CSV tersimpan: {OUT_CSV}")
    print(f"✔ Markdown tersimpan: {OUT_MD}")
    print(f"Total baris: {len(loket_rows)}")

if __name__ == "__main__":
    main()
