import os
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import requests
from urllib.parse import urljoin, urlparse

def download_manga_debug():
    page_url = os.getenv("MANGA_URL", "https://onepiecepower.com/manga8/onepiece/volumi/reader/1176")
    output_folder = "img"

    print("=" * 60)
    print(f"🚀 URL: {page_url}")
    print("=" * 60)

    options = Options()
    # === PER IL DEBUG IN LOCALE METTI False ===
    options.add_argument("--headless=new")          # <--- Cambia in False per test locale
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )

    try:
        print("🌐 Caricamento pagina...")
        driver.get(page_url)
        time.sleep(4)

        print(f"📄 Titolo pagina: {driver.title}")
        print(f"🔗 URL attuale: {driver.current_url}")

        # Attesa lunga per immagini
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "img"))
            )
            print("✅ Almeno un <img> trovato nel DOM")
        except:
            print("⚠️ Nessun <img> trovato dopo 15 secondi")

        # Scroll multiplo per lazy loading
        for i in range(4):
            driver.execute_script("window.scrollBy(0, 800);")
            time.sleep(1.5)
            print(f"   → Scroll {i+1}/4 completato")

        time.sleep(3)

        # === PROVA 1: Tutti gli img ===
        all_imgs = driver.find_elements(By.TAG_NAME, "img")
        print(f"\n🔍 Trovati {len(all_imgs)} tag <img> totali")

        image_urls = []
        for img in all_imgs:
            src = img.get_attribute("src") or img.get_attribute("data-src") or img.get_attribute("data-lazy-src")
            if src and src.startswith("http"):
                full = urljoin(page_url, src)
                if "logo" not in full.lower() and "icon" not in full.lower():
                    if full not in image_urls:
                        image_urls.append(full)

        print(f"📸 Immagini candidate dopo filtro: {len(image_urls)}")

        if image_urls:
            print("Prime 5 immagini trovate:")
            for u in image_urls[:5]:
                print(f"   - {u}")

        # === PROVA 2: Cerca dentro contenitori tipici manga ===
        containers = driver.find_elements(By.CSS_SELECTOR, 
            "div[class*='reader'], div[class*='page'], div[class*='manga'], div[class*='swiper'], #reader")
        print(f"\n📦 Trovati {len(containers)} possibili contenitori reader")

        for container in containers:
            imgs_in_container = container.find_elements(By.TAG_NAME, "img")
            print(f"   → Contenitore con {len(imgs_in_container)} immagini")

        if not image_urls:
            print("\n❌ NESSUNA IMMAGINE TROVATA. Il sito probabilmente blocca Selenium o usa un sistema particolare.")
            print("   Prova ad aprire la pagina manualmente e dimmi che classi ha il div dell'immagine centrale.")

        # Salva le immagini (stesso codice di prima)
        os.makedirs(output_folder, exist_ok=True)
        headers = {"User-Agent": "Mozilla/5.0", "Referer": page_url}

        saved = 0
        for i, img_url in enumerate(image_urls, 1):
            try:
                r = requests.get(img_url, headers=headers, timeout=20)
                if r.status_code == 200 and len(r.content) > 5000:
                    ext = os.path.splitext(urlparse(img_url).path)[1] or ".jpg"
                    filename = os.path.join(output_folder, f"pagina_{i:03d}{ext}")
                    with open(filename, "wb") as f:
                        f.write(r.content)
                    saved += 1
            except:
                pass

        print(f"\n✅ Immagini salvate: {saved}")

    except Exception as e:
        print(f"❌ ERRORE: {e}")
    finally:
        driver.quit()


if __name__ == "__main__":
    download_manga_debug()
