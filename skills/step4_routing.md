---
name: step4_routing
description: Technical specification and implementation details for Phase 4 - Multimodal Routing & Commute Profiling.
triggers:
  - "how does routing work"
  - "implement phase 4"
  - "what is OTP"
---

# Phase 4: Multimodal Routing & Commute Profiling

This phase calculates highly accurate, base multimodal commute times for spatially validated parcels using a local OpenTripPlanner (OTP) Docker container. This serves as a massive, cost-free pre-filter before executing the expensive Google Maps Live Traffic checks in Phase 5.

## 1. Scope & Strategy

*   **Targets:** Commute times are calculated to two specific points in central Warsaw:
    *   **Varso Tower** (Chmielna 69): `lat: 52.2275, lon: 21.0003`
    *   **Warsaw Hub** (Rondo Daszyńskiego): `lat: 52.2285, lon: 20.9840`
*   **Modes:** Multimodal calculations spanning:
    *   `CAR_ONLY`
    *   `CAR_TRANSIT` (Drive-to-transit + Public Transit + Walk)
    *   `BICYCLE_TRANSIT` (Bike-to-transit + Public Transit + Walk)
*   **Time Horizons:** Calculations simulate peak commuting hours at `08:00`, `14:00`, and `17:00`.
*   **Pre-Condition:** Parcels must possess the `SPATIALLY_VALIDATED` status.

## 2. Implementation Status (COMPLETED)

### 2.1 Router Module (`flows/router.py`) - [x] COMPLETED
-   Constructs and executes GraphQL queries against the local OTP v2 endpoint (`http://localhost:8080/otp/routers/default/index/graphql`).
-   Calculates the true driving/transit durations for all 18 permutations (2 targets × 3 modes × 3 times) per parcel.
-   Updates the database `RouteEvaluation` table with the duration in minutes.

### 2.2 Multithreaded Orchestration - [x] COMPLETED
-   Because synchronous HTTP requests to OTP are painfully slow (~20+ minutes for 400+ parcels), `router.py` employs a `ThreadPoolExecutor`.
-   Configured with 15 concurrent worker threads, reducing processing time for hundreds of parcels down to a few minutes.
-   Integrates `tqdm` for terminal progress tracking.
-   Implements thread-safe SQLAlchemy `SessionLocal` instantiation within the worker threads.

### 2.3 Integration into `main.py` - [x] COMPLETED
-   The router is officially integrated into the master `main.py` orchestration script via `run_routing_flow()`.
-   Executes automatically after the spatial filtering phase.
