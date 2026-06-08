import os
import re
import time
import hashlib
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote
import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

def safe_filename(url, content_type=""):
    parsed = urlparse(url)
    name = os.path.basename(unquote(parsed.path))
    if not name or "." not in name:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
        ext = ".jpg"
        if "png" in content_type: ext = ".png"
        elif "webp" in content_type: ext = ".webp"
        elif "gif" in content_type: ext = ".gif"
        name = f"image_{digest}{ext}"
    name = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
    if len(name) > 160:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
        stem, ext = os.path.splitext(name)
        name = f"{stem[:120]}_{digest}{ext}"
    return name

def extract_dom_images(driver, base_url):
    js = """
    const urls = new Set();
    function addUrl(value) {
        if (!value) return;
        value = value.trim();
        if (value.startsWith("data:") || value.startsWith("blob:") || value.startsWith("javascript:")) return;
        try { urls.add(new URL(value, document.baseURI).href); } catch(e) {}
    }
    const attrs = ["src","data-src","data-original","data-lazy-src","data-image","data-url","data-full","data-full-src"];
    document.querySelectorAll("img, source, picture, a, [style]").forEach(el => {
        attrs.forEach(attr => addUrl(el.getAttribute(attr)));
        const srcset = el.getAttribute("srcset");
        if (srcset) srcset.split(",").forEach(part => addUrl(part.trim().split(/\\s+/)[0]));
        const href = el.getAttribute("href");
        if (href && /\\.(jpg|jpeg|png|webp|gif|svg)(\\?|#|$)/i.test(href)) addUrl(href);
        const style = el.getAttribute("style");
        if (style) {
            const regex = /url\\(['"]?(.*?)['"]?\\)/g;
            let match;
            while ((match = regex.exec(style)) !== null) addUrl(match[1]);
        }
    });
    return Array.from(urls);
    """
    try:
        urls = driver.execute_script(js)
    except Exception as e:
        print(f"Errore JS: {e}")
        urls = []
    return sorted(set(urljoin(base_url, u) for u in urls))

def selenium_cookies_to_requests(driver, session):
    for cookie in driver.get_cookies():
        try:
            session.cookies.set(cookie["name"], cookie["value"], domain=cookie.get("domain"), path=cookie.get("path", "/"))
        except:
            pass

def download_images_debug():
    page_url = os.getenv("MANGA_URL", "https://onepiecepower.com/manga8/onepiece/volumi/reader/1176")
    output_folder = Path("img")
    debug_folder = Path("debug")
    output_folder.mkdir(exist_ok=True)
    debug_folder.mkdir(exist_ok=True)

    headless = os.getenv("HEADLESS", "1") == "1"
    print(f"URL: {page_url} | HEADLESS: {headless}")

    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1600")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    try:
        print("Caricamento pagina...")
        driver.get(page_url)
        time.sleep(6)
        print(f"Titolo: {driver.title}")

        # Screenshot e HTML iniziali
        driver.save_screenshot(str(debug_folder / "01_initial.png"))
        (debug_folder / "01_initial.html").write_text(driver.page_source, encoding="utf-8")

        # Scroll multiplo
        last_height = 0
        for i in range(12):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.3)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height: break
            last_height = new_height
            print(f"Scroll {i+1}/12")

        time.sleep(3)
        driver.save_screenshot(str(debug_folder / "02_after_scroll.png"))
        (debug_folder / "02_after_scroll.html").write_text(driver.page_source, encoding="utf-8")

        # Estrazione immagini con JS avanzato
        image_urls = extract_dom_images(driver, page_url)
        print(f"\nImmagini candidate trovate: {len(image_urls)}")
        for u in image_urls[:15]:
            print(f"  - {u}")

        (debug_folder / "image_urls.txt").write_text("\n".join(image_urls), encoding="utf-8")

        # Sessione requests con cookie di Selenium
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Referer": page_url,
            "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"
        })
        selenium_cookies_to_requests(driver, session)

        saved = 0
        for i, img_url in enumerate(image_urls, 1):
            try:
                r = session.get(img_url, timeout=25)
                content_type = r.headers.get("Content-Type", "")
                size = len(r.content)

                if r.status_code != 200 or not content_type.startswith("image/") or size < 5000:
                    continue

                filename = safe_filename(img_url, content_type)
                filepath = output_folder / f"{i:03d}_{filename}"
                filepath.write_bytes(r.content)
                saved += 1
                print(f"✅ Salvata: {filepath.name} ({size} bytes)")
            except Exception as e:
                print(f"Errore su {img_url}: {e}")

        print(f"\nTotale immagini salvate: {saved}")

    except Exception as e:
        print(f"ERRORE: {e}")
        driver.save_screenshot(str(debug_folder / "error.png"))
    finally:
        driver.quit()

if __name__ == "__main__":
    download_images_debug()
