import uuid
from typing import Optional

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, Boolean, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RoadSegment(Base):
    __tablename__ = "road_segments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    osm_way_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    geometry: Mapped[str] = mapped_column(Geometry(geometry_type="LINESTRING", srid=4326), nullable=False)
    highway_class: Mapped[str] = mapped_column(String, nullable=False)

    is_bridge: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    is_tunnel: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    graph_edge_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
