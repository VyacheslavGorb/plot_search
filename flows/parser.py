import json
import requests
from prefect import flow, task
from schema import LLMExtraction
from database import SessionLocal, RawListing, ParsedListing, StatusEnum

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen2.5:14b-instruct"

SYSTEM_PROMPT = """You are an expert real estate data extractor. Your task is to extract structured data from the following real estate listing.

Rules:
1. Extract information explicitly mentioned in the TEXT (Description and Characteristics).
2. If information is missing, output null. DO NOT guess or hallucinate.
3. For media, look for keywords like "prąd", "woda", "szambo", "kanalizacja", "gaz". Remember that "szambo" (septic tank) means sewage is FALSE (sewage refers to municipal grid).
4. For parcel_number: look closely for any plot numbers, cadastral numbers, parcel numbers, id dzialki, numer dzialki mentioned in the description. Examples: "123/4", "nr 56", "nr ewidencyjny 12", "141207_5.0014.64". Return as a single string, or null if missing.
"""

@task(retries=3, retry_delay_seconds=2)
def parse_with_llm(raw_listing: dict) -> dict:
    input_text = f"--- METADATA ---\n"
    input_text += f"ID: {raw_listing['id']}\n"
    input_text += f"URL: {raw_listing['source_url']}\n"
    input_text += f"Price: {raw_listing['price']}\n"
    input_text += f"Area: {raw_listing['area']}\n"
    input_text += f"Title: {raw_listing['title']}\n\n"
    
    input_text += f"--- TEXT: DESCRIPTION ---\n"
    input_text += f"{raw_listing['description']}\n\n"
    
    input_text += f"--- TEXT: CHARACTERISTICS ---\n"
    input_text += f"{raw_listing['raw_characteristics']}\n\n"
    
    schema = LLMExtraction.model_json_schema()
    
    payload = {
        "model": MODEL_NAME,
        "system": SYSTEM_PROMPT,
        "prompt": input_text,
        "stream": False,
        "format": schema,
        "options": {
            "temperature": 0.0
        }
    }
    
    response = requests.post(OLLAMA_URL, json=payload, timeout=120)
    response.raise_for_status()
    result = response.json()
    return json.loads(result.get("response", "{}"))

@flow(name="Parse Listings with LLM")
def parse_flow():
    db = SessionLocal()
    try:
        new_listings = db.query(RawListing).filter(RawListing.status == StatusEnum.NEW).all()
        print(f"Found {len(new_listings)} NEW listings to parse.")
        
        for idx, listing in enumerate(new_listings):
            print(f"--- [{idx+1}/{len(new_listings)}] Parsing {listing.id} ---")
            
            raw_dict = {
                "id": listing.id,
                "source_url": listing.source_url,
                "price": listing.price,
                "area": listing.area,
                "title": listing.title,
                "description": listing.description,
                "raw_characteristics": listing.raw_characteristics
            }
            
            try:
                parsed_data = parse_with_llm(raw_dict)
                validated = LLMExtraction(**parsed_data)
                
                parsed_record = ParsedListing(
                    id=listing.id,
                    parcel_number=validated.parcel_number,
                    media=validated.media.model_dump() if validated.media else None,
                    status=StatusEnum.NEW
                )
                db.add(parsed_record)
                listing.status = StatusEnum.PARSED
                db.commit()
                print(f"  ✓ Successfully parsed and saved.")
            except Exception as e:
                db.rollback()
                print(f"  ✗ Failed to parse: {e}")
                listing.status = StatusEnum.FAILED_PARSING
                db.commit()
                
    finally:
        db.close()

if __name__ == "__main__":
    parse_flow()
