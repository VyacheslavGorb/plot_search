import os
os.environ["PREFECT_EXPERIMENTAL_ENABLE_EVENTS_CLIENT"] = "false"
os.environ["PREFECT_LOGGING_LEVEL"] = "CRITICAL"
os.environ["PREFECT_API_URL"] = ""

import logging
logging.getLogger("prefect").setLevel(logging.CRITICAL)
logging.getLogger("prefect.events.utilities").setLevel(logging.CRITICAL)

from flows.spatial import spatial_flow
from flows.router import run_routing_flow
from flows.scorer import run_scoring_flow

print("Running Spatial Flow...")
spatial_flow()

print("Running Routing Flow...")
run_routing_flow()

print("Running Scoring Flow...")
run_scoring_flow()
