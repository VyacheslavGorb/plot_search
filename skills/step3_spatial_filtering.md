---
name: step3_spatial_filtering
description: Technical specification, TO-DO items, and Spatial Check Matrix for Phase 3 - Spatial Filtering & Setbacks.
triggers:
  - "how does spatial filtering work"
  - "implement phase 3"
  - "what is left to implement"
---

# Phase 3: Spatial Filtering & Setbacks

This phase represents the core physical validation of the parcel. Having loaded 5.5 million EGiB parcels and BDOT10k topographic layers into PostGIS, the pipeline must mathematically prove that a house can be built on the parcel legally and safely.

## 1. Data Completeness Categories

Because real estate listings are notoriously messy, spatial analysis must adapt to the "resolution" or confidence level of the geometry we possess. If we apply precise math to an approximate geometry, we will incorrectly reject valid parcels.

We categorize the incoming parcel geometry into four confidence levels:

| Category | Description |
| :--- | :--- |
| **A: Precise Polygon** | The listing provided a valid parcel number, and the ULDK API returned an exact polygon matching the declared area. |
| **B: Unsubdivided Polygon** | The listing provided a parcel number, but the official cadastral polygon is significantly larger than the advertised plot (e.g., selling 1000 m² out of a 1 hectare field). |
| **C: Approximate Point** | The listing only provided a map pin (latitude/longitude), and we couldn't resolve it to a specific parcel polygon. |
| **D: No Geometry** | The listing only provided a city or district name. |

## 2. Spatial Checks Matrix (Based on currently loaded data)

Here is exactly what we can check using our local PostGIS data, categorized by what is legally/mathematically valid for each confidence level.

| Check Name | Target Dataset | Category A (Precise Polygon) | Category B (Unsubdivided Polygon) | Category C (Approx Point) |
| :--- | :--- | :--- | :--- | :--- |
| **1. Forest Setback (12m)** | `bdot_ptlz_a` | **FULL:** Calculate exact `ST_Difference` with 12m buffer. Check if remaining envelope area >= 200m². | **PARTIAL:** Check if parent polygon is >90% covered by 12m forest buffer. Cannot calculate exact usable area. | **PARTIAL:** Check if point is within 12m of forest. Cannot calculate envelope. |
| **2. Flood Zone Intersection** | `flood_zones` | **FULL:** Disqualify if >10% of polygon intersects flood zone. | **PARTIAL:** Flag for manual review if parent polygon intersects flood zone. | **PARTIAL:** Check if point falls inside a flood zone. |
| **3. High-Voltage Lines** | `bdot_suln_l` | **FULL:** Disqualify if polygon intersects a 50m health buffer around power lines. | **FULL:** Disqualify if parent polygon is entirely within the 50m buffer. Flag if partial. | **PARTIAL:** Check if point is within 50m of power lines. |
| **4. Drainage Ditches** | `bdot_swrm_l` | **FULL:** Calculate exact distance to nearest meliorative channel. | **PARTIAL:** Calculate distance from parent polygon to channel. | **PARTIAL:** Check distance from point to channel. |
| **5. Schools** | `bdot_bubd_a` | **FULL:** Calculate distance to nearest school (`funkcjaSzczegolowaBudynku`). | **PARTIAL:** Calculate distance from parent polygon. | **PARTIAL:** Calculate distance from point. |
| **6. Kindergartens** | `bdot_bubd_a` | **FULL:** Calculate distance to nearest kindergarten. | **PARTIAL:** Calculate distance from parent polygon. | **PARTIAL:** Calculate distance from point. |
| **7. Train Stations** | `bdot_bubd_a` | **FULL:** Calculate distance to nearest train station (`dworzec kolejowy`). | **PARTIAL:** Calculate distance from parent polygon. | **PARTIAL:** Calculate distance from point. |
| **8. House Layout Fit** | `shapely` | **FULL:** Subtract 4m neighbor setback, test 3 standard 200m² footprints (14.1x14.1, 12x16.7, 10x20) rotated 0-180°. Fail if none fit. | **SKIP:** Cannot test shape of unsubdivided plots accurately. | **SKIP:** Points have no area. |

*(Category D skips all spatial checks and goes straight to manual review).*

## 3. Implementation Plan (COMPLETED)

### 3.1 Spatial Query Module (`flows/spatial_queries.py`) - [x] COMPLETED
A Python module using PostGIS and Shapely has been created to execute the matrix above. It takes a listing's geometry, determines its Category (A, B, C), and applies the corresponding spatial/geometric queries.

### 3.2 Prefect Flow Integration (`flows/spatial.py`) - [x] COMPLETED
A Prefect flow wraps the queries to:
1. Select all parcels from `parsed_listings` that are `GEOCODED` but have no spatial evaluation.
2. Execute the appropriate spatial SQL/Shapely queries based on geometry category.
3. Update the database state to either pass the parcel (`SPATIALLY_VALIDATED`) or fail it permanently (`FAILED_SPATIAL_RULES`).

### 3.3 Database Schema Updates (`schema.py` / `database.py`) - [x] COMPLETED
- Added `SpatialEvaluation` table to store the results of these checks (`usable_building_area_m2`, `fits_200m2_house`, amenity distances, etc.).
- Added `FAILED_SPATIAL_RULES` and `SPATIALLY_VALIDATED` to `StatusEnum`.

### 3.4 Utilities Extraction (KIUT Endpoint) - [x] COMPLETED
A robust Computer Vision pipeline (`flows/kiut.py`) integrates with the Krajowa Integracja Uzbrojenia Terenu (KIUT) WMS endpoint. It automatically:
1. Generates a transparent PNG utilities map for the parcel (buffered by 50 meters).
2. Analyzes the image pixels against standard GESUT color codes to extract explicit boolean values (`has_water`, `has_sewage`, `has_gas`, `has_electricity`, `has_telecom`).
3. Persists these flags into the `SpatialEvaluation` database for programmatic filtering.
