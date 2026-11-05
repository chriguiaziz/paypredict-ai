"""Tables d'authentification : roles, users."""
import uuid
from datetime import datetime
from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base, created_at_col, uuid_pk
ROLE_NAMES = ("admin", "analyst", "viewer")
class Role(Base):
    __tablename__ = "roles"
    role_id: Mapped[uuid.UUID] = uuid_pk()
    role_name: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(200))
class User(Base):
    __tablename__ = "users"
    user_id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(300), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(
    UUID(as_uuid=True), ForeignKey("roles.role_id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = created_at_col()
    role: Mapped[Role] = relationship()