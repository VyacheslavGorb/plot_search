import os
import json
import requests
from pathlib import Path
from schema import LLMExtraction, ParsedListing

# Config
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen2.5:14b-instruct"
RAW_DIR = Path("data/raw")
PARSED_DIR = Path("data/parsed")

PARSED_DIR.mkdir(parents=True, exist_ok=True)

SYSTEM_PROMPT = """You are an expert real estate data extractor. Your task is to extract structured data from the following real estate listing.

Rules:
1. Extract information explicitly mentioned in the TEXT (Description and Characteristics).
2. If information is missing, output null. DO NOT guess or hallucinate.
3. For media, look for keywords like "prąd", "woda", "szambo", "kanalizacja", "gaz". Remember that "szambo" (septic tank) means sewage is FALSE (sewage refers to municipal grid).
4. For parcel_number: look closely for any plot numbers, cadastral numbers, parcel numbers, id dzialki, numer dzialki mentioned in the description. Examples: "123/4", "nr 56", "nr ewidencyjny 12", "141207_5.0014.64". Return as a single string, or null if missing.
"""

def parse_listing_with_llm(listing_data):
    # Prepare the input text
    input_text = f"--- METADATA ---\n"
    input_text += f"ID: {listing_data.get('id')}\n"
    input_text += f"URL: {listing_data.get('source_url')}\n"
    input_text += f"Price: {listing_data.get('price')}\n"
    input_text += f"Area: {listing_data.get('area')}\n"
    input_text += f"Title: {listing_data.get('title')}\n\n"
    
    input_text += f"--- TEXT: DESCRIPTION ---\n"
    input_text += f"{listing_data.get('description', '')}\n\n"
    
    input_text += f"--- TEXT: CHARACTERISTICS ---\n"
    input_text += f"{listing_data.get('raw_characteristics', '')}\n\n"
    
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
    
    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=120)
        response.raise_for_status()
        result = response.json()
        
        parsed_json = json.loads(result.get("response", "{}"))
        return parsed_json
    except Exception as e:
        print(f"Error calling Ollama API: {e}")
        return None

def main():
    if not RAW_DIR.exists():
        print("Raw directory not found.")
        return
        
    json_files = list(RAW_DIR.glob("*.json"))
    print(f"Found {len(json_files)} raw listings.")
    
    for idx, file_path in enumerate(json_files):
        print(f"\n--- [{idx+1}/{len(json_files)}] Parsing {file_path.name} ---")
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        parsed_path = PARSED_DIR / file_path.name
        if parsed_path.exists():
            print("Already parsed, skipping.")
            continue
            
        parsed_data = parse_listing_with_llm(data)
        if parsed_data:
            # Merge with original data
            merged_data = data.copy()
            
            # The LLM extracted data overwrites or augments
            merged_data.update(parsed_data)
            
            # Validate with pydantic
            try:
                # This will cast fields and validate constraints
                validated_model = ParsedListing(**merged_data)
                
                with open(parsed_path, "w", encoding="utf-8") as out:
                    # dump as dict to keep JSON serializable formats
                    json.dump(validated_model.model_dump(), out, ensure_ascii=False, indent=2)
                print(f"✓ Successfully parsed and saved.")
            except Exception as e:
                print(f"Pydantic Validation Error: {e}")
                print(f"Raw Output: {parsed_data}")

if __name__ == "__main__":
    main()
