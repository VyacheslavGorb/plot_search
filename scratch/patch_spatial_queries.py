import re
with open('/home/vyacheslav/projects/plot_search/flows/spatial_queries.py', 'r') as f:
    content = f.read()

# We'll replace the block from "    # --- 4. Schools ---" to before "    # --- 6. Train Stations ---"

top_imports = """from sqlalchemy.orm import Session
from sqlalchemy import text
from database import SpatialEvaluation, GeocodedParcel
import json
import urllib.request

def get_routed_distance(origin_lat, origin_lon, dest_lat, dest_lon):
    if origin_lat is None or origin_lon is None or dest_lat is None or dest_lon is None:
        return None
    query = f'''
    {{
      plan(
        from: {{lat: {origin_lat}, lon: {origin_lon}}}
        to: {{lat: {dest_lat}, lon: {dest_lon}}}
        transportModes: [{{mode: CAR}}]
      ) {{
        itineraries {{
          legs {{
            distance
          }}
        }}
      }}
    }}
    '''
    req = urllib.request.Request("http://localhost:8080/otp/routers/default/index/graphql", data=json.dumps({'query': query}).encode('utf-8'))
    req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            itins = data.get('data', {}).get('plan', {}).get('itineraries', [])
            if not itins:
                return None
            total_dist = sum(leg['distance'] for leg in itins[0]['legs'])
            return total_dist
    except Exception as e:
        print(f"OTP routing failed: {e}")
        return None
"""
content = content.replace("from sqlalchemy.orm import Session\nfrom sqlalchemy import text\nfrom database import SpatialEvaluation, GeocodedParcel\nimport json\n", top_imports)

amenities_logic = """
    # Helper for amenities
    origin_lat = parcel.parsed_listing.raw_listing.location_lat
    origin_lon = parcel.parsed_listing.raw_listing.location_lon
    
    if not origin_lat or not origin_lon:
        if parcel.polygon_wkt:
            coords_query = text(f"SELECT ST_Y(ST_Transform({geom_sql}, 4326)), ST_X(ST_Transform({geom_sql}, 4326))")
            res = db.execute(coords_query).first()
            if res:
                origin_lat, origin_lon = res[0], res[1]

    def fetch_amenity_dist(condition, radius):
        query = text(f'''
            SELECT ST_Y(ST_Transform(ST_Centroid(geometry), 4326)) AS lat, 
                   ST_X(ST_Transform(ST_Centroid(geometry), 4326)) AS lon,
                   ST_Distance({geom_sql}, geometry) as straight_dist
            FROM bdot_bubd_a 
            WHERE ST_DWithin({geom_sql}, geometry, {radius})
            AND ({condition})
            ORDER BY ST_Distance({geom_sql}, geometry) ASC
            LIMIT 1
        ''')
        row = db.execute(query).first()
        if not row:
            return None
        dest_lat, dest_lon, straight_dist = row[0], row[1], row[2]
        routed = get_routed_distance(origin_lat, origin_lon, dest_lat, dest_lon)
        return routed if routed is not None else straight_dist

    # --- 4. Schools ---
    evaluation.distance_to_school_m = fetch_amenity_dist(
        "\"funkcjaOgolnaBudynku\" ILIKE '%szko%' OR \"funkcjaSzczegolowaBudynku\" ILIKE '%szko%'", 5000)
    
    # --- 5. Kindergartens ---
    evaluation.distance_to_kindergarten_m = fetch_amenity_dist(
        "\"funkcjaOgolnaBudynku\" ILIKE '%przedszkole%' OR \"funkcjaSzczegolowaBudynku\" ILIKE '%przedszkole%'", 5000)
    
    # --- Nurseries (Żłobki) ---
    evaluation.distance_to_nursery_m = fetch_amenity_dist(
        "\"funkcjaOgolnaBudynku\" ILIKE '%żłob%' OR \"funkcjaSzczegolowaBudynku\" ILIKE '%żłob%' OR \"funkcjaOgolnaBudynku\" ILIKE '%zlob%' OR \"funkcjaSzczegolowaBudynku\" ILIKE '%zlob%'", 5000)
    
    # --- Hospitals ---
    evaluation.distance_to_hospital_m = fetch_amenity_dist(
        "\"funkcjaOgolnaBudynku\" ILIKE '%szpital%' OR \"funkcjaSzczegolowaBudynku\" ILIKE '%szpital%'", 10000)
"""

old_amenities = """    # --- 4. Schools ---
    school_query = text(f\"\"\"
        SELECT MIN(ST_Distance({geom_sql}, geometry)) 
        FROM bdot_bubd_a 
        WHERE ST_DWithin({geom_sql}, geometry, 5000)
        AND ("funkcjaOgolnaBudynku" ILIKE '%szko%' OR "funkcjaSzczegolowaBudynku" ILIKE '%szko%')
    \"\"\")
    evaluation.distance_to_school_m = db.execute(school_query).scalar()
    
    # --- 5. Kindergartens ---
    kindergarten_query = text(f\"\"\"
        SELECT MIN(ST_Distance({geom_sql}, geometry)) 
        FROM bdot_bubd_a 
        WHERE ST_DWithin({geom_sql}, geometry, 5000)
        AND ("funkcjaOgolnaBudynku" ILIKE '%przedszkole%' OR "funkcjaSzczegolowaBudynku" ILIKE '%przedszkole%')
    \"\"\")
    evaluation.distance_to_kindergarten_m = db.execute(kindergarten_query).scalar()
    
    # --- Nurseries (Żłobki) ---
    nursery_query = text(f\"\"\"
        SELECT MIN(ST_Distance({geom_sql}, geometry)) 
        FROM bdot_bubd_a 
        WHERE ST_DWithin({geom_sql}, geometry, 5000)
        AND ("funkcjaOgolnaBudynku" ILIKE '%żłob%' OR "funkcjaSzczegolowaBudynku" ILIKE '%żłob%' OR "funkcjaOgolnaBudynku" ILIKE '%zlob%' OR "funkcjaSzczegolowaBudynku" ILIKE '%zlob%')
    \"\"\")
    evaluation.distance_to_nursery_m = db.execute(nursery_query).scalar()
    
    # --- Hospitals ---
    hospital_query = text(f\"\"\"
        SELECT MIN(ST_Distance({geom_sql}, geometry)) 
        FROM bdot_bubd_a 
        WHERE ST_DWithin({geom_sql}, geometry, 10000)
        AND ("funkcjaOgolnaBudynku" ILIKE '%szpital%' OR "funkcjaSzczegolowaBudynku" ILIKE '%szpital%')
    \"\"\")
    evaluation.distance_to_hospital_m = db.execute(hospital_query).scalar()"""

content = content.replace(old_amenities, amenities_logic.strip())

with open('/home/vyacheslav/projects/plot_search/flows/spatial_queries.py', 'w') as f:
    f.write(content)
