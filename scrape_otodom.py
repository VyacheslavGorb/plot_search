import os
import re
import json
import time
from playwright.sync_api import sync_playwright

SEARCH_URL = "https://www.otodom.pl/pl/wyniki/sprzedaz/dzialka/mazowieckie/warszawa/warszawa/warszawa?ownerTypeSingleSelect=ALL&distanceRadius=75&priceMax=650000&areaMin=1000&areaMax=2000&by=LATEST&direction=DESC"
CHROME_CDP = "http://localhost:9222"

def main():
    print(f"Connecting to Chrome running on {CHROME_CDP}...")
    
    with sync_playwright() as p:
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
        
        os.makedirs("data/raw", exist_ok=True)

        page_num = 1
        max_pages = float('inf')
        total_scraped = 0
        
        while page_num <= max_pages:
            print(f"Scraping search page {page_num}...")
            
            # Extract listing links
            listing_urls = []
            links = page.locator('a[href*="/pl/oferta/"]').all()
            for link in links:
                href = link.get_attribute('href')
                if href and href.startswith('/pl/oferta/'):
                    full_url = f"https://www.otodom.pl{href}"
                    if full_url not in listing_urls:
                        listing_urls.append(full_url)
            
            print(f"Found {len(listing_urls)} listings on page {page_num}. Beginning detail extraction...")
            
            for index, url in enumerate(listing_urls):
                print(f"\n[{index+1}/{len(listing_urls)}] Navigating to: {url}")
                try:
                    detail_page = context.new_page()
                    detail_page.goto(url, timeout=30000)
                    detail_page.wait_for_timeout(2000)
                    
                    # Extract listing ID
                    listing_id = None
                    id_match = re.search(r'-ID([A-Za-z0-9]+)$', url)
                    if id_match:
                        listing_id = id_match.group(1)
                    else:
                        listing_id = f"unknown_{index}_{int(time.time())}"
                    
                    # Extract plain text and images
                    # Extract __NEXT_DATA__ JSON blob containing all structured listing data
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
                    
                    # Extract ad details from the JSON blob
                    ad = data.get('props', {}).get('pageProps', {}).get('ad', {}) if data else {}
                    
                    # Clean up HTML description
                    html_description = ad.get('description', '')
                    clean_description = re.sub(r'<[^>]+>', ' ', html_description).strip() if html_description else ''
                    
                    # Fallback to extracting description via JS if __NEXT_DATA__ is missing or empty
                    if not clean_description:
                        clean_description = detail_page.evaluate("() => { const mainEl = document.querySelector('main') || document.body; return mainEl ? mainEl.innerText.trim() : ''; }")
                        
                    # Extract raw characteristics block from DOM
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
                    
                    # Prepare JSON payload
                    payload = {
                        "id": listing_id,
                        "source_url": url,
                        "scraped_at": time.strftime('%Y-%m-%d %H:%M:%S'),
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
                    
                    # Fallback for images if __NEXT_DATA__ parsing failed
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
                    
                    # Save parsed metadata to JSON
                    json_path = f"data/raw/{listing_id}.json"
                    with open(json_path, "w", encoding="utf-8") as f:
                        json.dump(payload, f, ensure_ascii=False, indent=2)
                    
                    print(f"  ✓ Saved plain text and {len(payload['images'])} image links to {json_path}")
                    total_scraped += 1
                    
                except Exception as e:
                    print(f"  ✗ Error scraping {url}: {e}")
                finally:
                    try:
                        detail_page.close()
                    except:
                        pass
            
            # Navigate to next page
            next_button = page.locator('button[aria-label="Go to next Page"]')
            if next_button.is_visible() and not next_button.is_disabled():
                print("Navigating to next search page...")
                next_button.click()
                page.wait_for_timeout(3000)
                page_num += 1
            else:
                break
        
        print(f"\nAll scraping operations completed! Total listings scraped: {total_scraped}")

if __name__ == "__main__":
    main()
