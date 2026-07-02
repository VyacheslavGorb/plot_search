import sys
from database import get_db, RawListing, ParsedListing, GeocodedParcel, StatusEnum
from flows.spatial import spatial_flow
from sqlalchemy.orm import Session
import uuid

def seed_test_data():
    db: Session = next(get_db())
    test_id = f"test_listing_{uuid.uuid4().hex[:8]}"
    
    # 1. Create Raw Listing
    raw = RawListing(
        id=test_id,
        source_url=f"http://test.com/{test_id}",
        location_lat=52.2297,
        location_lon=21.0122,
        is_exact_location=True
    )
    db.add(raw)
    
    # 2. Create Parsed Listing
    parsed = ParsedListing(
        id=test_id,
        parcel_number="141208_2.0019.353/2",
        status=StatusEnum.GEOCODED
    )
    db.add(parsed)
    
    # 3. Create Geocoded Parcel
    geocoded = GeocodedParcel(
        id=test_id,
        teryt="141208_2.0019.353/2",
        polygon_wkt="POLYGON((685234.405805 489577.861238,685249.202663 489578.779919,685120.616649 489356.276292,684994.177315 489137.522686,684986.776804 489140.398797,685111.587978 489360.887707,685234.405805 489577.861238))",
        is_unsubdivided=False
    )
    db.add(geocoded)
    
    db.commit()
    db.close()
    print(f"Seeded test parcel: {test_id}")
    return test_id

if __name__ == "__main__":
    test_id = seed_test_data()
    print("\n--- Running Spatial Flow ---")
    spatial_flow()
    
    # Verify DB State
    print("\n--- Verifying Results ---")
    db = next(get_db())
    parsed = db.query(ParsedListing).filter(ParsedListing.id == test_id).first()
    print(f"Final Status: {parsed.status}")
    
    evaluation = parsed.spatial_evaluation
    if evaluation:
        print(f"Category: {evaluation.geometry_category}")
        print(f"Usable Area (m2): {evaluation.usable_building_area_m2}")
        print(f"Intersects Flood Zone: {evaluation.intersects_flood_zone}")
        print(f"Distance to Forest (m): {evaluation.forest_distance_m}")
        print(f"Distance to Power Line (m): {evaluation.power_line_distance_m}")
        print(f"Distance to Train Station (m): {evaluation.distance_to_train_station_m}")
        print(f"Distance to School (m): {evaluation.distance_to_school_m}")
        print(f"Distance to Kindergarten (m): {evaluation.distance_to_kindergarten_m}")
        print(f"Distance to Drainage (m): {evaluation.distance_to_drainage_m}")
    else:
        print("NO SPATIAL EVALUATION FOUND!")
