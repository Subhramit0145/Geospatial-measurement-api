import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.database import Base


def _generate_id() -> str:
    """Short readable identifier (first 12 hex chars of a uuid4)."""
    return uuid.uuid4().hex[:12]


class GeoFile(Base):
    """
    Represents an uploaded geospatial file and its top-level metadata.
    """

    __tablename__ = "geo_files"

    id = Column(String(12), primary_key=True, default=_generate_id)
    filename = Column(String(255), nullable=False)
    original_crs = Column(String(64), nullable=True)
    feature_count = Column(Integer, default=0)
    status = Column(String(20), default="PENDING")  # PENDING | PROCESSING | COMPLETED | FAILED
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    features = relationship(
        "Feature",
        back_populates="geo_file",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<GeoFile id={self.id} filename={self.filename} status={self.status}>"


class Feature(Base):
    """
    One geometric feature extracted from a GeoFile.
    Stores the geometry as WKT, its type, any measurement value,
    and the original properties as a JSON string.
    """

    __tablename__ = "features"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(String(12), ForeignKey("geo_files.id"), nullable=False)
    feature_index = Column(Integer, nullable=False)
    geometry_type = Column(String(50), nullable=False)
    geometry_wkt = Column(Text, nullable=False)
    measurement_value = Column(Float, nullable=True)
    measurement_unit = Column(String(20), nullable=True)   # "sq_meters" | "meters" | null
    measurement_type = Column(String(20), nullable=True)   # "area" | "length" | null
    projected_crs = Column(String(64), nullable=True)      # CRS used for measurement
    properties_json = Column(Text, nullable=True)           # original attributes as JSON

    geo_file = relationship("GeoFile", back_populates="features")

    def __repr__(self) -> str:
        return (
            f"<Feature idx={self.feature_index} type={self.geometry_type} "
            f"measurement={self.measurement_value}>"
        )
