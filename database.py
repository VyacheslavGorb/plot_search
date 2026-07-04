from sqlalchemy import create_engine, Column, String, Float, Boolean, Text, DateTime, ForeignKey, Enum as SQLEnum, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
import datetime
import enum

DATABASE_URL = "postgresql://postgres:password@localhost:5432/plot_search"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class TelegramUserState(Base):
    __tablename__ = "telegram_user_states"
    user_id = Column(String, primary_key=True)
    last_menu_msg_id = Column(Integer, nullable=True)
    last_notified_count = Column(Integer, default=0)

class ParcelReview(Base):
    __tablename__ = "parcel_reviews"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, index=True, nullable=False)
    listing_id = Column(String, ForeignKey("parsed_listings.id"), nullable=False)
    rating = Column(String, nullable=False)
    reviewed_at = Column(DateTime, default=datetime.datetime.utcnow)

class StatusEnum(str, enum.Enum):
    NEW = "NEW"
    PARSED = "PARSED"
    GEOCODED = "GEOCODED"
    SPATIALLY_VALIDATED = "SPATIALLY_VALIDATED"
    ROUTED = "ROUTED"
    FAILED_PARSING = "FAILED_PARSING"
    FAILED_GEOCODING = "FAILED_GEOCODING"
    FAILED_SPATIAL_RULES = "FAILED_SPATIAL_RULES"
    FAILED_ROUTING = "FAILED_ROUTING"
    INACTIVE = "INACTIVE"

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
    spatial_evaluation = relationship("SpatialEvaluation", back_populates="parsed_listing", uselist=False, cascade="all, delete-orphan")
    route_evaluations = relationship("RouteEvaluation", back_populates="parsed_listing", cascade="all, delete-orphan")

class GeocodedParcel(Base):
    __tablename__ = "geocoded_parcels"

    id = Column(String, ForeignKey("parsed_listings.id"), primary_key=True)
    teryt = Column(String, nullable=True)
    polygon_wkt = Column(Text, nullable=True)
    is_unsubdivided = Column(Boolean, nullable=True)
    location_hierarchy = Column(JSONB, nullable=True)
    
    geocoded_at = Column(DateTime, default=datetime.datetime.utcnow)

    parsed_listing = relationship("ParsedListing", back_populates="geocoded_parcel")

class SpatialEvaluation(Base):
    __tablename__ = "spatial_evaluations"

    id = Column(String, ForeignKey("parsed_listings.id"), primary_key=True)
    geometry_category = Column(String, nullable=False) # A_PRECISE, B_UNSUBDIVIDED, C_POINT, D_NONE
    
    # Measurements
    forest_distance_m = Column(Float, nullable=True)
    usable_building_area_m2 = Column(Float, nullable=True)
    fits_200m2_house = Column(Boolean, nullable=True)
    intersects_flood_zone = Column(Boolean, nullable=True)
    power_line_distance_m = Column(Float, nullable=True)
    railway_distance_m = Column(Float, nullable=True)
    major_road_distance_m = Column(Float, nullable=True)
    
    # Utilities (from KIUT color analysis)
    has_water = Column(Boolean, nullable=True)
    has_sewage = Column(Boolean, nullable=True)
    has_gas = Column(Boolean, nullable=True)
    has_electricity = Column(Boolean, nullable=True)
    has_telecom = Column(Boolean, nullable=True)

    water_distance_m = Column(Float, nullable=True)
    
    # Amenities & Infrastructure Distances
    distance_to_train_station_m = Column(Float, nullable=True)
    distance_to_school_m = Column(Float, nullable=True)
    distance_to_kindergarten_m = Column(Float, nullable=True)
    distance_to_nursery_m = Column(Float, nullable=True)
    distance_to_hospital_m = Column(Float, nullable=True)
    distance_to_drainage_m = Column(Float, nullable=True)
    
    evaluated_at = Column(DateTime, default=datetime.datetime.utcnow)

    parsed_listing = relationship("ParsedListing", back_populates="spatial_evaluation")

class RouteEvaluation(Base):
    __tablename__ = "route_evaluations"

    id = Column(String, primary_key=True, index=True)
    listing_id = Column(String, ForeignKey("parsed_listings.id"), index=True, nullable=False)
    target_name = Column(String, nullable=False) # e.g. "VARSO_TOWER", "WARSAW_HUB"
    route_mode = Column(String, nullable=False) # e.g. "CAR_ONLY", "CAR_TRANSIT", "BICYCLE_TRANSIT"
    
    time_0800_mins = Column(Float, nullable=True)
    time_1400_mins = Column(Float, nullable=True)
    time_1700_mins = Column(Float, nullable=True)
    
    evaluated_at = Column(DateTime, default=datetime.datetime.utcnow)

    parsed_listing = relationship("ParsedListing", back_populates="route_evaluations")

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
