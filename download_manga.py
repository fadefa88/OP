import os
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import requests
import time
from urllib.parse import urljoin, urlparse

def download_manga_selenium():
    page_url = os.getenv("MANGA_URL", "https://onepiecepower.com/manga8/onepiece/volumi/reader/1176")
    output_folder = "img"   # Cartella dentro il repo

    print(f"🚀 Avvio download da: {page_url}")

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )

    try:
        driver.get(page_url)
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "img")))
        time.sleep(3)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)

        img_elements = driver.find_elements(By.TAG_NAME, "img")
        image_urls = []

        for img in img_elements:
            src = img.get_attribute("src") or img.get_attribute("data-src")
            if src and src.startswith("http"):
                full_url = urljoin(page_url, src)
                if not any(x in full_url.lower() for x in ["logo", "icon", "banner", "thumb"]):
                    if full_url not in image_urls:
                        image_urls.append(full_url)

        print(f"📸 Trovate {len(image_urls)} immagini")

        os.makedirs(output_folder, exist_ok=True)

        headers = {"User-Agent": "Mozilla/5.0", "Referer": page_url}

        for i, img_url in enumerate(image_urls, 1):
            try:
                r = requests.get(img_url, headers=headers, timeout=30)
                if r.status_code == 200 and len(r.content) > 5000:
                    ext = os.path.splitext(urlparse(img_url).path)[1] or ".jpg"
                    filename = os.path.join(output_folder, f"pagina_{i:03d}{ext}")
                    with open(filename, "wb") as f:
                        f.write(r.content)
                    print(f"✅ Salvata: {filename}")
            except Exception as e:
                print(f"Errore su {img_url}: {e}")
            time.sleep(0.4)

        print("🎉 Download completato!")

    finally:
        driver.quit()


if __name__ == "__main__":
    download_manga_selenium()
