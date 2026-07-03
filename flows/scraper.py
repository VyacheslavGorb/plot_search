import os
import re
import json
import time
from prefect import flow, task
from playwright.sync_api import sync_playwright
from database import SessionLocal, RawListing

SEARCH_URL = "https://www.otodom.pl/pl/wyniki/sprzedaz/dzialka/mazowieckie/warszawa/warszawa/warszawa?ownerTypeSingleSelect=ALL&distanceRadius=75&priceMax=650000&areaMin=1000&areaMax=2000&by=LATEST&direction=DESC"
CHROME_CDP = "http://localhost:9222"

@task(retries=3, retry_delay_seconds=5)
def save_raw_listing(payload: dict) -> bool:
    """Saves a listing to PostgreSQL. Returns True if saved, False if already exists."""
    db = SessionLocal()
    try:
        exists = db.query(RawListing.id).filter(RawListing.source_url == payload['source_url']).first()
        if exists:
            return False

        listing = RawListing(
            id=payload['id'],
            source_url=payload['source_url'],
            title=payload['title'],
            description=payload['description'],
            raw_characteristics=payload['raw_characteristics'],
            price=payload['price'],
            area=payload['area'],
            location_lat=payload['location'].get('latitude') if payload['location'] else None,
            location_lon=payload['location'].get('longitude') if payload['location'] else None,
            is_exact_location=payload['is_exact_location'],
            images=payload['images'],
            advertiser_type=payload['advertiser_type']
        )
        db.add(listing)
        db.commit()
        return True
    finally:
        db.close()

class ChromeManager:
    def __init__(self):
        import subprocess, time
        print("Starting Chrome...")
        chrome_cmd = [
            "google-chrome",
            "--remote-debugging-port=9222",
            "--user-data-dir=/tmp/chrome-debug"
        ]
        self.process = subprocess.Popen(chrome_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(3) # Wait for Chrome to initialize
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        print("Stopping Chrome...")
        try:
            self.process.terminate()
            self.process.wait(timeout=5)
        except Exception as e:
            print(f"Error stopping Chrome: {e}")

@flow(name="Scrape Otodom Listings")
def scrape_flow(mode="incremental"):
    print(f"Starting scraper in {mode} mode.")
    
    with ChromeManager(), sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(CHROME_CDP)
        except Exception as e:
            print(f"Error connecting to Chrome: {e}")
            return

        context = browser.contexts[0]
        page = context.pages[0] if context.pages else context.new_page()
        
        print(f"Navigating to search URL: {SEARCH_URL}")
        page.goto(SEARCH_URL, timeout=60000)
        page.wait_for_timeout(3000)
        
        # Handle cookie consent if visible
        try:
            accept_button = page.locator('button:has-text("Akceptuj wszystkie")')
            if accept_button.is_visible(timeout=2000):
                print("Clicking cookie consent...")
                accept_button.click()
                page.wait_for_timeout(1000)
        except Exception:
            pass
        
        page_num = 1
        max_pages = float('inf')
        total_scraped = 0
        all_active_urls = set()
        
        while page_num <= max_pages:
            print(f"Scraping search page {page_num}...")
            
            hrefs = page.evaluate("() => Array.from(document.querySelectorAll('a[href*=\"/pl/oferta/\"]')).map(a => a.getAttribute('href'))")
            for href in hrefs:
                if href and href.startswith('/pl/oferta/'):
                    full_url = f"https://www.otodom.pl{href}"
                    all_active_urls.add(full_url)
            
            next_button = page.locator('button[aria-label="Go to next Page"]')
            if next_button.is_visible() and not next_button.is_disabled():
                print("Navigating to next search page...")
                next_button.click()
                page.wait_for_timeout(3000)
                page_num += 1
            else:
                break
                
        if not all_active_urls:
            print("No active URLs found! Stopping scraper (possible captcha/block).")
            return
            
        print(f"Found {len(all_active_urls)} active URLs across {page_num} pages.")
        
        db = SessionLocal()
        try:
            from database import StatusEnum
            inactive_count = 0
            for raw in db.query(RawListing).filter(~RawListing.source_url.in_(list(all_active_urls))).all():
                if raw.status != StatusEnum.INACTIVE:
                    raw.status = StatusEnum.INACTIVE
                    if raw.parsed_listing:
                        raw.parsed_listing.status = StatusEnum.INACTIVE
                    inactive_count += 1
            db.commit()
            print(f"Marked {inactive_count} older listings as INACTIVE (no longer found on search pages).")
        except Exception as e:
            print(f"Error marking INACTIVE: {e}")
        finally:
            db.close()
            
        for index, url in enumerate(all_active_urls):
            db = SessionLocal()
            url_exists = db.query(RawListing.id).filter(RawListing.source_url == url).first()
            db.close()
            
            if url_exists and mode == "incremental":
                # print(f"  [{index+1}/{len(all_active_urls)}] Skipping known URL: {url}")
                continue
            elif url_exists:
                print(f"  [{index+1}/{len(all_active_urls)}] Already exists, but running in FULL mode. Skipping parsing.")
                continue

            print(f"\n[{index+1}/{len(all_active_urls)}] Navigating to: {url}")
            try:
                detail_page = context.new_page()
                detail_page.goto(url, timeout=30000)
                detail_page.wait_for_timeout(2000)
                
                listing_id = None
                id_match = re.search(r'-ID([A-Za-z0-9]+)$', url)
                if id_match:
                    listing_id = id_match.group(1)
                else:
                    listing_id = f"unknown_{index}_{int(time.time())}"
                
                data = detail_page.evaluate("""
                    () => {
                        const nextDataEl = document.getElementById('__NEXT_DATA__');
                        if (nextDataEl) {
                            try {
                                return JSON.parse(nextDataEl.innerText);
                            } catch(e) {
                                return null;
                            }
                        }
                        return null;
                    }
                """)
                
                ad = data.get('props', {}).get('pageProps', {}).get('ad', {}) if data else {}
                html_description = ad.get('description', '')
                clean_description = re.sub(r'<[^>]+>', ' ', html_description).strip() if html_description else ''
                
                if not clean_description:
                    clean_description = detail_page.evaluate("() => { const mainEl = document.querySelector('main') || document.body; return mainEl ? mainEl.innerText.trim() : ''; }")
                    
                raw_characteristics = detail_page.evaluate("""
                    () => {
                        const headers = Array.from(document.querySelectorAll('h2, h3, h4, span, div')).filter(e => e.innerText && e.innerText.trim() === 'Działka na sprzedaż');
                        for (const h of headers) {
                            if (h.parentElement && h.parentElement.innerText.includes('Powierzchnia:')) {
                                return h.parentElement.innerText;
                            }
                        }
                        return "";
                    }
                """)
                
                owner = ad.get('owner', {})
                advertiser_type = owner.get('type') or ad.get('advertiserType', 'unknown')
                map_details = ad.get('location', {}).get('mapDetails', {})
                is_exact_location = map_details.get('radius') == 0
                
                price = None
                area = None
                for c in ad.get('characteristics', []):
                    if c.get('key') == 'price':
                        price = c.get('value')
                    elif c.get('key') == 'm':
                        area = c.get('value')
                
                payload = {
                    "id": listing_id,
                    "source_url": url,
                    "title": ad.get('title', ''),
                    "description": clean_description,
                    "price": price,
                    "area": area,
                    "location": ad.get('location', {}).get('coordinates', {}),
                    "is_exact_location": is_exact_location,
                    "advertiser_type": advertiser_type,
                    "raw_characteristics": raw_characteristics,
                    "images": [img.get('large') for img in ad.get('images', []) if img.get('large')]
                }
                
                if not payload["images"]:
                    payload["images"] = detail_page.evaluate("""
                        () => {
                            const imgs = [];
                            document.querySelectorAll('img').forEach(img => {
                                const src = img.src || '';
                                if (src && (img.alt.includes('Pełny obrazek:') || src.includes('olxcdn.com/v1/files')) && !img.closest('[data-sentry-component="RecommendedAdItem"]')) {
                                    if (!imgs.includes(src)) imgs.push(src.replace(/;s=\\d+x\\d+;/, ';s=1280x1024;'));
                                }
                            });
                            return imgs;
                        }
                    """)
                
                saved = save_raw_listing(payload)
                if saved:
                    print(f"  ✓ Saved to DB: {listing_id}")
                    total_scraped += 1
                
            except Exception as e:
                print(f"  ✗ Error scraping {url}: {e}")
            finally:
                try:
                    detail_page.close()
                except:
                    pass
        
        print(f"\nScraping flow completed! Total new listings scraped: {total_scraped}")

if __name__ == "__main__":
    scrape_flow()
