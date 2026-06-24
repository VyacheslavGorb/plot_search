from pydantic import BaseModel, Field
from typing import List, Optional

class MediaAvailability(BaseModel):
    electricity: Optional[bool] = Field(None, description="Is electricity available on or near the plot?")
    water: Optional[bool] = Field(None, description="Is water (mains) available?")
    gas: Optional[bool] = Field(None, description="Is gas available?")
    sewage: Optional[bool] = Field(None, description="Is sewage (kanalizacja) available? Exclude szambo/septic tanks.")
    telecom: Optional[bool] = Field(None, description="Is internet/fiber optic/telecom available?")

class LLMExtraction(BaseModel):
    parcel_number: Optional[str] = Field(None, description="The exact parcel number (e.g., '186', '123/4') found in the text. If multiple parcel numbers are found, extract only the primary one.")
    media: Optional[MediaAvailability] = Field(None, description="Details about utility connections")

class ParsedListing(LLMExtraction):
    # Core Identity
    id: str
    source_url: str
    scraped_at: str
    
    # Financials & Sizing
    price: Optional[float] = Field(None, description="Total price in PLN")
    area: Optional[float] = Field(None, description="Total area in square meters")
    
    location: dict
    is_exact_location: bool
    advertiser_type: str
