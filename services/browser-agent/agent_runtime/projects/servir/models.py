"""
Modelos SQLAlchemy exclusivos del proyecto SERVIR.
Eliminar projects/servir/ no afecta ningun otro proyecto.
La tabla 'servir_ofertas' es creada por schema/001_servir_ofertas.sql.
"""
import uuid
from datetime import datetime

from sqlalchemy import Text, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base


class ServirOferta(Base):
    __tablename__ = "servir_ofertas"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    numero_convocatoria: Mapped[str] = mapped_column(Text, nullable=False)
    entidad: Mapped[str] = mapped_column(Text, nullable=False)
    titulo: Mapped[str | None] = mapped_column(Text)
    ubicacion: Mapped[str | None] = mapped_column(Text)
    vacantes: Mapped[str | None] = mapped_column(Text)
    remuneracion: Mapped[str | None] = mapped_column(Text)
    fecha_inicio: Mapped[str | None] = mapped_column(Text)
    fecha_fin: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )
    removed_by_user: Mapped[bool] = mapped_column(nullable=False, default=False)
    removed_by_user_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
