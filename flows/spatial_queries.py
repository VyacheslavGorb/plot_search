from sqlalchemy.orm import Session
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

def get_geometry_category(parcel: GeocodedParcel) -> str:
    if not parcel.polygon_wkt:
        return "C_POINT" if parcel.parsed_listing.raw_listing.location_lat else "D_NONE"
        
    if parcel.is_unsubdivided:
        return "B_UNSUBDIVIDED"
        
    return "A_PRECISE_POLYGON"

def evaluate_parcel_spatial_rules(db: Session, parcel: GeocodedParcel) -> SpatialEvaluation:
    category = get_geometry_category(parcel)
    
    evaluation = SpatialEvaluation(
        id=parcel.id,
        geometry_category=category
    )
    
    if category == "D_NONE":
        return evaluation
        
    if category in ["A_PRECISE_POLYGON", "B_UNSUBDIVIDED"]:
        if parcel.polygon_wkt.startswith("SRID="):
            geom_sql = f"ST_Transform(ST_GeomFromEWKT('{parcel.polygon_wkt}'), 2180)"
        else:
            geom_sql = f"ST_GeomFromText('{parcel.polygon_wkt}', 2180)"
    else:
        lat = parcel.parsed_listing.raw_listing.location_lat
        lon = parcel.parsed_listing.raw_listing.location_lon
        geom_sql = f"ST_Transform(ST_SetSRID(ST_MakePoint({lon}, {lat}), 4326), 2180)"

    # --- 1. Flood Zones ---
    flood_query = text(f"""
        SELECT EXISTS (
            SELECT 1 FROM flood_zones 
            WHERE ST_Intersects(geometry, ST_Transform({geom_sql}, 6870))
        )
    """)
    evaluation.intersects_flood_zone = db.execute(flood_query).scalar()

    # --- 2. High Voltage Power Lines ---
    power_query = text(f"""
        SELECT MIN(ST_Distance({geom_sql}, geometry)) 
        FROM bdot_suln_l 
        WHERE ST_DWithin({geom_sql}, geometry, 1000)
    """)
    evaluation.power_line_distance_m = db.execute(power_query).scalar()

    # --- 3. Forests ---
    forest_query = text(f"""
        SELECT MIN(ST_Distance({geom_sql}, geometry)) 
        FROM bdot_ptlz_a 
        WHERE ST_DWithin({geom_sql}, geometry, 1000)
    """)
    evaluation.forest_distance_m = db.execute(forest_query).scalar()
    
    # --- Major Roads (Noise Factor) ---
    major_road_query = text(f"""
        SELECT MIN(ST_Distance({geom_sql}, geometry)) 
        FROM bdot_skdr_l 
        WHERE ST_DWithin({geom_sql}, geometry, 1000)
        AND "klasaDrogi" IN ('autostrada', 'droga ekspresowa', 'droga główna ruchu przyśpieszonego', 'droga główna')
    """)
    evaluation.major_road_distance_m = db.execute(major_road_query).scalar()
    
    # --- Railways (Noise Factor) ---
    railway_query = text(f"""
        SELECT MIN(ST_Distance({geom_sql}, geometry)) 
        FROM bdot_sktr_l 
        WHERE ST_DWithin({geom_sql}, geometry, 1000)
    """)
    evaluation.railway_distance_m = db.execute(railway_query).scalar()

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
        '"funkcjaOgolnaBudynku" ILIKE \'%szko%\' OR "funkcjaSzczegolowaBudynku" ILIKE \'%szko%\'', 5000)
    
    # --- 5. Kindergartens ---
    evaluation.distance_to_kindergarten_m = fetch_amenity_dist(
        '"funkcjaOgolnaBudynku" ILIKE \'%przedszkole%\' OR "funkcjaSzczegolowaBudynku" ILIKE \'%przedszkole%\'', 5000)
    
    # --- Nurseries (Żłobki) ---
    evaluation.distance_to_nursery_m = fetch_amenity_dist(
        '"funkcjaOgolnaBudynku" ILIKE \'%żłob%\' OR "funkcjaSzczegolowaBudynku" ILIKE \'%żłob%\' OR "funkcjaOgolnaBudynku" ILIKE \'%zlob%\' OR "funkcjaSzczegolowaBudynku" ILIKE \'%zlob%\'', 5000)
    
    # --- Hospitals ---
    evaluation.distance_to_hospital_m = fetch_amenity_dist(
        '"funkcjaOgolnaBudynku" ILIKE \'%szpital%\' OR "funkcjaSzczegolowaBudynku" ILIKE \'%szpital%\'', 10000)
    
    # --- 6. Train Stations ---
    train_query = text(f"""
        SELECT MIN(ST_Distance({geom_sql}, geometry)) 
        FROM bdot_bubd_a 
        WHERE ST_DWithin({geom_sql}, geometry, 10000)
        AND ("funkcjaSzczegolowaBudynku" ILIKE '%dworzec kolejowy%')
    """)
    evaluation.distance_to_train_station_m = db.execute(train_query).scalar()
    
    # --- 7. Drainage Ditches (Rowy Melioracyjne) ---
    drainage_query = text(f"""
        SELECT MIN(ST_Distance({geom_sql}, geometry)) 
        FROM bdot_swrm_l 
        WHERE ST_DWithin({geom_sql}, geometry, 1000)
    """)
    evaluation.distance_to_drainage_m = db.execute(drainage_query).scalar()
    
    # Calculate usable envelope ONLY for Precise Polygons
    if category == "A_PRECISE_POLYGON":
        envelope_query = text(f"""
            WITH parcel AS (SELECT {geom_sql} as geom),
                 nearby_forests AS (
                     SELECT ST_Union(ST_Buffer(geometry, 12)) as exclusion_zone 
                     FROM bdot_ptlz_a 
                     WHERE ST_DWithin({geom_sql}, geometry, 50)
                 )
            SELECT 
                CASE 
                    WHEN (SELECT exclusion_zone FROM nearby_forests) IS NULL THEN ST_AsText(parcel.geom)
                    ELSE ST_AsText(ST_Difference(parcel.geom, (SELECT exclusion_zone FROM nearby_forests)))
                END
            FROM parcel;
        """)
        envelope_wkt = db.execute(envelope_query).scalar()
        
        if envelope_wkt:
            from shapely.wkt import loads
            from shapely.geometry import box
            from shapely.affinity import rotate, translate
            import numpy as np
            
            try:
                usable_geom = loads(envelope_wkt)
                evaluation.usable_building_area_m2 = usable_geom.area
                
                # Shrink by 4m for neighbor setbacks
                inner_envelope = usable_geom.buffer(-4)
                
                if inner_envelope.is_empty:
                    evaluation.fits_200m2_house = False
                else:
                    # The 3 layouts for 200m2 house
                    layouts = [
                        (14.14, 14.14), # 1:1
                        (12.0, 16.67),  # 1:1.39
                        (10.0, 20.0)    # 1:2
                    ]
                    
                    # Generate a grid of points inside the inner envelope
                    minx, miny, maxx, maxy = inner_envelope.bounds
                    x_coords = np.arange(minx, maxx, 3)
                    y_coords = np.arange(miny, maxy, 3)
                    
                    fits = False
                    # Create base rectangles centered at 0,0
                    base_rects = [box(-w/2, -h/2, w/2, h/2) for w, h in layouts]
                    
                    # Try to fit
                    for x in x_coords:
                        for y in y_coords:
                            if fits: break
                            # Quick check if point is in polygon
                            # (Avoid full contains check if point is far outside)
                            
                            for rect in base_rects:
                                if fits: break
                                translated_rect = translate(rect, x, y)
                                # Try rotations
                                for angle in range(0, 180, 15):
                                    rotated_rect = rotate(translated_rect, angle, use_radians=False)
                                    if inner_envelope.contains(rotated_rect):
                                        fits = True
                                        break
                    
                    evaluation.fits_200m2_house = fits
            except Exception as e:
                print(f"Error fitting house: {e}")
                evaluation.fits_200m2_house = False

    return evaluation
