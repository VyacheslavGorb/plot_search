import os
import json
import time
import re
import requests
from pathlib import Path
from pyproj import Transformer
from shapely import wkt
from shapely.geometry import Polygon
from shapely.ops import transform
from tenacity import retry, wait_fixed, stop_after_attempt, retry_if_exception_type

PARSED_DIR = Path("data/parsed")
GEOCODED_DIR = Path("data/geocoded")
GEOCODED_DIR.mkdir(parents=True, exist_ok=True)

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
        # ULDK sometimes returns 'SRID=4326;POLYGON(...)' or 'SRID=2180;POLYGON(...)'
        if wkt_str.startswith("SRID="):
            wkt_str = wkt_str.split(";", 1)[1]
            
        geom = wkt.loads(wkt_str)
        if not isinstance(geom, Polygon):
            return None
            
        # Project from WGS84 to PUWG 1992 (meters)
        geom_projected = transform(transformer.transform, geom)
        return geom_projected.area
    except Exception as e:
        print(f"    Warning: Failed to calculate area: {e}")
        return None

def validate_area(calculated_area, declared_area):
    if not declared_area or not calculated_area:
        return False
    # +/- 25% tolerance
    tolerance = 0.25 * declared_area
    return abs(calculated_area - declared_area) <= tolerance

def clean_parcel_number(parcel_str):
    if not parcel_str:
        return None
    parcel_str = str(parcel_str).strip()
    # If it looks like a full TERYT ID, just return it as is
    if re.match(r'^\d{6}_\d\.\d{4}\.', parcel_str):
        return parcel_str
        
    # Remove words like 'lub', ranges with '-', and take the first item if comma separated
    cleaned = parcel_str.split(',')[0].split('lub')[0].split('-')[0].split('–')[0].strip()
    return cleaned if cleaned else None

def fetch_by_id(teryt_id):
    params = {
        "request": "GetParcelById",
        "id": teryt_id,
        "result": "teryt,geom_wkt",
        "srid": "4326"
    }
    lines = client.request(params)
    if len(lines) > 1 and lines[0] == '0':
        parts = lines[1].split('|')
        if len(parts) == 2:
            return {"teryt": parts[0], "geom_wkt": parts[1]}
    return None

def fetch_exact(lat, lon):
    params = {
        "request": "GetParcelByXY",
        "xy": f"{lon},{lat},4326",
        "result": "teryt,geom_wkt",
        "srid": "4326"
    }
    lines = client.request(params)
    if len(lines) > 1 and lines[0] == '0':
        parts = lines[1].split('|')
        if len(parts) == 2:
            return {"teryt": parts[0], "geom_wkt": parts[1]}
    return None

def fetch_hierarchy(lat, lon):
    params = {
        "request": "GetParcelByXY",
        "xy": f"{lon},{lat},4326",
        "result": "voivodeship,county,commune,region"
    }
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
    # format: voivodeship,county,commune,region,parcel
    id_str = f"{hierarchy['voivodeship']},{hierarchy['county']},{hierarchy['commune']},{hierarchy['region']},{parcel_number}"
    params = {
        "request": "GetParcelByNr",
        "id": id_str,
        "result": "teryt,geom_wkt",
        "srid": "4326"
    }
    lines = client.request(params)
    if len(lines) > 1 and lines[0] == '0':
        parts = lines[1].split('|')
        if len(parts) == 2:
            return {"teryt": parts[0], "geom_wkt": parts[1]}
    return None

def main():
    if not PARSED_DIR.exists():
        print("Parsed directory not found.")
        return

    json_files = list(PARSED_DIR.glob("*.json"))
    print(f"Found {len(json_files)} parsed listings. Starting geocoding...")

    for idx, file_path in enumerate(json_files):
        print(f"\n--- [{idx+1}/{len(json_files)}] Processing {file_path.name} ---")
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        out_path = GEOCODED_DIR / file_path.name
        if out_path.exists():
            print("Already geocoded, skipping.")
            continue

        lat = data.get("location", {}).get("latitude")
        lon = data.get("location", {}).get("longitude")
        is_exact = data.get("is_exact_location", False)
        declared_area = data.get("area")
        parcel_number = data.get("parcel_number")

        success = False
        teryt = None
        geom_wkt = None
        hierarchy = None
        is_unsubdivided = None

        if lat and lon:
            # 1. Try exact location
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
                        if is_unsubdivided:
                            print(f"  ✓ Exact location parcel found but area mismatch (Unsubdivided). Declared: {declared_area}, Calculated: {calc_area}")
                        else:
                            print(f"  ✓ Exact location validation passed (Diff: {abs(calc_area - declared_area):.1f} sqm).")
                    else:
                        print("  ✓ Exact location parcel found but could not calculate area.")
                else:
                    print("  ✗ No parcel found at exact location.")

            # 2. Try fallback if exact failed or wasn't exact
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
                            if is_unsubdivided:
                                print(f"  ✓ TERYT ID parcel found but area mismatch (Unsubdivided). Declared: {declared_area}, Calculated: {calc_area}")
                            else:
                                print(f"  ✓ TERYT ID validation passed (Diff: {abs(calc_area - declared_area):.1f} sqm).")
                        else:
                            print("  ✓ TERYT ID parcel found but could not calculate area.")
                    else:
                        print(f"  ✗ Failed to find parcel by ID: {cleaned_parcel}")
                else:
                    print(f"  Attempting fallback fetch (GetParcelByNr) using approximate location with parcel {cleaned_parcel}...")
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
                                if is_unsubdivided:
                                    print(f"  ✓ Fallback parcel found but area mismatch (Unsubdivided). Declared: {declared_area}, Calculated: {calc_area}")
                                else:
                                    print(f"  ✓ Fallback validation passed (Diff: {abs(calc_area - declared_area):.1f} sqm).")
                            else:
                                print("  ✓ Fallback parcel found but could not calculate area.")
                        else:
                            print(f"  ✗ Failed to find parcel by number: {cleaned_parcel}")
                    else:
                        print("  ✗ Failed to resolve geographic hierarchy for fallback.")
        else:
            print("  ✗ No coordinates available.")

        if not success:
            print("  ! Geocoding unsuccessful.")

        # Update JSON
        data["geocoding_successful"] = success
        data["teryt"] = teryt
        data["polygon_wkt"] = geom_wkt
        data["is_unsubdivided"] = is_unsubdivided
        
        # Save hierarchy if fetched during fallback, else try to fetch it just to save it
        if not success and lat and lon and not hierarchy:
            hierarchy = fetch_hierarchy(lat, lon)
        
        data["location_hierarchy"] = hierarchy

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    print("\nGeocoding pipeline complete!")

if __name__ == "__main__":
    main()
