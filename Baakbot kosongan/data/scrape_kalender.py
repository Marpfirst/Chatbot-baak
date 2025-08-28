import csv, re, io, time, sys
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict
from pathlib import Path

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup, Tag

# ====== ATUR DI SINI (cukup Run) ===========================================
URL_PAGE = "https://baak.gunadarma.ac.id"  # pastikan ini URL halaman yg ada tabelnya
HEADING_FILTER = "Kalender Akademik Genap (ATA) 2024/2025"  # "" jika mau ambil semua heading


# Folder output RELATIF ke lokasi file script ini
SCRIPT_DIR = Path(__file__).resolve().parent
# (BARU) Path untuk output CSV
OUTPUT_DIR_CSV = SCRIPT_DIR / "data_scrap" / "csv"
OUTPUT_DIR_CSV.mkdir(parents=True, exist_ok=True)
# (BARU) Path untuk output Markdown
OUTPUT_DIR_MD = SCRIPT_DIR / "data_scrap" / "md"
OUTPUT_DIR_MD.mkdir(parents=True, exist_ok=True)

# Nama file:
OUT_CSV = OUTPUT_DIR_CSV / "kalender_genap_2024_2025.csv"
OUT_MD = OUTPUT_DIR_MD / "kalender_genap_2024_2025.md"  # (BARU) Nama file Markdown

HEADLESS = False  # True jika mau tanpa membuka jendela Chrome
CHROME_VERSION_MAIN = None  # contoh 139; biarkan None agar auto
# (opsional) gunakan profil Chrome pribadi agar lolos proteksi lebih mudah:
USER_DATA_DIR = None  # contoh: r"C:\Users\ASUS\AppData\Local\Google\Chrome\User Data"
PROFILE_DIR   = None  # contoh: "Default" atau "Profile 1"
# ===========================================================================

MONTHS_ID = {
    'januari':1,'februari':2,'maret':3,'april':4,'mei':5,'juni':6,
    'juli':7,'agustus':8,'september':9,'oktober':10,'november':11,'desember':12
}
HYPHENS = "\u2010\u2011\u2012\u2013\u2014\u2015-"

def clean_text(s: str) -> str:
    if not s: return ""
    s = re.sub(rf"[{HYPHENS}]", "-", s).replace("\xa0"," ")
    return re.sub(r"\s+"," ", s).strip()

def month_to_num(name: str) -> Optional[int]:
    return MONTHS_ID.get(name.lower().strip()) if name else None

def to_iso(y:int,m:int,d:int) -> str:
    return f"{y:04d}-{m:02d}-{d:02d}"

def parse_indonesian_date_range(s: str) -> Tuple[Optional[str], Optional[str]]:
    s = clean_text(s)
    if not s: return (None, None)
    m = re.match(r"(?i)^\s*(\d{1,2})\s+([A-Za-z]+)\s*-\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\s*$", s)
    if m:
        d1, mon1, d2, mon2, y = m.groups()
        m1, m2 = month_to_num(mon1), month_to_num(mon2)
        if m1 and m2: return to_iso(int(y),m1,int(d1)), to_iso(int(y),m2,int(d2))
    m = re.match(r"(?i)^\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\s*$", s)
    if m:
        d, mon, y = m.groups(); mnum = month_to_num(mon)
        if mnum:
            iso = to_iso(int(y), mnum, int(d))
            return iso, iso
    m = re.match(r"(?i)^\s*(\d{1,2})\s*-\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\s*$", s)
    if m:
        d1, d2, mon, y = m.groups(); mnum = month_to_num(mon)
        if mnum: return to_iso(int(y),mnum,int(d1)), to_iso(int(y),mnum,int(d2))
    return (None, None)

def find_heading_nodes(soup: BeautifulSoup, heading_query: Optional[str]) -> List[Tag]:
    hits=[]
    for h in soup.find_all("h3"):
        t = clean_text(h.get_text(" ", strip=True))
        if "kalender akademik" in t.lower() and (not heading_query or heading_query.lower() in t.lower()):
            hits.append(h)
    return hits

def extract_tables_after_heading(h: Tag) -> List[Tag]:
    tables=[]
    for sib in h.find_all_next():
        if isinstance(sib, Tag):
            if sib.name and sib.name.lower()=="h3": break
            if sib.name and sib.name.lower()=="table": tables.append(sib)
            # Disederhanakan agar lebih robust
            if len(tables)>=2 and sib.name.lower() not in ("table","tbody","tr","td","th","div", "b", "strong", "span"): break
    return tables

def table_rows_to_pairs(tb: Tag) -> List[Dict]:
    out=[]
    tbody = tb.find("tbody") or tb
    for tr_idx, tr in enumerate(tbody.find_all("tr")):
        tds = tr.find_all(["td","th"])
        # Lewati header row
        if len(tds)>=2 and (tds[0].name=="th" and tds[1].name=="th"): continue
        if len(tds)<2: continue

        kegiatan = clean_text(tds[0].get_text(" ", strip=True))
        tanggal  = clean_text(tds[1].get_text(" ", strip=True))
        # Hanya tambahkan jika kolom kegiatan tidak kosong
        if kegiatan:
            out.append({"order": tr_idx, "kegiatan": kegiatan, "tanggal": tanggal})
    return out

def dedup_preserve_order(records: List[Dict]) -> List[Dict]:
    seen=set(); out=[]
    for r in records:
        key=(r["kegiatan"].lower(), r["tanggal"].lower())
        if key not in seen:
            seen.add(key); out.append(r)
    return out

def build_flat(records: List[Dict], title_text: str) -> List[Dict]:
    items=[]; parent=None
    for r in records:
        kegiatan = r["kegiatan"]; tanggal = r["tanggal"]; order=r["order"]
        is_sub = bool(re.match(r"^[a-z]\.\s", kegiatan.lower()))
        level = 2 if is_sub else 1
        kegiatan_core = re.sub(r"^[a-z]\.\s","", kegiatan, flags=re.I).strip()
        parent_kegiatan = parent if is_sub else None
        if (not is_sub) and ((not tanggal) or kegiatan.endswith(".")):
            parent = kegiatan
        elif not is_sub:
            parent = None
        start, end = parse_indonesian_date_range(tanggal)
        items.append({
            "title": title_text,
            "order": order,
            "level": level,
            "kegiatan": kegiatan_core,
            "parent_kegiatan": parent_kegiatan,
            "tanggal_raw": tanggal,
            "start_date": start,
            "end_date": end
        })
    items.sort(key=lambda x: x["order"])
    return items

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
                EC.presence_of_element_located((By.XPATH,"//h3[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'kalender akademik')]")),
                EC.presence_of_element_located((By.CSS_SELECTOR,"table.table-custom.table-primary"))
            )
        )
        time.sleep(1.0)
        return driver.page_source
    finally:
        try: driver.quit()
        except: pass

# (BARU) Fungsi untuk menulis ke file Markdown
def write_to_markdown(all_data: List[Dict], filepath: Path):
    """Menulis data yang di-scrape ke dalam format tabel Markdown."""
    with open(filepath, "w", encoding="utf-8") as f:
        for item in all_data:
            title = item['title']
            records = item['records']
            
            f.write(f"## {title}\n\n")  # Judul dari Kalender
            f.write("| Kegiatan | Tanggal |\n")
            f.write("| :--- | :--- |\n")
            for record in records:
                # Ganti karakter | di dalam teks agar tidak merusak tabel MD
                kegiatan = record['kegiatan'].replace("|", "\\|")
                tanggal = record['tanggal'].replace("|", "\\|")
                f.write(f"| {kegiatan} | {tanggal} |\n")
            f.write("\n\n") # Beri spasi antar tabel jika ada lebih dari satu

    print(f"✔ Markdown tersimpan: {filepath}")


def main():
    print("[i] Membuka:", URL_PAGE)
    html = get_page_source_via_uc(URL_PAGE)
    soup = BeautifulSoup(html, "html.parser")

    headings = find_heading_nodes(soup, HEADING_FILTER)
    if not headings:
        print("! Heading 'Kalender Akademik' tidak ditemukan. Cek URL_PAGE/HEADING_FILTER.")
        sys.exit(1)

    all_items_for_csv = []
    all_items_for_md = [] # (BARU) List untuk data MD
    for h in headings:
        title_text = clean_text(h.get_text(" ", strip=True))
        tables = extract_tables_after_heading(h)
        if not tables: continue
        
        # Menggunakan data mentah yang lebih simpel untuk MD
        raw_recs = []
        for tb in tables:
            raw_recs += table_rows_to_pairs(tb)
        raw_recs = dedup_preserve_order(raw_recs)
        if raw_recs:
             all_items_for_md.append({'title': title_text, 'records': raw_recs})

        # Data yang lebih terstruktur untuk CSV
        all_items_for_csv += build_flat(raw_recs, title_text)

    if not all_items_for_csv:
        print("… Tidak ada baris data.")
        return

    # Tulis CSV (tetap ada)
    cols = ["title","order","level","kegiatan","parent_kegiatan","tanggal_raw","start_date","end_date"]
    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for row in all_items_for_csv:
            w.writerow(row)

    print(f"✔ CSV tersimpan: {OUT_CSV}")
    print(f"Total baris: {len(all_items_for_csv)}")

    # (BARU) Tulis Markdown
    if all_items_for_md:
        write_to_markdown(all_items_for_md, OUT_MD)

if __name__ == "__main__":
    main()