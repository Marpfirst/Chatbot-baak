
import csv, re, time, random
from typing import List, Tuple
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from bs4 import BeautifulSoup

BASE_URL = "https://baak.gunadarma.ac.id/kuliahUjian/3"
OUTPUT_CSV = "hasil_wali_kelas.csv"

# Urutan sesuai permintaan
QUERIES = ["1ka", "2ka", "3ka", "4ka", "1kb", "2kb", "3kb", "4kb"]

# Simpan hanya kode kelas 1–4 KA/KB (misal 4KA12, 2KB03)
PAT_CLASS = re.compile(r"^[1-4](KA|KB)\d{2}$", re.I)

def human_pause(a=0.35, b=0.85):
    time.sleep(random.uniform(a, b))

def parse_desktop_table(soup: BeautifulSoup) -> List[Tuple[str, str]]:
    rows = []
    tables = soup.select("table.table-custom.table-primary")
    target = None
    for t in tables:
        ths = [th.get_text(strip=True).lower() for th in t.select("tr th")]
        if ths and any("kelas" in h for h in ths) and any("dosen" in h for h in ths):
            target = t; break
    if not target: return rows
    for tr in target.select("tr"):
        tds = [td.get_text(strip=True) for td in tr.select("td")]
        if len(tds) == 3:
            _, kelas, dosen = tds
            if kelas and dosen:
                rows.append((kelas.upper(), dosen.strip()))
    return rows

def parse_stacktable(soup: BeautifulSoup) -> List[Tuple[str, str]]:
    rows = []
    keys = soup.select("td.st-key")
    vals = soup.select("td.st-val")
    if not keys or not vals: return rows
    kv = list(zip([k.get_text(strip=True) for k in keys],
                  [v.get_text(strip=True) for v in vals]))
    tmp_kelas = None
    for k, v in kv:
        lk = k.lower()
        if lk == "kelas":
            tmp_kelas = v.upper()
        elif lk == "dosen" and tmp_kelas:
            rows.append((tmp_kelas, v.strip()))
            tmp_kelas = None
    return rows

def parse_current_page(html: str):
    soup = BeautifulSoup(html, "lxml")
    rows = parse_desktop_table(soup)
    if not rows:
        rows = parse_stacktable(soup)
    return rows  # TANPA cek/klik Next

def find_search_input(driver):
    selectors = [
        'input[name="search_wali"]',
        'input[type="search"]',
        'input[placeholder*="wali"]',
        'input[placeholder*="cari"]',
        'input.form-control',
        'input[type="text"]'
    ]
    for sel in selectors:
        els = driver.find_elements(By.CSS_SELECTOR, sel)
        if els: return els[0]
    return None

def collect_single_page_for_query(driver, query_text: str):
    print(f"=== Query: {query_text.upper()} (tanpa pagination) ===")

    # reset ke halaman utama tiap ganti query
    driver.get(BASE_URL)
    human_pause(0.6, 1.0)

    # ketik ke kolom pencarian lalu ENTER
    inp = find_search_input(driver)
    if inp:
        try: inp.clear()
        except: pass
        human_pause()
        for ch in query_text:
            inp.send_keys(ch); time.sleep(random.uniform(0.05, 0.12))
        inp.send_keys(Keys.ENTER)
        human_pause(0.6, 1.0)
    else:
        # fallback: langsung URL query string
        driver.get(f"{BASE_URL}?search_wali={query_text}")
        human_pause(0.6, 1.0)

    html = driver.page_source
    rows = parse_current_page(html)
    print(f"[{query_text}] -> {len(rows)} baris (halaman ini saja)")
    return rows

def main():
    options = uc.ChromeOptions()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--start-maximized")
    # options.add_argument("--headless=new")  # aktifkan kalau sudah yakin aman

    driver = uc.Chrome(options=options)
    try:
        raw = []
        for q in QUERIES:
            raw.extend(collect_single_page_for_query(driver, q))
            human_pause(0.8, 1.2)

        # filter 1–4 KA/KB, dedup, format rapi
        seen = set()
        records = []
        for kelas, dosen in raw:
            ku = kelas.upper()
            if not PAT_CLASS.match(ku):
                continue
            key = (ku, dosen)
            if key in seen: continue
            seen.add(key)
            prefix = ku[:3]
            records.append({"prefix": prefix, "kelas": ku, "dosen": dosen})

        # optional: sort
        def sort_key(r):
            ang = int(r["kelas"][0])
            sts = r["kelas"][1:3]
            num = int(r["kelas"][3:5])
            return (sts, ang, num)
        records.sort(key=sort_key)

        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["prefix", "kelas", "dosen"])
            w.writeheader(); w.writerows(records)

        print(f"\nSelesai. Total baris tersimpan: {len(records)}")
        print(f"File: {OUTPUT_CSV}")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
