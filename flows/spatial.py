from prefect import flow, task
from database import get_db, ParsedListing, GeocodedParcel, StatusEnum
from sqlalchemy.orm import Session
from flows.spatial_queries import evaluate_parcel_spatial_rules

@task(name="Evaluate Spatial Rules", retries=2, retry_delay_seconds=5)
def evaluate_parcel(listing_id: str):
    db: Session = next(get_db())
    try:
        parsed = db.query(ParsedListing).filter(ParsedListing.id == listing_id).first()
        if not parsed or not parsed.geocoded_parcel:
            return
            
        print(f"Executing spatial queries for {listing_id}...")
        evaluation = evaluate_parcel_spatial_rules(db, parsed.geocoded_parcel)
        db.add(evaluation)
        
        # Apply strict business rules for PASS / FAIL
        passed = True
        reason = ""
        
        # 1. Flood check
        if evaluation.intersects_flood_zone:
            passed = False
            reason += "Intersects Flood Zone. "
            
        # 2. Power line check
        if evaluation.power_line_distance_m is not None and evaluation.power_line_distance_m < 50:
            passed = False
            reason += f"Too close to power lines ({evaluation.power_line_distance_m:.1f}m). "
            
        # 3. Shape layout check (Only for Precise Polygons)
        if evaluation.geometry_category == "A_PRECISE_POLYGON":
            if not evaluation.fits_200m2_house:
                passed = False
                reason += f"Cannot fit a 200m2 house layout. "

        # 4. Noise factors (Major Roads & Railways)
        if evaluation.major_road_distance_m is not None and evaluation.major_road_distance_m < 150:
            passed = False
            reason += f"Too close to a major road ({evaluation.major_road_distance_m:.1f}m). "
            
        if evaluation.railway_distance_m is not None and evaluation.railway_distance_m < 150:
            passed = False
            reason += f"Too close to railway ({evaluation.railway_distance_m:.1f}m). "

        # 4. Utilities Extraction (KIUT)
        from flows.kiut import get_kiut_utilities
        try:
            utils = get_kiut_utilities(db, parsed.id)
            if utils:
                evaluation.has_water = utils.get('has_water')
                evaluation.has_sewage = utils.get('has_sewage')
                evaluation.has_gas = utils.get('has_gas')
                evaluation.has_electricity = utils.get('has_electricity')
                evaluation.has_telecom = utils.get('has_telecom')
        except Exception as e:
            print(f"KIUT analysis failed for {parsed.id}: {e}")

        if passed:
            parsed.status = StatusEnum.SPATIALLY_VALIDATED
            print(f"✅ {listing_id} passed spatial rules!")
        else:
            parsed.status = StatusEnum.FAILED_SPATIAL_RULES
            print(f"❌ {listing_id} failed spatial rules: {reason}")
            
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Error evaluating {listing_id}: {e}")
        raise e
    finally:
        db.close()

@flow(name="Phase 3: Spatial Filtering")
def spatial_flow():
    db: Session = next(get_db())
    try:
        from database import SpatialEvaluation
        # Find all geocoded listings that haven't been spatially checked
        pending = db.query(ParsedListing).outerjoin(
            SpatialEvaluation, ParsedListing.id == SpatialEvaluation.id
        ).filter(
            SpatialEvaluation.id == None,
            ParsedListing.status == StatusEnum.GEOCODED
        ).all()
        pending_ids = [p.id for p in pending]
    finally:
        db.close()
        
    print(f"Found {len(pending_ids)} listings ready for spatial filtering.")
    for listing_id in pending_ids:
        evaluate_parcel(listing_id)
