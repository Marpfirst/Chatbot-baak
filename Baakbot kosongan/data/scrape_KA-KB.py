# scrape_playwright_multi_faststop.py
from playwright.sync_api import sync_playwright
import pandas as pd
import random, time

# ============== KONFIGURASI ==============
PREFIXES = ["1ka","2ka","3ka","4ka","1kb","2kb","3kb","4kb"]
START_NUM = 1
HEADLESS = True
OUT_CSV = "jadwal_kuliah.csv"

# Batas maksimum nomor per prefix (None = tidak dibatasi)
MAX_NUM = None  # mis. 60 kalau mau scan 01..60

# Timing & retry (ringan agar cepat)
PAGE_TIMEOUT = 45000      # ms
WAIT_TD_TIMEOUT = 7000    # ms tunggu <td> pertama
RETRIES_PER_PAGE = 1      # nunggu <td> ulang 1x
RETRY_ON_EMPTY = 1        # 0=matikan; 1=sekali reload cepat kalau kosong
# ========================================

BASE = "https://baak.gunadarma.ac.id/jadwal/cariJadKul"
UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
]

def url_for(kelas: str) -> str:
    # cache-busting agar tidak keambil cache CDN
    ts = int(time.time() * 1000)
    return f"{BASE}?teks={kelas}&filter=*.html&_ts={ts}"

JS_SCRAPE = """
() => {
  const tables = Array.from(document.querySelectorAll('table.table.table-custom'));
  const rows = [];
  for (const tbl of tables) {
    const trs = Array.from(tbl.querySelectorAll('tr'));
    for (const tr of trs) {
      const tds = Array.from(tr.querySelectorAll('td'));
      if (tds.length >= 6) {
        const rec = {
          kelas: tds[0].innerText.trim(),
          hari: tds[1].innerText.trim(),
          mata_kuliah: tds[2].innerText.trim(),
          waktu: tds[3].innerText.trim(),
          ruang: tds[4].innerText.trim(),
          dosen: tds[5].innerText.trim(),
        };
        if (rec.kelas && rec.kelas.toUpperCase() !== "KELAS") rows.push(rec);
      }
    }
  }
  let berlaku_mulai = null;
  for (const p of Array.from(document.querySelectorAll('p.text-md-left'))) {
    const txt = p.innerText.trim();
    if (txt.includes('Berlaku Mulai')) {
      const parts = txt.split(':');
      berlaku_mulai = (parts.length > 1 ? parts.slice(1).join(':') : '').trim();
      break;
    }
  }
  return {rows, berlaku_mulai};
}
"""

def goto_fast(page, url: str):
    # domcontentloaded cukup (lebih cepat dari networkidle)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
    except Exception:
        page.goto(url, timeout=PAGE_TIMEOUT)

def wait_rows(page, max_wait_ms: int, retries: int):
    for _ in range(retries + 1):
        try:
            page.wait_for_selector("table.table.table-custom tr td", timeout=max_wait_ms)
            return True
        except Exception:
            page.wait_for_timeout(600)
    return False

def scrape_once(page, kelas: str):
    goto_fast(page, url_for(kelas))
    # sinkronisasi ringan (opsional)
    try:
        page.wait_for_selector("text=Untuk Input", timeout=1500)
    except:
        pass
    wait_rows(page, WAIT_TD_TIMEOUT, RETRIES_PER_PAGE)
    data = page.evaluate(JS_SCRAPE)
    rows = data["rows"] or []
    berlaku_mulai = data["berlaku_mulai"]
    for r in rows:
        r["input_kelas"] = kelas
        r["berlaku_mulai"] = berlaku_mulai
    return rows

def make_context(browser):
    ua = random.choice(UA_POOL)
    context = browser.new_context(user_agent=ua, locale="id-ID", bypass_csp=True)
    # blokir resource berat biar cepat
    def route_block(route, request):
        if request.resource_type in ("document", "script", "xhr", "fetch"):
            route.continue_()
        else:
            route.abort()
    context.route("**/*", route_block)
    return context

def run():
    all_rows = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS, args=["--lang=id-ID", "--disable-extensions", "--no-first-run"])
        for prefix in PREFIXES:
            print(f"=== Mulai prefix: {prefix} ===")
            context = make_context(browser)
            page = context.new_page()

            n = START_NUM
            while True:
                if MAX_NUM and n > MAX_NUM:
                    print(f"Batas MAX_NUM tercapai untuk {prefix}")
                    break

                kelas = f"{prefix}{n:02d}".lower()
                print(f"Scraping {kelas} ...")

                rows = scrape_once(page, kelas)

                # sekali retry cepat jika kosong (opsional)
                if not rows and RETRY_ON_EMPTY > 0:
                    # “hard refresh” singkat: blank → balik
                    page.goto("about:blank")
                    rows = scrape_once(page, kelas)

                if not rows:
                    print(f"Kosong di {kelas} → stop prefix {prefix}")
                    break  # langsung lanjut ke prefix berikutnya

                all_rows.extend(rows)
                n += 1

            context.close()
        browser.close()

    cols = ["input_kelas","kelas","hari","mata_kuliah","waktu","ruang","dosen","berlaku_mulai"]
    if all_rows:
        df = pd.DataFrame(all_rows)[cols].drop_duplicates(subset=["kelas","hari","mata_kuliah","waktu","ruang","dosen"])
    else:
        df = pd.DataFrame(columns=cols)
    df.to_csv(OUT_CSV, index=False, encoding="utf-8")
    print(f"Tersimpan: {OUT_CSV} ({len(df)} baris)")

if __name__ == "__main__":
    run()
