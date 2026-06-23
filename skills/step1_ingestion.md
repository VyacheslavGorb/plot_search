---
name: step1_ingestion
description: Technical specification and implementation details for Phase 1 - Multi-Source Ingestion & Normalization.
triggers:
  - "how does ingestion work"
  - "implement phase 1"
  - "show the scraping logic"
---

# Phase 1: Multi-Source Ingestion & Normalization

This document details the implementation of the first phase of the pipeline. The goal is to scrape real estate listings, extract critical data (especially the parcel number and municipality), and normalize the data into a standard schema for subsequent spatial analysis.

## 1. Subflow Overview

This phase is implemented as a **Prefect Subflow**. This allows ingestion tasks to run, fail, and retry independently from the complex spatial calculations in later phases.

**Prefect Flow:** `ingest_and_normalize_listings`
**Input:** A list of listing URLs or a search page URL.
**Output:** Database records inserted into the `normalized_listings` table.

**Idempotency & State:**
The ingestion step is strictly idempotent. Before scraping a listing, the pipeline checks the `raw_listings` table by `source_url`. If a record exists and its status indicates it has already been parsed or permanently failed, it is skipped. Entities that failed on a particular step are not processed further. Only new URLs or those marked explicitly for retry are processed.

## 2. Component Details

### 2.1 Playwright Stealth Scraper (Task)
To avoid anti-bot protections (like Cloudflare on Otodom/OLX), the scraper connects to an already-running local instance of Google Chrome opened with a remote debugging port.

**Implementation Steps:**
1. **Connect to Chrome:** `playwright.connect_over_cdp("http://localhost:9222")`
2. **Navigate:** Open the listing URL.
3. **Extract Metadata:** Pull price, declared area, and the main description text.
4. **Download Images:** Find image URLs and download them to `data/images/{listing_id}/`.
5. **Save Raw HTML:** Save the page source to `data/raw/{listing_id}.html` for debugging purposes.
6. **Persist:** Insert the raw data into the `raw_listings` table.

### 2.2 Text Parsing via Local LLM (Task)
Extracting the parcel number (`numer działki`) and municipality (`gmina`) from unstructured text is complex. We use a local LLM via Ollama.

**Implementation Steps:**
1. **Query Ollama:** Send the `raw_text` to the local Ollama endpoint (`http://localhost:11434/api/generate`).
2. **Prompt Design:** Ask the LLM to strictly extract the parcel number and gmina in a JSON format.
   * *Example prompt:* "Extract the parcel number (numer działki) and municipality (gmina) from the following Polish real estate listing. Return ONLY a JSON object: `{\"parcel_number\": \"...\", \"gmina\": \"...\"}`. If not found, return nulls."
3. **Parse Result:** If a valid parcel number is found, proceed to Normalization. If not, trigger the OCR Fallback.

### 2.3 OCR Fallback with PaddleOCR (Task)
If the seller put the parcel number in a screenshot or map image rather than the text, we scan the downloaded images. PaddleOCR is used instead of EasyOCR for better accuracy and performance.

**Implementation Steps:**
1. **Condition:** Only run if `extracted_parcel_number` is null after LLM parsing.
2. **Process Images:** Iterate through images in `data/images/{listing_id}/`.
3. **Execute PaddleOCR:** Run optical character recognition on each image.
4. **Pattern Matching:** Use Regex to look for standard Polish parcel number formats (e.g., `123/4`, `141201_1.0001.123`) in the OCR output.
5. **Early Exit:** Stop processing images as soon as a valid parcel number is found.

### 2.4 Normalization & Storage (Task)
Consolidate the findings and store them in a standard format, decoupled from the source portal.

**Implementation Steps:**
1. **Map Data:** Combine the scraped metadata (price, area) with the extracted entities (`parcel_number`, `gmina`).
2. **Record Extraction Method:** Note whether the parcel number was found via `llm_text` or `ocr_fallback`.
3. **Database Insert:** Save the record to the `normalized_listings` table.
4. **Set Status:** Set the status to `pending_geometry` so Phase 2 knows this listing is ready for ULDK API lookup.

## 3. Error Handling & Retries
- **Playwright Timeouts:** Configure Prefect task retries for network timeouts during scraping.
- **LLM Hallucinations:** Validate the LLM JSON output. If it fails parsing or hallucinated a non-existent format, mark `extraction_method` as failed and move to OCR.
- **Missing Data:** If both LLM and OCR fail to find a parcel number, the listing cannot be processed automatically. Set the `normalized_listings` status to `failed_extraction` (requires manual review).
