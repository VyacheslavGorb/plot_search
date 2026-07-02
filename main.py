import os
# Suppress Prefect telemetry noise when running ephemeral local server
os.environ["PREFECT_EXPERIMENTAL_ENABLE_EVENTS_CLIENT"] = "false"
os.environ["PREFECT_LOGGING_LEVEL"] = "ERROR"

from prefect import flow
from flows.scraper import scrape_flow
from flows.parser import parse_flow
from flows.geocoder import geocode_flow
from flows.spatial import spatial_flow
from database import init_db

@flow(name="Master Plot Search Pipeline")
def master_pipeline(mode="incremental"):
    print(f"Initializing database...")
    init_db()
    
    print(f"\n====================================")
    print(f"Executing Scraper Flow (Mode: {mode})")
    print(f"====================================")
    scrape_flow(mode=mode)
    
    print(f"\n====================================")
    print(f"Executing Parser Flow")
    print(f"====================================")
    parse_flow()
    
    print(f"\n====================================")
    print(f"Executing Geocoder Flow")
    print(f"====================================")
    geocode_flow()

    print(f"\n====================================")
    print(f"Executing Spatial Filtering Flow")
    print(f"====================================")
    spatial_flow()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run the plot search pipeline.")
    parser.add_argument("--mode", type=str, choices=["incremental", "full"], default="incremental",
                        help="Scraping mode (default: incremental)")
    args = parser.parse_args()
    
    master_pipeline(mode=args.mode)
