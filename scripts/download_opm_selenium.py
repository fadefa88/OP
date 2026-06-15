from seleniumbase import Driver
import requests
import os
import time
from tqdm import tqdm
from urllib.parse import urlparse

URL = os.getenv("OPM_URL", "https://onepiecepower.com/manga8/one-punch-man/reader/001")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "opm_chapter_001")
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

def download_image(url, filename):
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code == 200 and len(r.content) > 3000:
            with open(filename, "wb") as f:
                f.write(r.content)
            return True
    except Exception as exc:
        print(f"Errore download {url}: {exc}")
    return False

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"URL: {URL}")
    print(f"Output dir: {OUTPUT_DIR}")
    print(f"Headless: {HEADLESS}")

    driver = Driver(
        browser="chrome",
        headless=HEADLESS,
    )

    try:
        driver.get(URL)
        print("Pagina caricata. Aspetto immagini...")
        time.sleep(10)

        images = driver.execute_script("""
            const urls = new Set();
            document.querySelectorAll('img').forEach(img => {
                ['src', 'data-src', 'data-lazy-src', 'data-original'].forEach(attr => {
                    const val = img.getAttribute(attr);
                    if (val && val.startsWith('http')) urls.add(val);
                });
            });
            return Array.from(urls);
        """)

        manga_images = [
            u for u in images
            if any(x in u.lower() for x in ['.jpg', '.jpeg', '.webp', '.png'])
            and 'logo' not in u.lower()
            and 'icon' not in u.lower()
            and 'avatar' not in u.lower()
        ]

        print(f"Trovate {len(manga_images)} immagini candidate.")

        if not manga_images:
            print("Nessuna immagine trovata.")
            return

        def get_page_num(url):
            try:
                name = urlparse(url).path.split('/')[-1]
                num = ''.join(filter(str.isdigit, name))
                return int(num) if num else 9999
            except Exception:
                return 9999

        manga_images.sort(key=get_page_num)

        for i, img_url in enumerate(tqdm(manga_images, desc="Scaricamento"), 1):
            ext = urlparse(img_url).path.split('.')[-1].split('?')[0].lower()
            if ext not in ["jpg", "jpeg", "webp", "png"]:
                ext = "jpg"

            filename = os.path.join(OUTPUT_DIR, f"page_{i:03d}.{ext}")

            if download_image(img_url, filename):
                print(f"Salvata: {filename}")
            else:
                print(f"Errore su: {img_url}")

        print(f"Fatto. Immagini salvate in: {os.path.abspath(OUTPUT_DIR)}")

    finally:
        driver.quit()

if __name__ == "__main__":
    main()
