import time
import re
import requests
from prefect import flow, task
from pyproj import Transformer
from shapely import wkt
from shapely.geometry import Polygon
from shapely.ops import transform
from tenacity import retry, wait_fixed, stop_after_attempt, retry_if_exception_type

from database import SessionLocal, RawListing, ParsedListing, GeocodedParcel, StatusEnum

class ULDKClient:
    def __init__(self):
        self.session = requests.Session()
        self.last_request_time = 0
        self.min_delay = 0.5  # 500ms

    def _wait_for_rate_limit(self):
        now = time.time()
        elapsed = now - self.last_request_time
        if elapsed < self.min_delay:
            time.sleep(self.min_delay - elapsed)
        self.last_request_time = time.time()

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(1), retry=retry_if_exception_type(requests.RequestException))
    def request(self, params):
        self._wait_for_rate_limit()
        url = "https://uldk.gugik.gov.pl/"
        response = self.session.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.text.strip().split('\n')

client = ULDKClient()
transformer = Transformer.from_crs("epsg:4326", "epsg:2180", always_xy=True)

def calculate_area(wkt_str):
    try:
        if wkt_str.startswith("SRID="):
            wkt_str = wkt_str.split(";", 1)[1]
            
        geom = wkt.loads(wkt_str)
        if not isinstance(geom, Polygon):
            return None
            
        geom_projected = transform(transformer.transform, geom)
        return geom_projected.area
    except Exception as e:
        print(f"    Warning: Failed to calculate area: {e}")
        return None

def validate_area(calculated_area, declared_area):
    if not declared_area or not calculated_area:
        return False
    tolerance = 0.25 * declared_area
    return abs(calculated_area - declared_area) <= tolerance

def clean_parcel_number(parcel_str):
    if not parcel_str:
        return None
    parcel_str = str(parcel_str).strip()
    if re.match(r'^\d{6}_\d\.\d{4}\.', parcel_str):
        return parcel_str
        
    cleaned = parcel_str.split(',')[0].split('lub')[0].split('-')[0].split('–')[0].strip()
    return cleaned if cleaned else None

def fetch_by_id(teryt_id):
    params = {"request": "GetParcelById", "id": teryt_id, "result": "teryt,geom_wkt", "srid": "4326"}
    lines = client.request(params)
    if len(lines) > 1 and lines[0] == '0':
        parts = lines[1].split('|')
        if len(parts) == 2:
            return {"teryt": parts[0], "geom_wkt": parts[1]}
    return None

def fetch_exact(lat, lon):
    params = {"request": "GetParcelByXY", "xy": f"{lon},{lat},4326", "result": "teryt,geom_wkt", "srid": "4326"}
    lines = client.request(params)
    if len(lines) > 1 and lines[0] == '0':
        parts = lines[1].split('|')
        if len(parts) == 2:
            return {"teryt": parts[0], "geom_wkt": parts[1]}
    return None

def fetch_hierarchy(lat, lon):
    params = {"request": "GetParcelByXY", "xy": f"{lon},{lat},4326", "result": "voivodeship,county,commune,region"}
    lines = client.request(params)
    if len(lines) > 1 and lines[0] == '0':
        parts = lines[1].split('|')
        if len(parts) == 4:
            return {
                "voivodeship": parts[0],
                "county": parts[1],
                "commune": parts[2],
                "region": parts[3]
            }
    return None

def fetch_by_nr(hierarchy, parcel_number):
    id_str = f"{hierarchy['voivodeship']},{hierarchy['county']},{hierarchy['commune']},{hierarchy['region']},{parcel_number}"
    params = {"request": "GetParcelByNr", "id": id_str, "result": "teryt,geom_wkt", "srid": "4326"}
    lines = client.request(params)
    if len(lines) > 1 and lines[0] == '0':
        parts = lines[1].split('|')
        if len(parts) == 2:
            return {"teryt": parts[0], "geom_wkt": parts[1]}
    return None

@task(retries=3, retry_delay_seconds=5)
def process_listing(listing_id: str, lat: float, lon: float, is_exact: bool, declared_area: float, parcel_number: str):
    success = False
    teryt = None
    geom_wkt = None
    hierarchy = None
    is_unsubdivided = None

    if lat and lon:
        if is_exact:
            print("  Attempting fetch by exact location (GetParcelByXY)...")
            exact_res = fetch_exact(lat, lon)
            if exact_res:
                teryt = exact_res["teryt"]
                geom_wkt = exact_res["geom_wkt"]
                success = True
                calc_area = calculate_area(geom_wkt)
                if calc_area:
                    is_unsubdivided = not validate_area(calc_area, declared_area)
                    print(f"  ✓ Exact location parcel found (Unsubdivided: {is_unsubdivided}).")
                else:
                    print("  ✓ Exact location parcel found but could not calculate area.")
            else:
                print("  ✗ No parcel found at exact location.")

        if not success and parcel_number:
            cleaned_parcel = clean_parcel_number(parcel_number)
            if not cleaned_parcel:
                print(f"  ✗ Failed to extract clean parcel number from: {parcel_number}")
            elif re.match(r'^\d{6}_\d\.\d{4}\.', cleaned_parcel):
                print(f"  Attempting fetch by TERYT ID directly: {cleaned_parcel}...")
                id_res = fetch_by_id(cleaned_parcel)
                if id_res:
                    teryt = id_res["teryt"]
                    geom_wkt = id_res["geom_wkt"]
                    success = True
                    calc_area = calculate_area(geom_wkt)
                    if calc_area:
                        is_unsubdivided = not validate_area(calc_area, declared_area)
                        print(f"  ✓ TERYT ID parcel found (Unsubdivided: {is_unsubdivided}).")
                else:
                    print(f"  ✗ Failed to find parcel by ID: {cleaned_parcel}")
            else:
                print(f"  Attempting fallback fetch using hierarchy with parcel {cleaned_parcel}...")
                hierarchy = fetch_hierarchy(lat, lon)
                if hierarchy:
                    nr_res = fetch_by_nr(hierarchy, cleaned_parcel)
                    if nr_res:
                        teryt = nr_res["teryt"]
                        geom_wkt = nr_res["geom_wkt"]
                        success = True
                        calc_area = calculate_area(geom_wkt)
                        if calc_area:
                            is_unsubdivided = not validate_area(calc_area, declared_area)
                            print(f"  ✓ Fallback parcel found (Unsubdivided: {is_unsubdivided}).")
                    else:
                        print(f"  ✗ Failed to find parcel by number: {cleaned_parcel}")

    if not success and lat and lon and not hierarchy:
        hierarchy = fetch_hierarchy(lat, lon)
        
    return {
        "success": success,
        "teryt": teryt,
        "geom_wkt": geom_wkt,
        "hierarchy": hierarchy,
        "is_unsubdivided": is_unsubdivided
    }

@flow(name="Geocode Parcels with ULDK")
def geocode_flow():
    db = SessionLocal()
    try:
        new_listings = db.query(ParsedListing, RawListing).join(RawListing).filter(ParsedListing.status == StatusEnum.NEW).all()
        print(f"Found {len(new_listings)} NEW parsed listings to geocode.")
        
        for idx, (parsed, raw) in enumerate(new_listings):
            print(f"\n--- [{idx+1}/{len(new_listings)}] Geocoding {parsed.id} ---")
            
            result = process_listing(
                listing_id=parsed.id,
                lat=raw.location_lat,
                lon=raw.location_lon,
                is_exact=raw.is_exact_location,
                declared_area=raw.area,
                parcel_number=parsed.parcel_number
            )
            
            if result["success"]:
                geocoded_record = GeocodedParcel(
                    id=parsed.id,
                    teryt=result["teryt"],
                    polygon_wkt=result["geom_wkt"],
                    is_unsubdivided=result["is_unsubdivided"],
                    location_hierarchy=result["hierarchy"]
                )
                db.add(geocoded_record)
                parsed.status = StatusEnum.GEOCODED
            else:
                parsed.status = StatusEnum.FAILED_GEOCODING
                
            db.commit()
            
    finally:
        db.close()

if __name__ == "__main__":
    geocode_flow()
