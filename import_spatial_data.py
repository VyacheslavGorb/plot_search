import os
import glob
import zipfile
import pyogrio
import geopandas as gpd
from sqlalchemy import create_engine, text
import shutil
from shapely.geometry import MultiPolygon, MultiLineString, MultiPoint
import sqlite3
import psycopg2
from psycopg2.extras import execute_values

DB_URL = "postgresql://postgres:password@127.0.0.1:5432/plot_search"
engine = create_engine(DB_URL)

def promote_to_multi(geom):
    """Ensure all geometries are Multi* variants so PostGIS tables accept mixed batches safely."""
    if geom is None:
        return None
    if geom.geom_type == 'Polygon':
        return MultiPolygon([geom])
    if geom.geom_type == 'LineString':
        return MultiLineString([geom])
    if geom.geom_type == 'Point':
        return MultiPoint([geom])
    return geom

def safe_drop_table(table_name):
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {table_name} CASCADE"))

def process_layer_pyogrio(filepath, layer, table_name, chunk_size=50000):
    """Used for Flood Maps and BDOT10k which are successfully read by pyogrio."""
    try:
        info = pyogrio.read_info(filepath, layer=layer)
        total_features = info.get('features', 0)
    except Exception as e:
        print(f"Skipping {layer or filepath}: {e}")
        return

    print(f"Loading {layer or 'file'} into {table_name}...")
    safe_drop_table(table_name)
    
    loaded = 0
    i = 0
    while True:
        try:
            gdf = pyogrio.read_dataframe(
                filepath, 
                layer=layer, 
                skip_features=i, 
                max_features=chunk_size
            )
            
            if gdf.empty:
                break
                
            if 'geometry' in gdf.columns:
                gdf['geometry'] = gdf['geometry'].apply(promote_to_multi)
                
            gdf = gdf[gdf['geometry'].is_valid & ~gdf['geometry'].is_empty]
            gdf.to_postgis(table_name, engine, if_exists='append', index=False)
            
            loaded += len(gdf)
            print(f"  -> Loaded {loaded} features...")
            
            if len(gdf) < chunk_size:
                break
                
            i += chunk_size
        except Exception as e:
            print(f"  -> Error on chunk {i}: {e}")
            break

def strip_gpkg_header(blob):
    """Strips the binary GPKG header to yield raw PostGIS-compatible WKB."""
    if not blob: return None
    flags = blob[3]
    env = (flags >> 1) & 7
    if env == 0: hl = 8
    elif env == 1: hl = 40
    elif env in (2, 3): hl = 56
    elif env == 4: hl = 72
    else: hl = 8
    return blob[hl:].hex()

def process_table_sqlite_stream(gpkg_path, table_name, batch_size=20000):
    """Used for EGiB to bypass pyogrio/GDAL metadata bugs when reading massive files."""
    print(f"Connecting to {gpkg_path} to natively import {table_name} via SQLite stream...")
    conn_lite = sqlite3.connect(gpkg_path)
    c_lite = conn_lite.cursor()
    
    c_lite.execute(f"PRAGMA table_info({table_name})")
    cols = c_lite.fetchall()
    
    pg_cols = []
    col_names = []
    for col in cols:
        name = col[1]
        ctype = col[2].upper()
        col_names.append(name)
        if name == 'geometry':
            pg_cols.append("geom geometry(Geometry, 2180)")
        elif 'INT' in ctype:
            pg_cols.append(f"{name} BIGINT")
        elif 'REAL' in ctype or 'FLOAT' in ctype:
            pg_cols.append(f"{name} DOUBLE PRECISION")
        else:
            pg_cols.append(f"{name} TEXT")
            
    conn_pg = psycopg2.connect(DB_URL)
    with conn_pg.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE;")
        cur.execute(f"CREATE TABLE {table_name} ({', '.join(pg_cols)});")
    conn_pg.commit()
    
    insert_cols = [c if c != 'geometry' else 'geom' for c in col_names]
    geom_idx = col_names.index('geometry')
    
    template_parts = []
    for i in range(len(col_names)):
        if i == geom_idx:
            template_parts.append("ST_GeomFromWKB(decode(%s, 'HEX'), 2180)")
        else:
            template_parts.append("%s")
    template = "(" + ", ".join(template_parts) + ")"
    
    query = f"INSERT INTO {table_name} ({', '.join(insert_cols)}) VALUES %s"
    
    c_lite.execute(f"SELECT * FROM {table_name}")
    batch = []
    count = 0
    
    while True:
        rows = c_lite.fetchmany(batch_size)
        if not rows:
            break
            
        for row in rows:
            new_row = list(row)
            if new_row[geom_idx]:
                new_row[geom_idx] = strip_gpkg_header(new_row[geom_idx])
            batch.append(tuple(new_row))
            
        if batch:
            with conn_pg.cursor() as cur:
                execute_values(cur, query, batch, template=template)
            conn_pg.commit()
            count += len(batch)
            print(f"  -> Loaded {count} features into {table_name}...")
            batch = []
            
    conn_lite.close()
    conn_pg.close()

def main():
    print("======================================")
    print("🚀 STARTING PYTHON SPATIAL IMPORT")
    print("======================================")
    
    # 1. Flood Maps
    print("\n🌊 Importing Flood Maps...")
    tmp_flood = "raw_maps/tmp_flood"
    os.makedirs(tmp_flood, exist_ok=True)
    for zipfile_path in glob.glob("raw_maps/OZP_*.zip"):
        with zipfile.ZipFile(zipfile_path, 'r') as zip_ref:
            zip_ref.extractall(tmp_flood)
            
        shp_file = None
        for root, dirs, files in os.walk(tmp_flood):
            for file in files:
                if file.endswith(".shp"):
                    shp_file = os.path.join(root, file)
                    break
        
        if shp_file:
            process_layer_pyogrio(shp_file, None, "flood_zones", chunk_size=50000)
            
        for item in os.listdir(tmp_flood):
            item_path = os.path.join(tmp_flood, item)
            if os.path.isfile(item_path): os.unlink(item_path)
            elif os.path.isdir(item_path): shutil.rmtree(item_path)
    shutil.rmtree(tmp_flood)
    
    # 2. BDOT10k
    print("\n⚡ Importing BDOT10k (ALL Layers)...")
    bdot_zip = "raw_maps/BDOT10k.zip"
    bdot_tmp = "raw_maps/bdot_tmp"
    os.makedirs(bdot_tmp, exist_ok=True)
    
    with zipfile.ZipFile(bdot_zip, 'r') as zip_ref:
        zip_ref.extractall(bdot_tmp)
        
    for county_zip in glob.glob(f"{bdot_tmp}/14/*.zip"):
        county_dir = county_zip.replace(".zip", "_unzipped")
        with zipfile.ZipFile(county_zip, 'r') as zip_ref:
            zip_ref.extractall(county_dir)
            
        for root, dirs, files in os.walk(county_dir):
            for xml_file in files:
                if xml_file.endswith(".xml"):
                    layer_code = xml_file.split("_OT_")[-1].replace(".xml", "").lower()
                    table_name = f"bdot_{layer_code}"
                    process_layer_pyogrio(os.path.join(root, xml_file), None, table_name, chunk_size=50000)
                    
        shutil.rmtree(county_dir)
    shutil.rmtree(bdot_tmp)

    # 3. EGiB
    print("\n🏘️ Importing EGiB & Transactions (Using Native SQLite)...")
    gpkg_zip = "raw_maps/14.gpkg.zip"
    gpkg_path = "raw_maps/14.gpkg"
    
    if not os.path.exists(gpkg_path):
        print("Unzipping 14.gpkg...")
        with zipfile.ZipFile(gpkg_zip, 'r') as zip_ref:
            zip_ref.extractall("raw_maps/")
            
    # Process only the specific tables we need using native sqlite stream
    process_table_sqlite_stream(gpkg_path, "dzialki", batch_size=20000)
    process_table_sqlite_stream(gpkg_path, "transakcje", batch_size=20000)
    
    # Post-process: Create Spatial Index
    print("\n🏗️ Creating Spatial Indexes...")
    with engine.begin() as conn:
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_dzialki_geom ON dzialki USING GIST (geom);"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_transakcje_geometry ON transakcje USING GIST (geometry);"))
        
    if os.path.exists(gpkg_path):
        os.unlink(gpkg_path)

    print("\n✅ ALL IMPORTS FULLY COMPLETE!")

if __name__ == "__main__":
    main()
