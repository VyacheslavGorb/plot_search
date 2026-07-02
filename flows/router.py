import urllib.request
import urllib.parse
import json
import uuid
import datetime
from prefect import flow, task
from shapely import wkt
from sqlalchemy.orm import joinedload
from database import SessionLocal, ParsedListing, GeocodedParcel, RawListing, RouteEvaluation, StatusEnum

GRAPHQL_URL = "http://localhost:8080/otp/routers/default/index/graphql"

TARGETS = {
    "VARSO_TOWER": {"lat": 52.2275, "lon": 21.0003},
    "WARSAW_HUB": {"lat": 52.2285, "lon": 20.9840}
}

MODES = {
    "CAR_ONLY": "[{mode: CAR}]",
    "CAR_TRANSIT": "[{mode: CAR}, {mode: TRANSIT}, {mode: WALK}]",
    "BICYCLE_TRANSIT": "[{mode: BICYCLE}, {mode: TRANSIT}, {mode: WALK}]"
}

TIMES = {
    "time_0800_mins": "08:00:00",
    "time_1400_mins": "14:00:00",
    "time_1700_mins": "17:00:00"
}

# Use a fixed weekday in the future to ensure stable schedules
DATE_STR = "2026-06-25" # Thursday

def query_otp(origin_lat, origin_lon, dest_lat, dest_lon, mode_str, time_str):
    query = f"""
    {{
      plan(
        from: {{lat: {origin_lat}, lon: {origin_lon}}}
        to: {{lat: {dest_lat}, lon: {dest_lon}}}
        date: "{DATE_STR}"
        time: "{time_str}"
        transportModes: {mode_str}
      ) {{
        itineraries {{
          duration
        }}
      }}
    }}
    """
    
    req = urllib.request.Request(GRAPHQL_URL, data=json.dumps({'query': query}).encode('utf-8'))
    req.add_header('Content-Type', 'application/json')
    
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            if 'errors' in data:
                return None
            
            itins = data.get('data', {}).get('plan', {}).get('itineraries', [])
            if not itins:
                return None
                
            return itins[0]['duration'] / 60.0
    except Exception as e:
        print(f"OTP Request failed: {e}")
        return None

@task(retries=3, retry_delay_seconds=2)
def evaluate_parcel_routes(db_session, listing):
    # 1. Determine Origin
    origin_lat, origin_lon = None, None
    if listing.geocoded_parcel and listing.geocoded_parcel.polygon_wkt:
        try:
            wkt_str = listing.geocoded_parcel.polygon_wkt
            if wkt_str.startswith("SRID="):
                wkt_str = wkt_str.split(";", 1)[1]
            poly = wkt.loads(wkt_str)
            origin_lat = poly.centroid.y
            origin_lon = poly.centroid.x
        except Exception as e:
            print(f"Error parsing WKT for {listing.id}: {e}")
            
    if origin_lat is None or origin_lon is None:
        if listing.raw_listing.location_lat and listing.raw_listing.location_lon:
            origin_lat = listing.raw_listing.location_lat
            origin_lon = listing.raw_listing.location_lon
        else:
            print(f"No valid coordinates for {listing.id}. Failing routing.")
            listing.status = StatusEnum.FAILED_ROUTING
            return False

    # 2. Evaluate Routes
    for target_name, dest_coords in TARGETS.items():
        for mode_name, mode_str in MODES.items():
            
            eval_record = RouteEvaluation(
                id=str(uuid.uuid4()),
                listing_id=listing.id,
                target_name=target_name,
                route_mode=mode_name,
            )
            
            for time_col, time_str in TIMES.items():
                duration_mins = query_otp(
                    origin_lat, origin_lon, 
                    dest_coords['lat'], dest_coords['lon'], 
                    mode_str, time_str
                )
                setattr(eval_record, time_col, duration_mins)
            
            db_session.add(eval_record)
            
    listing.status = StatusEnum.ROUTED
    return True

@flow(name="Multimodal Route Evaluation")
def run_routing_flow():
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from tqdm import tqdm
    
    db = SessionLocal()
    try:
        # Fetch geocoded listings that haven't been routed
        listings_to_route = db.query(ParsedListing).filter(
            ParsedListing.status == StatusEnum.SPATIALLY_VALIDATED
        ).all()
        
        listing_ids = [l.id for l in listings_to_route]
        print(f"Found {len(listing_ids)} parcels to route.")
    finally:
        db.close()
        
    def process_parcel(listing_id):
        session = SessionLocal()
        try:
            listing = session.query(ParsedListing).options(
                joinedload(ParsedListing.raw_listing),
                joinedload(ParsedListing.geocoded_parcel)
            ).get(listing_id)
            
            if not listing:
                return False
                
            success = evaluate_parcel_routes.fn(session, listing)
            if success:
                session.commit()
                return True
            else:
                session.rollback()
                return False
        except Exception as e:
            session.rollback()
            return False
        finally:
            session.close()

    success_count = 0
    if listing_ids:
        with ThreadPoolExecutor(max_workers=15) as executor:
            futures = [executor.submit(process_parcel, lid) for lid in listing_ids]
            for future in tqdm(as_completed(futures), total=len(futures), desc="Routing Parcels (OTP)", unit="parcel"):
                if future.result():
                    success_count += 1
                    
    print(f"Successfully evaluated routes for {success_count} parcels.")

if __name__ == "__main__":
    run_routing_flow()
