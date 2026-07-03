from prefect import flow, task
from sqlalchemy.orm import Session, joinedload
from database import get_db, ParsedListing, StatusEnum

MAX_SCORE = 2200

@task
def calculate_score(listing: ParsedListing) -> dict:
    score = 1000  # Base score
    bad_reasons = []
    good_reasons = []

    spatial = listing.spatial_evaluation
    if not spatial:
        return {"score": 0, "reasons": ["❌ No spatial evaluation found"]}
        
    needs_verification = False
    if spatial.geometry_category not in ["A_PRECISE_POLYGON", "A_PRECISE", "B_UNSUBDIVIDED"]:
        needs_verification = True
        
    raw = listing.raw_listing
    
    # === BAD THINGS (Penalties / Risks) ===
    # 0. Shape Layout Check
    if spatial.geometry_category == "A_PRECISE_POLYGON":
        if spatial.fits_200m2_house is False:
            score -= 500
            needs_verification = True
            bad_reasons.append("❌ SHAPE: Cannot fit a standard 200m² square house footprint")
        else:
            good_reasons.append("✅ SHAPE: Fits standard 200m² house footprint")
    # 1. Flood zone
    if spatial.intersects_flood_zone:
        score -= 1000
        needs_verification = True
        bad_reasons.append("❌ FLOOD ZONE: Intersects flood zone")
    else:
        bad_reasons.append("✅ FLOOD ZONE: Safe (No intersection)")
        
    # 2. High Voltage Lines
    if spatial.power_line_distance_m is not None:
        if spatial.power_line_distance_m < 50:
            score -= 500
            needs_verification = True
            bad_reasons.append(f"❌ HIGH VOLTAGE: Very close ({spatial.power_line_distance_m / 1000:.2f}km)")
        elif spatial.power_line_distance_m < 150:
            score -= 100
            bad_reasons.append(f"❌ HIGH VOLTAGE: Nearby ({spatial.power_line_distance_m / 1000:.2f}km)")
        else:
            bad_reasons.append(f"✅ HIGH VOLTAGE: Safe distance ({spatial.power_line_distance_m / 1000:.2f}km)")
    else:
        bad_reasons.append("✅ HIGH VOLTAGE: None detected")

    # 3. Railway
    if spatial.railway_distance_m is not None:
        if spatial.railway_distance_m < 150:
            score -= 300
            needs_verification = True
            bad_reasons.append(f"❌ RAILWAY: Very close ({spatial.railway_distance_m / 1000:.2f}km)")
        elif spatial.railway_distance_m < 500:
            score -= 300
            bad_reasons.append(f"❌ RAILWAY: Very close ({spatial.railway_distance_m / 1000:.2f}km)")
        else:
            bad_reasons.append(f"✅ RAILWAY: Safe distance ({spatial.railway_distance_m / 1000:.2f}km)")
    else:
        bad_reasons.append("✅ RAILWAY: None detected")
        
    # 4. Major Road
    if spatial.major_road_distance_m is not None:
        if spatial.major_road_distance_m < 150:
            score -= 150
            needs_verification = True
            bad_reasons.append(f"❌ MAJOR ROAD: Close / Noise risk ({spatial.major_road_distance_m / 1000:.2f}km)")
        elif spatial.major_road_distance_m < 300:
            score -= 150
            bad_reasons.append(f"❌ MAJOR ROAD: Close / Noise risk ({spatial.major_road_distance_m / 1000:.2f}km)")
        else:
            bad_reasons.append(f"✅ MAJOR ROAD: Safe distance ({spatial.major_road_distance_m / 1000:.2f}km)")
    else:
        bad_reasons.append("✅ MAJOR ROAD: None detected")
        
    # 5. Drainage Ditch
    if spatial.distance_to_drainage_m is not None:
        if spatial.distance_to_drainage_m < 100:
            score -= 100
            bad_reasons.append(f"❌ DRAINAGE DITCH: Very close ({spatial.distance_to_drainage_m / 1000:.2f}km)")
        else:
            bad_reasons.append(f"✅ DRAINAGE DITCH: Safe distance ({spatial.distance_to_drainage_m / 1000:.2f}km)")
    else:
        bad_reasons.append("✅ DRAINAGE DITCH: None detected")


    # === GOOD THINGS (Bonuses / Benefits) ===
    # 6. Forest Proximity
    if spatial.forest_distance_m is not None:
        if spatial.forest_distance_m <= 100:
            score += 200
            good_reasons.append(f"✅ FOREST: Adjacent ({spatial.forest_distance_m / 1000:.2f}km)")
        elif spatial.forest_distance_m <= 500:
            score += 100
            good_reasons.append(f"✅ FOREST: Close ({spatial.forest_distance_m / 1000:.2f}km)")
        else:
            good_reasons.append(f"❌ FOREST: Far ({spatial.forest_distance_m / 1000:.2f}km)")
    else:
        good_reasons.append("❌ FOREST: None detected nearby")

    # 7. School Proximity
    if spatial.distance_to_school_m is not None:
        if spatial.distance_to_school_m < 5000:
            score += 100
            good_reasons.append(f"✅ SCHOOL: Nearby ({spatial.distance_to_school_m / 1000:.2f}km)")
        else:
            good_reasons.append(f"❌ SCHOOL: Far ({spatial.distance_to_school_m / 1000:.2f}km)")
    else:
        good_reasons.append("❌ SCHOOL: None detected nearby")

    # 8. Kindergarten Proximity
    if spatial.distance_to_kindergarten_m is not None:
        if spatial.distance_to_kindergarten_m < 5000:
            score += 100
            good_reasons.append(f"✅ KINDERGARTEN (Przedszkole): Nearby ({spatial.distance_to_kindergarten_m / 1000:.2f}km)")
        else:
            good_reasons.append(f"❌ KINDERGARTEN (Przedszkole): Far ({spatial.distance_to_kindergarten_m / 1000:.2f}km)")
    else:
        good_reasons.append("❌ KINDERGARTEN (Przedszkole)r: None detected nearby")

    # 9. Nursery Proximity
    if spatial.distance_to_nursery_m is not None:
        if spatial.distance_to_nursery_m < 5000:
            score += 100
            good_reasons.append(f"✅ NURSERY (Żłobek): Nearby ({spatial.distance_to_nursery_m / 1000:.2f}km)")
        else:
            good_reasons.append(f"❌ NURSERY (Żłobek): Far ({spatial.distance_to_nursery_m / 1000:.2f}km)")
    else:
        good_reasons.append("❌ NURSERY (Żłobek): None detected nearby")

    # 10. Hospital Proximity
    if spatial.distance_to_hospital_m is not None:
        if spatial.distance_to_hospital_m < 10000:
            score += 50
            good_reasons.append(f"✅ HOSPITAL: Within reach ({spatial.distance_to_hospital_m / 1000:.2f}km)")
        else:
            good_reasons.append(f"❌ HOSPITAL: Far ({spatial.distance_to_hospital_m / 1000:.2f}km)")
    else:
        good_reasons.append("❌ HOSPITAL: None detected nearby")

    # 11. Utilities
    utils = []
    if spatial.has_water: utils.append("Water")
    if spatial.has_electricity: utils.append("Power")
    if spatial.has_gas: utils.append("Gas")
    if spatial.has_sewage: utils.append("Sewage")
    
    if spatial.has_water: score += 50
    if spatial.has_electricity: score += 50
    if spatial.has_gas: score += 50
    if spatial.has_sewage: score += 50

    if utils:
        good_reasons.append(f"✅ UTILITIES: {', '.join(utils)}")
    else:
        score -= 200
        good_reasons.append("❌ UTILITIES: None detected nearby")

    # 12. Commute (From RouteEvaluations)
    routes = listing.route_evaluations
    if routes:
        # Car commute to Varso Tower at 0800
        car_varso = [r.time_0800_mins for r in routes if r.target_name == "VARSO_TOWER" and r.route_mode == "CAR_ONLY" and r.time_0800_mins]
        if car_varso:
            best_car = min(car_varso)
            if best_car < 45:
                score += 200
                good_reasons.append(f"✅ COMMUTE (CAR): Excellent to Varso Tower ({best_car:.0f} min)")
            elif best_car < 60:
                score += 50
                good_reasons.append(f"✅ COMMUTE (CAR): Acceptable to Varso Tower ({best_car:.0f} min)")
            else:
                score -= 100
                good_reasons.append(f"❌ COMMUTE (CAR): Long drive to Varso Tower ({best_car:.0f} min)")
        else:
             good_reasons.append("❌ COMMUTE (CAR): Data missing")
                
    # 11. Train Station Proximity
    if spatial.distance_to_train_station_m is not None:
        # Since we use route builder, distances might be a bit longer than straight line.
        if spatial.distance_to_train_station_m < 5000:
            score += 100
            good_reasons.append(f"✅ TRAIN STATION: Nearby commute ({spatial.distance_to_train_station_m / 1000:.2f}km drive)")
        elif spatial.distance_to_train_station_m < 10000:
            score += 50
            good_reasons.append(f"✅ TRAIN STATION: Acceptable commute ({spatial.distance_to_train_station_m / 1000:.2f}km drive)")
        else:
            good_reasons.append(f"❌ TRAIN STATION: Far ({spatial.distance_to_train_station_m / 1000:.2f}km drive)")
    else:
        good_reasons.append("❌ TRAIN STATION: None detected nearby")
        
    if not routes:
        good_reasons.append("❌ COMMUTE: No routing data available")

    # 13. Price
    if raw.price and raw.area:
        price_per_m2 = raw.price / raw.area
        if price_per_m2 < 150:
            score += 150
            good_reasons.append(f"✅ PRICE: Great deal ({price_per_m2:.0f} PLN/m²)")
        elif price_per_m2 > 400:
            score -= 100
            good_reasons.append(f"❌ PRICE: Expensive ({price_per_m2:.0f} PLN/m²)")
        else:
            good_reasons.append(f"✅ PRICE: Average ({price_per_m2:.0f} PLN/m²)")
    else:
        good_reasons.append("❌ PRICE: Not specified")

    cat_map = {
        "A_PRECISE_POLYGON": "ℹ️ LOCATION: Correct precise polygon",
        "A_PRECISE": "ℹ️ LOCATION: Correct precise polygon",
        "B_UNSUBDIVIDED": "⚠️ LOCATION: Unsubdivided polygon",
        "C_EXACT_POINT": "⚠️ LOCATION: Exact point (polygon unavailable/rejected)",
        "C_APPROX_POINT": "⚠️ LOCATION: Approximate general area only",
        "C_POINT": "⚠️ LOCATION: Approximate point/area location",
        "D_NONE": "❌ LOCATION: No geometry available"
    }
    location_type = cat_map.get(spatial.geometry_category, f"ℹ️ LOCATION: {spatial.geometry_category}")

    wkt = listing.geocoded_parcel.polygon_wkt if listing.geocoded_parcel else None

    reasons = bad_reasons + good_reasons
    
    if needs_verification:
        score = 0
        reasons.insert(0, "🚨 **ADDITIONAL VERIFICATION NEEDED: Missing exact boundary or major spatial warning!**")
        
    return {
        "score": score, 
        "max_score": MAX_SCORE, 
        "location_type": location_type,
        "reasons": reasons, 
        "price": raw.price, 
        "area": raw.area,
        "wkt": wkt,
        "lat": raw.location_lat,
        "lon": raw.location_lon
    }
    
@flow(name="Scoring Engine")
def run_scoring_flow(print_top=10):
    db = next(get_db())
    try:
        listings = db.query(ParsedListing).options(
            joinedload(ParsedListing.raw_listing),
            joinedload(ParsedListing.spatial_evaluation),
            joinedload(ParsedListing.route_evaluations),
            joinedload(ParsedListing.geocoded_parcel)
        ).filter(
            ParsedListing.status.in_([StatusEnum.SPATIALLY_VALIDATED, StatusEnum.ROUTED])
        ).all()
        
        print(f"Scoring {len(listings)} fully validated parcels...")
        
        results = []
        for listing in listings:
            res = calculate_score.fn(listing)
            results.append({
                "id": listing.id,
                "url": listing.raw_listing.source_url,
                "score": res["score"],
                "max_score": res["max_score"],
                "location_type": res["location_type"],
                "reasons": res["reasons"],
                "wkt": res["wkt"],
                "lat": res["lat"],
                "lon": res["lon"]
            })
            
        # Sort by score descending
        results.sort(key=lambda x: x["score"], reverse=True)
        
        print(f"\n🏆 TOP {print_top} PARCELS 🏆")
        for i, r in enumerate(results[:print_top]):
            print(f"\n#{i+1} | Score: {r['score']}/{r['max_score']} | {r['url']}")
            print(f"  {r['location_type']}")
            for reason in r['reasons']:
                print(f"  {reason}")
                
        return results
    finally:
        db.close()

if __name__ == "__main__":
    run_scoring_flow()
