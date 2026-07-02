import requests
import os
from shapely.wkt import loads
from shapely.geometry import box
from sqlalchemy.orm import Session
from database import get_db, GeocodedParcel
import warnings

# Suppress insecure request warnings for WMS
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

KIUT_URL = "https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaUzbrojeniaTerenu"

def get_kiut_map_for_parcel(db: Session, parcel_id: str, output_dir: str = "data/kiut_maps") -> str:
    """
    Downloads a KIUT (underground utilities) WMS map for a given parcel.
    Returns the path to the saved PNG image.
    """
    parcel = db.query(GeocodedParcel).filter(GeocodedParcel.id == parcel_id).first()
    if not parcel or not parcel.polygon_wkt:
        raise ValueError(f"Parcel {parcel_id} not found or has no geometry.")
        
    # Load geometry. Ensure it is in EPSG:2180 (PUWG 1992) for the BBOX
    # Note: If it's stored as SRID=4326; in the DB, we need to transform it.
    wkt = parcel.polygon_wkt
    if wkt.startswith("SRID="):
        # We need it in 2180. For this python script, we can query PostGIS to transform it,
        # or use pyproj. Let's ask the DB to give it to us in 2180.
        from sqlalchemy import text
        geom_query = text(f"SELECT ST_AsText(ST_Transform(ST_GeomFromEWKT('{wkt}'), 2180))")
        wkt_2180 = db.execute(geom_query).scalar()
        geom = loads(wkt_2180)
    else:
        geom = loads(wkt)
        
    # Get bounding box and buffer it by 50 meters to see surrounding utilities
    minx, miny, maxx, maxy = geom.bounds
    buffer_m = 50
    bbox_str = f"{miny-buffer_m},{minx-buffer_m},{maxy+buffer_m},{maxx+buffer_m}"
    
    params = {
        "SERVICE": "WMS",
        "REQUEST": "GetMap",
        "VERSION": "1.3.0",
        "LAYERS": "przewod_wodociagowy,przewod_kanalizacyjny,przewod_gazowy,przewod_elektroenergetyczny,przewod_telekomunikacyjny", 
        "STYLES": "",
        "CRS": "EPSG:2180",
        "BBOX": bbox_str, 
        "WIDTH": "800",
        "HEIGHT": "800",
        "FORMAT": "image/png",
        "TRANSPARENT": "TRUE"
    }
    
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{parcel_id}_utilities.png")
    
    response = requests.get(KIUT_URL, params=params, verify=False, timeout=15)
    response.raise_for_status()
    
    if 'image' not in response.headers.get('content-type', ''):
        raise RuntimeError("KIUT did not return an image. It might have returned an XML error.")
        
    with open(output_path, 'wb') as f:
        f.write(response.content)
        
    return output_path

def analyze_kiut_utilities(image_path: str) -> dict:
    """
    Analyzes the downloaded PNG map using computer vision/color matching
    to determine which utilities are present inside the bounding box.
    """
    from PIL import Image
    import numpy as np
    
    img = Image.open(image_path).convert('RGBA')
    arr = np.array(img)
    
    pixels = arr.reshape(-1, 4)
    # Keep only non-transparent pixels (alpha > 0)
    opaque_pixels = pixels[pixels[:, 3] > 0]
    
    # Very robust color thresholding for standard GESUT utility colors
    # Water = Blue
    has_water = np.any((opaque_pixels[:, 0] < 50) & (opaque_pixels[:, 1] < 50) & (opaque_pixels[:, 2] > 200))
    
    # Sewage = Brown/Dark Orange (e.g. 128, 51, 0)
    has_sewage = np.any((opaque_pixels[:, 0] > 100) & (opaque_pixels[:, 0] < 160) & (opaque_pixels[:, 1] > 30) & (opaque_pixels[:, 1] < 80) & (opaque_pixels[:, 2] < 50))
    
    # Gas = Yellow (e.g. 191, 191, 0)
    has_gas = np.any((opaque_pixels[:, 0] > 150) & (opaque_pixels[:, 1] > 150) & (opaque_pixels[:, 2] < 50))
    
    # Electricity = Red (e.g. 255, 0, 0)
    has_electricity = np.any((opaque_pixels[:, 0] > 200) & (opaque_pixels[:, 1] < 50) & (opaque_pixels[:, 2] < 50))
    
    # Telecom = Orange (e.g. 255, 145, 0)
    has_telecom = np.any((opaque_pixels[:, 0] > 200) & (opaque_pixels[:, 1] > 100) & (opaque_pixels[:, 1] < 180) & (opaque_pixels[:, 2] < 50))
    
    return {
        "has_water": bool(has_water),
        "has_sewage": bool(has_sewage),
        "has_gas": bool(has_gas),
        "has_electricity": bool(has_electricity),
        "has_telecom": bool(has_telecom),
    }

def get_kiut_utilities(db: Session, parcel_id: str) -> dict:
    """
    Orchestrator: Downloads the WMS map and analyzes its colors.
    """
    try:
        path = get_kiut_map_for_parcel(db, parcel_id)
        utilities = analyze_kiut_utilities(path)
        return utilities
    except Exception as e:
        print(f"Failed to fetch/analyze KIUT for {parcel_id}: {e}")
        return {}

if __name__ == "__main__":
    db = next(get_db())
    test_parcel = db.query(GeocodedParcel).first()
    if test_parcel:
        print(f"Downloading KIUT map for {test_parcel.id}...")
        path = get_kiut_map_for_parcel(db, test_parcel.id)
        print(f"Saved KIUT map to {path}")
        utils = analyze_kiut_utilities(path)
        print(f"Utilities found: {utils}")
    else:
        print("No geocoded parcels found to test.")
