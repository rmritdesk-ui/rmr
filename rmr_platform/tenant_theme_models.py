from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TenantTheme(Base):
    """Tenant-scoped application branding.

    The public website theme remains in WebsiteSite. This model controls only
    the authenticated RMR Global workspace presentation.
    """

    __tablename__ = "tenant_themes"

    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    workspace_style: Mapped[str] = mapped_column(String(40), default="classic-blue", nullable=False)
    brand_name: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    primary_color: Mapped[str] = mapped_column(String(7), default="#315EFB", nullable=False)
    secondary_color: Mapped[str] = mapped_column(String(7), default="#F4F7FB", nullable=False)
    accent_color: Mapped[str] = mapped_column(String(7), default="#7C5CFC", nullable=False)
    font_family: Mapped[str] = mapped_column(String(40), default="system", nullable=False)
    logo_filename: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    logo_content_type: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    logo_original_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    updated_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
