import os
import time
import undetected_chromedriver as uc
import requests
from urllib.parse import urljoin, urlparse

def download_manga():
    page_url = os.getenv("MANGA_URL", "https://onepiecepower.com/manga8/onepiece/volumi/reader/1176")
    output_folder = "img"

    print(f"🚀 URL: {page_url}")

    options = uc.ChromeOptions()
    options.add_argument("--headless=new")          # Metti False per test locale
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")

    driver = uc.Chrome(options=options)

    try:
        print("🌐 Caricamento pagina (con undetected)...")
        driver.get(page_url)
        time.sleep(6)   # Aspetta che Cloudflare risolva la challenge

        print(f"📄 Titolo: {driver.title}")

        if "just a moment" in driver.title.lower():
            print("❌ Ancora bloccato da Cloudflare. Provo ad aspettare di più...")
            time.sleep(8)

        # Scroll per caricare le immagini
        for i in range(5):
            driver.execute_script("window.scrollBy(0, 600);")
            time.sleep(1.2)

        time.sleep(3)

        # Prendi tutte le immagini
        imgs = driver.find_elements("tag name", "img")
        print(f"🔍 Trovati {len(imgs)} tag <img>")

        image_urls = []
        for img in imgs:
            src = img.get_attribute("src") or img.get_attribute("data-src")
            if src and src.startswith("http"):
                full = urljoin(page_url, src)
                if all(x not in full.lower() for x in ["logo", "icon", "banner", "cloudflare"]):
                    if full not in image_urls:
                        image_urls.append(full)

        print(f"📸 Immagini candidate: {len(image_urls)}")

        if not image_urls:
            print("❌ Ancora nessuna immagine trovata.")
            return

        # Scarica le immagini
        os.makedirs(output_folder, exist_ok=True)
        headers = {"User-Agent": "Mozilla/5.0", "Referer": page_url}

        saved = 0
        for i, url in enumerate(image_urls, 1):
            try:
                r = requests.get(url, headers=headers, timeout=25)
                if r.status_code == 200 and len(r.content) > 8000:
                    ext = os.path.splitext(urlparse(url).path)[1] or ".jpg"
                    filename = os.path.join(output_folder, f"pagina_{i:03d}{ext}")
                    with open(filename, "wb") as f:
                        f.write(r.content)
                    print(f"✅ Salvata: {filename}")
                    saved += 1
            except Exception as e:
                print(f"Errore: {e}")

        print(f"\n🎉 Completato! Immagini salvate: {saved}")

    except Exception as e:
        print(f"❌ Errore: {e}")
    finally:
        driver.quit()


if __name__ == "__main__":
    download_manga()
