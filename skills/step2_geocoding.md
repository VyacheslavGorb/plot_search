---
name: step2_geocoding
description: Technical specification and implementation details for Phase 2 - Entity Resolution & Verification (Geocoding).
triggers:
  - "how does geocoding work"
  - "implement phase 2"
  - "show the uldk integration"
---

# Phase 2: Entity Resolution & Verification (Geocoding)

This document details the implementation of the second phase of the pipeline. The goal is to accurately match the real estate listings with their official cadastral geometries using the Polish state ULDK API (Usługi Lokalizacji Danych Katastralnych).

## 1. Flow Overview

This phase is implemented using a **Prefect Flow** and executed via `main.py`.

**Prefect Flow:** `geocode_flow` (geocoder.py)
**Input:** Unprocessed (`StatusEnum.NEW`) records from the `parsed_listings` table.
**Output:** Official geometries and cadastral data inserted into the `geocoded_parcels` table.

**Idempotency & State:**
The flow queries only the `parsed_listings` that have `status == StatusEnum.NEW`. Upon a successful match, the record is stored in `geocoded_parcels` and the status in `parsed_listings` is updated to `StatusEnum.GEOCODED`. If no match can be found, the status is updated to `StatusEnum.FAILED_GEOCODING`. If the script crashes (e.g., due to severe API timeouts), the transaction rolls back, and the status remains `NEW`, allowing the flow to naturally resume on the next execution.

## 2. Component Details

### 2.1 The ULDK Client
The integration with `uldk.gugik.gov.pl` requires respecting rate limits to avoid bans.
- **Rate Limiting:** Enforced at `0.5` seconds per request.
- **Resilience:** Wrapped with the `tenacity` library to automatically retry on network failures (`requests.RequestException`).

### 2.2 Geocoding Strategies
The task `process_listing` attempts to find the correct parcel geometry using a cascading fallback strategy to maximize success rates:

1. **Exact Location Match (`fetch_exact`):**
   If the listing was flagged as having an exact location on the map (`is_exact_location == True`), the client calls `GetParcelByXY` using the provided longitude and latitude.

2. **Full TERYT ID Match (`fetch_by_id`):**
   If exact location fails (or wasn't provided), the pipeline cleans the extracted `parcel_number`. If the string matches the official 14-character TERYT format (e.g., `141207_5.0014.64`), it calls `GetParcelById`.

3. **Hierarchical Fallback (`fetch_by_nr`):**
   If the `parcel_number` is a short local number (e.g., `123/4`), the system:
   - Uses the latitude/longitude to call `GetParcelByXY` to resolve the administrative hierarchy (`voivodeship`, `county`, `commune`, `region`).
   - Reconstructs a localized search string and calls `GetParcelByNr`.

### 2.3 Subdivided Parcel Detection (Area Validation)
Sellers frequently advertise a 1000 m² plot that is actually an undivided part of a larger 1-hectare cadastral parcel. Knowing this is critical because spatial analysis (like setbacks) on the entire 1ha parcel will yield incorrect results.

**Implementation Steps:**
1. **Projection:** WKT polygons returned by ULDK (EPSG:4326) are transformed to the Polish metric coordinate system (EPSG:2180) using `pyproj`.
2. **Area Calculation:** The area of the official polygon is calculated in square meters using `shapely`.
3. **Tolerance Check:** The calculated area is compared against the `declared_area` from the listing.
4. **Flagging:** If the difference exceeds a 25% tolerance, the pipeline flags the parcel as `is_unsubdivided = True`. This crucial flag tells later pipeline stages that the geometry represents a larger parent parcel.

## 3. Error Handling & Retries
- **API Connectivity:** The Prefect task `process_listing` is configured with 3 retries and a 5-second delay. Combined with the internal `tenacity` retries, this creates a highly resilient fetcher.
- **Malformed WKTs or Math Errors:** Try/catch blocks ensure that a failure in area calculation (e.g. invalid geometries) does not crash the pipeline; it simply leaves `is_unsubdivided` as `None`.
