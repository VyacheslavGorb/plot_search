---
name: step1_ingestion
description: Technical specification and implementation details for Phase 1 - Multi-Source Ingestion & Normalization.
triggers:
  - "how does ingestion work"
  - "implement phase 1"
  - "show the scraping logic"
---

# Phase 1: Multi-Source Ingestion & Normalization

This document details the implementation of the first phase of the pipeline. The goal is to scrape real estate listings, extract critical data (especially the parcel number), and normalize the data into a standard schema for subsequent spatial analysis.

## 1. Flow Overview

This phase is implemented using **Prefect Flows** and executed via `main.py`. This allows ingestion tasks to run, fail, and retry independently from the complex spatial calculations in later phases.

**Prefect Flows:** `scrape_flow` (scraper.py) and `parse_flow` (parser.py)
**Input:** A search page URL.
**Output:** Database records inserted into `raw_listings` and `parsed_listings`.

**Idempotency & State:**
The ingestion step is strictly idempotent. Before scraping a listing, the pipeline checks the `raw_listings` table by `source_url`. If a record exists, it skips scraping it (when running in `incremental` mode). Parsed listings are stored with `StatusEnum.NEW` until they are successfully processed by the geocoder.

## 2. Component Details

### 2.1 Playwright Stealth Scraper (`scrape_flow`)
To avoid anti-bot protections, the scraper connects to an already-running local instance of Google Chrome opened with a remote debugging port.

**Implementation Steps:**
1. **Connect to Chrome:** `playwright.connect_over_cdp("http://localhost:9222")`
2. **Navigate:** Open the search URL, handle pagination.
3. **Extract Metadata:** Pull price, declared area, text description, and characteristics from `__NEXT_DATA__` or DOM elements.
4. **Extract Image URLs:** Extract high-quality image URLs instead of downloading them directly to disk.
5. **Persist:** Insert the data into the `raw_listings` table using the `save_raw_listing` task.

### 2.2 Text Parsing via Local LLM (`parse_flow`)
Extracting the parcel number (`numer działki`) and utilities presence from unstructured text is handled via a local LLM (Ollama).

**Implementation Steps:**
1. **Query Ollama:** Send the `description` and `raw_characteristics` to the local Ollama endpoint (`http://localhost:11434/api/generate`) using the `qwen2.5:14b-instruct` model.
2. **Prompt Design:** Ask the LLM to extract the parcel number and media (water, electricity, gas, sewage) using a strict Pydantic JSON schema (`LLMExtraction`).
3. **Normalization:** The extracted parcel number is returned as a single nullable string.
4. **Database Insert:** Save the validated record to the `parsed_listings` table.
5. **Set Status:** Set the status to `StatusEnum.NEW` so the Geocoder flow knows this listing is ready for ULDK API lookup, and update the raw listing status to `PARSED`.

## 3. Error Handling & Retries
- **Playwright Timeouts:** The `save_raw_listing` task is configured with 3 retries and a 5-second delay to handle transient database or connectivity issues.
- **LLM Hallucinations:** The `parse_with_llm` task validates the LLM JSON output against the `LLMExtraction` Pydantic schema. It is configured with 3 retries. If parsing fails, the raw listing is marked as `FAILED_PARSING`.
