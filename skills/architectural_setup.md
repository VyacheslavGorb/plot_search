---
name: architectural_setup
description: Detailed architectural setup, databases, schemas, and Docker configurations shared across the pipeline.
triggers:
  - "what is the architectural setup"
  - "show the database schema"
  - "how is docker configured"
---

# Architectural Setup & Shared Configuration

This document outlines the shared technical infrastructure, Docker configurations, and database schemas required for the Automated Real Estate Parcel Scoring Pipeline. It is currently populated with the general setup and specifics for Phase 1 (Ingestion).

## 1. General Infrastructure

The pipeline runs locally on an Ubuntu personal computer. It relies on a containerized environment to manage dependencies like databases and AI models.

### 1.1 Directory Structure
```text
.
├── docker-compose.yml     # Infrastructure (PostgreSQL, OTP)
├── main.py                # Master pipeline orchestrator
├── database.py            # SQLAlchemy models and schema definitions
├── schema.py              # Pydantic schemas for LLM extraction
├── import_spatial_data.py # Master spatial data ingestion script
├── flows/                 # Prefect workflows and tasks
│   ├── scraper.py         # Playwright Otodom scraping flow
│   ├── parser.py          # Ollama LLM text extraction flow
│   ├── geocoder.py        # ULDK geometry and spatial logic flow
│   ├── spatial.py         # Spatial filtering flow orchestrator
│   ├── spatial_queries.py # PostGIS and Shapely spatial math functions
│   ├── kiut.py            # KIUT WMS map download and Computer Vision analysis
│   └── router.py          # OTP Multimodal Routing flow
└── skills/                # Documentation and architectural notes
```

### 1.2 Docker Compose Configuration (`docker/docker-compose.yml`)

The core services are orchestrated using Docker Compose.

```yaml
version: '3.8'

services:
  postgres:
    image: postgis/postgis:15-3.4-alpine
    container_name: plot_search_db
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: password
      POSTGRES_DB: plot_search
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    restart: unless-stopped

  opentripplanner:
    image: opentripplanner/opentripplanner:latest
    container_name: plot_search_otp
    ports:
      - "8080:8080"
    volumes:
      - ./data/otp:/var/opentripplanner
    command: --load --serve
    restart: unless-stopped

volumes:
  pgdata:
```

## 2. Database Schema

We use **PostgreSQL with PostGIS** and `SQLAlchemy 2.0`. The database is managed using `database.py`.

### 2.1 Pipeline State Management & Idempotency

All pipeline steps must be strictly **idempotent**. We use a `StatusEnum` to track the state of each record: `NEW`, `PARSED`, `FAILED_PARSING`, `GEOCODED`, `FAILED_GEOCODING`, `SPATIALLY_VALIDATED`, `FAILED_SPATIAL_RULES`, `ROUTED`, and `FAILED_ROUTING`. Entities that have successfully passed a step or permanently failed a step are skipped in subsequent pipeline runs (incremental mode).

### 2.2 Core Tables

#### Table: `raw_listings`
Stores the exact output from the scrapers before any AI extraction or parsing.
- `id` (String, Primary Key)
- `source_url` (String, Unique)
- `title`, `description`, `raw_characteristics` (Text)
- `price`, `area`, `location_lat`, `location_lon` (Float)
- `is_exact_location` (Boolean)
- `images` (JSONB, list of image URLs)
- `advertiser_type` (String)
- `status` (Enum: `StatusEnum.NEW` initially)
- `scraped_at` (Timestamp)

#### Table: `parsed_listings`
Stores the structured data after Ollama LLM text extraction.
- `id` (String, Foreign Key to `raw_listings.id`, Primary Key)
- `parcel_number` (String, nullable)
- `media` (JSONB, structured utility presence)
- `status` (Enum: `StatusEnum.NEW` initially, then `GEOCODED` or `FAILED_GEOCODING`)
- `parsed_at` (Timestamp)

#### Table: `geocoded_parcels`
Stores the spatial geometry retrieved from the ULDK API based on the parsed parcel number or exact location.
- `id` (String, Foreign Key to `parsed_listings.id`, Primary Key)
- `teryt` (String, official parcel ID)
- `polygon_wkt` (Text, WKT geometry of the parcel in WGS84 EPSG:4326)
- `is_unsubdivided` (Boolean, true if cadastral area differs significantly from declared area)
- `location_hierarchy` (JSONB)
- `geocoded_at` (Timestamp)

#### Table: `spatial_evaluations`
Stores the results of spatial and geometric tests.
- `id` (String, Foreign Key to `parsed_listings.id`, Primary Key)
- `usable_building_area_m2` (Float, nullable)
- `fits_200m2_house` (Boolean, true if a 200m2 footprint fits with 4m setbacks)
- `dist_to_forest_m`, `dist_to_school_m`, `dist_to_train_station_m`, `dist_to_kindergarten_m`, `dist_to_drainage_m` (Float, nullable)
- `has_water`, `has_sewage`, `has_gas`, `has_electricity`, `has_telecom` (Boolean, KIUT extracted)
- `evaluated_at` (Timestamp)

#### Table: `route_evaluations`
Stores multimodal commute times from OpenTripPlanner.
- `id` (String, Primary Key)
- `listing_id` (String, Foreign Key to `parsed_listings.id`)
- `target_name` (String, e.g., 'VARSO_TOWER')
- `route_mode` (String, e.g., 'CAR_ONLY', 'BICYCLE_TRANSIT')
- `time_0800_mins`, `time_1400_mins`, `time_1700_mins` (Float, commute durations in minutes)
- `evaluated_at` (Timestamp)
