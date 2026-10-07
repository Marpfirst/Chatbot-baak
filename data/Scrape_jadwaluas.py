# scrape_uas_batch.py
# pip install undetected-chromedriver selenium beautifulsoup4 pandas openpyxl

import time, csv, gc, re, sys, random
from pathlib import Path
from collections import defaultdict

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import pandas as pd

URL = "https://baak.gunadarma.ac.id/jadwal/cariUas"

# === ATUR DI SINI ===
PREFIXES = ["1ka", "2ka", "3ka", "4ka", "1kb", "2kb", "3kb", "4kb"]  # ganti sesuai kebutuhan
MAX_NUM = 50                              # cek 01..MAX_NUM per prefix
CHROME_VERSION_MAIN = 138                 # sesuaikan versi Chrome utama (138/139/...)
DELAY_BETWEEN_SUBMITS = (1.0, 2.0)        # jeda acak antar submit (min, max) detik

WAIT_TIMEOUT_FIRST = 25                   # detik, submit pertama
WAIT_TIMEOUT_RETRY = 40                   # detik, retry & mini-refresh

OUT_CSV  = "jadwal_uas_all.csv"

# (opsional) pakai profil Chrome kamu (biar cookie/clearance ikut)
USER_DATA_DIR = None  # mis. r"C:\Users\ASUS\AppData\Local\Google\Chrome\User Data"
PROFILE_DIR   = None  # mis. "Default" atau "Profile 1"
# =====================

NOT_FOUND_PAT = re.compile(r"tidak\s+ada\s+dalam\s+database", re.I)

def rand_sleep(a_b_tuple):
    """Tidur acak (min,max) detik untuk menghindari rate-limiting."""
    a, b = a_b_tuple
    time.sleep(random.uniform(a, b))

def ensure_input(driver, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            return driver.find_element(By.CSS_SELECTOR, 'input[name="teks"]')
        except NoSuchElementException:
            time.sleep(0.2)
    raise TimeoutError("Input 'teks' tidak muncul (mungkin masih verifikasi Cloudflare).")

def parse_tables_from_html(html):
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.select("table.table-custom.table-primary")
    rows = []
    for tb in tables:
        for tr in tb.select("tr"):
            tds = tr.find_all("td")
            if len(tds) >= 4:
                rows.append((
                    tds[0].get_text(strip=True),  # Hari
                    tds[1].get_text(strip=True),  # Tanggal
                    tds[2].get_text(strip=True),  # Mata Kuliah
                    tds[3].get_text(strip=True),  # Waktu
                ))
    # de-dup small-only vs large-only
    uniq, seen = [], set()
    for r in rows:
        if r not in seen:
            seen.add(r)
            uniq.append(r)
    return uniq

def _wait_result_for_kelas(driver, kelas, timeout):
    """
    Tunggu hasil yang VALID untuk 'kelas':
      - muncul pesan 'tidak ada dalam database' untuk KELAS → 'not_found'
      - ATAU 'Untuk Input <b>KELAS</b>' + minimal 1 row di tabel → 'table'
      - fallback: kalau P tidak ada, tapi ada tabel + halaman mengandung 'Untuk Input KELAS'
    """
    kelas_lower = kelas.lower()
    wait = WebDriverWait(driver, timeout, poll_frequency=0.4)

    def condition(drv):
        html = drv.page_source
        low = html.lower()

        # not_found?
        if NOT_FOUND_PAT.search(low) and kelas_lower in low:
            return "not_found"

        # "Untuk Input <b>kelas</b>" cocok?
        try:
            drv.find_element(
                By.XPATH,
                f"//p[contains(., 'Untuk Input')][.//b[translate(normalize-space(text()),"
                f" 'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')='{kelas_lower}']]"
            )
            # cek tabel punya minimal 1 baris data
            rows = drv.find_elements(By.XPATH, "//table[contains(@class,'table-primary')]//tr[td]")
            if rows:
                return "table"
        except NoSuchElementException:
            pass

        # fallback: tabel ada + teks 'Untuk Input' mengandung kelas (kadang <p>-nya beda struktur)
        rows = drv.find_elements(By.XPATH, "//table[contains(@class,'table-primary')]//tr[td]")
        if rows and ("untuk input" in low and kelas_lower in low):
            return "table"

        return None

    try:
        res = wait.until(lambda d: (val := condition(d)) in ("table", "not_found") and val)  # return val
        return res
    except Exception:
        return "timeout"

def _type_clear(inp):
    """Clear input lebih 'tegas' supaya benar² kosong."""
    inp.click()
    inp.send_keys(Keys.CONTROL, "a")
    inp.send_keys(Keys.DELETE)
    time.sleep(0.15)

def submit_kelas(driver, kelas, type_delay=0.03):
    """Isi input & submit normal."""
    inp = ensure_input(driver, timeout=60)
    _type_clear(inp)
    for ch in kelas:
        inp.send_keys(ch); time.sleep(type_delay)
    try:
        btn = driver.find_element(By.CSS_SELECTOR, 'form[action*="/jadwal/cariUas"] button[type="submit"]')
        btn.click()
    except NoSuchElementException:
        inp.send_keys(Keys.ENTER)

def _resubmit(driver, kelas, type_delay=0.035):
    """Re-submit (ketik ulang lambat)."""
    submit_kelas(driver, kelas, type_delay=type_delay)

def scrape_one(driver, kelas):
    """
    Return (status, rows):
      'ok'        : tabel valid utk kelas ini
      'not_found' : pesan 'tidak ada dalam database'
      'empty'     : sudah di-retry + mini-refresh tapi tetap tidak dapat
    Tahap:
      1) submit normal → tunggu hasil valid
      2) retry sekali → tunggu hasil valid
      3) mini-refresh (reload URL) → submit lagi → tunggu
    """
    # 1) submit normal
    submit_kelas(driver, kelas)
    outcome = _wait_result_for_kelas(driver, kelas, timeout=WAIT_TIMEOUT_FIRST)
    if outcome == "table":
        return "ok", parse_tables_from_html(driver.page_source)
    if outcome == "not_found":
        return "not_found", []

    # 2) retry sekali
    _resubmit(driver, kelas, type_delay=0.035)
    outcome2 = _wait_result_for_kelas(driver, kelas, timeout=WAIT_TIMEOUT_RETRY)
    if outcome2 == "table":
        return "ok", parse_tables_from_html(driver.page_source)
    if outcome2 == "not_found":
        return "not_found", []

    # 3) mini-refresh form → submit lagi
    driver.get(URL)
    _ = ensure_input(driver, timeout=60)
    time.sleep(0.5)
    _resubmit(driver, kelas, type_delay=0.04)
    outcome3 = _wait_result_for_kelas(driver, kelas, timeout=WAIT_TIMEOUT_RETRY)
    if outcome3 == "table":
        return "ok", parse_tables_from_html(driver.page_source)
    if outcome3 == "not_found":
        return "not_found", []

    # tetap gagal → anggap empty
    return "empty", []

def save_outputs(all_rows):
    if not all_rows:
        print("\nTidak ada data yang terkumpul.")
        return
    # CSV
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["kelas","hari","tanggal","mata_kuliah","waktu"])
        w.writerows(all_rows)
    print(f"\nCSV tersimpan: {Path(OUT_CSV).resolve()}")

def main():
    options = uc.ChromeOptions()
    options.add_argument("--lang=id-ID")
    options.add_argument("--disable-blink-features=AutomationControlled")
    # opsi: headless baru chromedriver cenderung terdeteksi; gunakan visible jika bisa
    # options.add_argument("--headless=new")  # jika ingin headless, coba aktifkan baris ini bila perlu

    if USER_DATA_DIR:
        options.add_argument(rf"--user-data-dir={USER_DATA_DIR}")
    if PROFILE_DIR:
        options.add_argument(rf"--profile-directory={PROFILE_DIR}")

    driver = None
    all_rows = []  # (kelas, hari, tanggal, mata_kuliah, waktu)

    try:
        driver = uc.Chrome(version_main=CHROME_VERSION_MAIN, options=options)
        driver.set_window_size(1366, 900)
        driver.get(URL)
        time.sleep(3)  # beri waktu Cloudflare/Turnstile

        for prefix in PREFIXES:
            ada_data_di_prefix = False

            for n in range(1, MAX_NUM + 1):
                kelas = f"{prefix}{n:02d}"
                try:
                    status, rows = scrape_one(driver, kelas)
                except KeyboardInterrupt:
                    print("\n[CTRL+C] Simpan progres & keluar…")
                    save_outputs(all_rows)
                    if driver:
                        try:
                            driver.quit()
                        except Exception:
                            pass
                        driver = None
                        gc.collect()
                    sys.exit(0)
                except Exception as e:
                    print(f"! {kelas}: ERROR -> {e}")
                    status, rows = ("empty", [])

                if status == "ok" and rows:
                    ada_data_di_prefix = True
                    for h, t, mk, w in rows:
                        all_rows.append((kelas, h, t, mk, w))
                    print(f"✔ {kelas}: {len(rows)} baris")
                elif status == "not_found":
                    print(f"✘ {kelas}: tidak ada dalam database (skip prefix)")
                    # sesuai permintaan: begitu not_found → hentikan prefix ini
                    break
                else:  # empty
                    print(f"… {kelas}: kosong/timeout setelah retry (skip)")

                rand_sleep(DELAY_BETWEEN_SUBMITS)

            if not ada_data_di_prefix:
                print(f"— Prefix {prefix} tidak menghasilkan data")

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
            driver = None
            gc.collect()

    save_outputs(all_rows)

if __name__ == "__main__":
    main()
