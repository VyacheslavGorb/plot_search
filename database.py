from sqlalchemy import create_engine, Column, String, Float, Boolean, Text, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
import datetime
import enum

DATABASE_URL = "postgresql://postgres:password@localhost:5432/plot_search"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class StatusEnum(str, enum.Enum):
    NEW = "NEW"
    PARSED = "PARSED"
    GEOCODED = "GEOCODED"
    FAILED_PARSING = "FAILED_PARSING"
    FAILED_GEOCODING = "FAILED_GEOCODING"

class RawListing(Base):
    __tablename__ = "raw_listings"

    id = Column(String, primary_key=True, index=True)
    source_url = Column(String, unique=True, index=True, nullable=False)
    title = Column(String)
    description = Column(Text)
    raw_characteristics = Column(Text)
    price = Column(Float, nullable=True)
    area = Column(Float, nullable=True)
    location_lat = Column(Float, nullable=True)
    location_lon = Column(Float, nullable=True)
    is_exact_location = Column(Boolean, default=False)
    images = Column(JSONB, nullable=True)
    advertiser_type = Column(String, nullable=True)
    
    status = Column(SQLEnum(StatusEnum), default=StatusEnum.NEW)
    scraped_at = Column(DateTime, default=datetime.datetime.utcnow)

    parsed_listing = relationship("ParsedListing", back_populates="raw_listing", uselist=False)

class ParsedListing(Base):
    __tablename__ = "parsed_listings"

    id = Column(String, ForeignKey("raw_listings.id"), primary_key=True)
    parcel_number = Column(String, nullable=True)
    media = Column(JSONB, nullable=True)
    
    status = Column(SQLEnum(StatusEnum), default=StatusEnum.NEW)
    parsed_at = Column(DateTime, default=datetime.datetime.utcnow)

    raw_listing = relationship("RawListing", back_populates="parsed_listing")
    geocoded_parcel = relationship("GeocodedParcel", back_populates="parsed_listing", uselist=False)

class GeocodedParcel(Base):
    __tablename__ = "geocoded_parcels"

    id = Column(String, ForeignKey("parsed_listings.id"), primary_key=True)
    teryt = Column(String, nullable=True)
    polygon_wkt = Column(Text, nullable=True)
    is_unsubdivided = Column(Boolean, nullable=True)
    location_hierarchy = Column(JSONB, nullable=True)
    
    geocoded_at = Column(DateTime, default=datetime.datetime.utcnow)

    parsed_listing = relationship("ParsedListing", back_populates="geocoded_parcel")

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
