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
├── data/                  # Local storage for non-database data
│   ├── raw/               # Raw HTML downloads for debugging
│   ├── images/            # Downloaded listing images for VLM processing
│   └── dumps/             # Spatial data dumps (EGiB, BDOT10k, ISOK)
├── docker/                # Docker and infrastructure configs
│   └── docker-compose.yml
├── pipeline/              # Prefect workflows and tasks
├── core/                  # Shared database models and utilities
└── scripts/               # Utility and one-off scripts
```

### 1.2 Docker Compose Configuration (`docker/docker-compose.yml`)

The core services are orchestrated using Docker Compose.

```yaml
version: '3.8'

services:
  # Spatial Database
  postgis:
    image: postgis/postgis:15-3.4
    environment:
      POSTGRES_USER: user
      POSTGRES_PASSWORD: password
      POSTGRES_DB: plot_search
    ports:
      - "5432:5432"
    volumes:
      - postgis_data:/var/lib/postgresql/data

  # Local LLM for text extraction
  ollama:
    image: ollama/ollama
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama
    # Note: Ensure 'ollama run <model_name>' is executed post-startup

  # Routing Engine (Used in later steps)
  osrm:
    image: osrm/osrm-backend
    ports:
      - "5000:5000"
    volumes:
      - ./data/osrm:/data
    # Note: Requires processing the OSM map data beforehand

volumes:
  postgis_data:
  ollama_data:
```

## 2. Database Schema (General & Phase 1)

We use **PostgreSQL with PostGIS** (`GeoAlchemy2` and `SQLAlchemy 2.0 (asyncpg)`).

### 2.1 ORM Configuration

Use SQLAlchemy's declarative base. Async sessions are preferred for database interactions to maintain non-blocking behavior during API calls and ingestion.

### 2.2 Pipeline State Management & Idempotency

All pipeline steps must be strictly **idempotent**. Each table corresponding to a step (including `raw_listings`, `normalized_listings`, and future spatial/scoring tables) must have a `status` column. Entities that have successfully passed a step or permanently failed a step should not be re-processed during subsequent runs.

### 2.3 Phase 1 Schemas

During Phase 1 (Ingestion), we store raw scraped data and the normalized representation.

#### Table: `raw_listings`
Stores the exact output from the scrapers before any AI extraction or parsing.
- `id` (UUID, Primary Key)
- `source_url` (String, Unique)
- `source_portal` (String, e.g., 'otodom', 'olx')
- `status` (String: 'pending_parsing', 'parsed', 'failed_parsing', etc.)
- `raw_html_path` (String, path to local file)
- `raw_text` (Text)
- `images_paths` (JSONB, list of local paths)
- `scraped_at` (Timestamp)

#### Table: `normalized_listings`
Stores the structured data after Ollama text/vision processing.
- `id` (UUID, Primary Key)
- `raw_listing_id` (UUID, Foreign Key)
- `status` (String: 'pending_geometry', 'failed_extraction', 'rejected', etc.)
- `price` (Numeric)
- `declared_area` (Numeric)
- `extracted_parcel_number` (String, nullable)
- `extracted_gmina` (String, nullable)
- `extraction_method` (String: 'llm_text', 'vlm_vision', 'manual')
- `created_at` (Timestamp)
