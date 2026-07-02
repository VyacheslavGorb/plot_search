# Plot Search ("Golden Parcel" Finder)

This project is designed to automate the search for a "Golden Parcel" of land in the Mazowieckie Voivodeship (around Warsaw) by cross-referencing real estate listings from Otodom against official Polish government spatial datasets.

## Project Structure

* `import_spatial_data.py`: The unified master script to ingest all spatial data into PostGIS.
* `database.py` / `schema.py`: Database connection and ORM schemas.
* `flows/`: Prefect workflows for scraping and parsing listings.
* `docker-compose.yml`: Local infrastructure including PostGIS database and OpenTripPlanner (OTP).

## Infrastructure Setup

1. Start the PostGIS database:
   ```bash
   docker compose up -d postgres
   ```

2. The database will be available at: `postgresql://postgres:password@127.0.0.1:5432/plot_search`

## Spatial Data Ingestion

The project requires three official spatial datasets to be downloaded into the `raw_maps/` folder:
1. **Flood Maps (ISOK/MZP):** Zipped shapefiles starting with `OZP_*.zip`
2. **BDOT10k:** Zipped GML/XML packages containing topographic data (forests, infrastructure, buildings).
3. **EGiB & Transactions:** A master geopackage file `14.gpkg.zip` containing 5.5 million parcel boundaries (`dzialki`) and transaction pricing history (`transakcje`).

### Running the Importer

Instead of using heavy GDAL C-binaries and Docker memory limits, all spatial data is imported using a highly-optimized, memory-safe pure Python script.

To ingest all raw maps into PostGIS:
```bash
uv run python import_spatial_data.py
```

### How the Importer Works

The script is resilient to Out-Of-Memory (OOM) crashes and broken metadata:
* **Flood Maps / BDOT10k:** Read in chunks of 50,000 features using `pyogrio` and `geopandas`, and streamed into PostGIS.
* **EGiB (Parcels):** Bypasses all GIS abstraction layers. It opens `14.gpkg` natively as an SQLite database, extracts the GeoPackage WKB binaries natively, and `COPY`s them directly into PostGIS via `psycopg2`.
* **Spatial Indexes:** PostGIS `GiST` indexes are constructed *after* loading to guarantee optimal bulk-insert speed and prevent index bloat.

## Spatial Data Sources
* [Geoportal (EGiB / BDOT10k)](https://www.geoportal.gov.pl/)
* [Wody Polskie (ISOK Flood Maps)](https://isok.gov.pl/)
