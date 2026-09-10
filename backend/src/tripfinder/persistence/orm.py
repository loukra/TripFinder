"""SQLAlchemy table definitions (plan §3.1, §10 Phase 3).

Two tables: ``research`` persists the domain ``Research`` aggregate as a
whole (config/status/statistics/results/weak_results/diagnostics as JSONB);
``research_jobs`` is the Postgres-backed work queue (plan §1 — no Redis).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ResearchRow(Base):
    __tablename__ = "research"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    original_query: Mapped[str] = mapped_column(Text)
    normalized_query: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32))
    research_config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    statistics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    weak_results: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    diagnostics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    clarification: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    pending_plan: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    resume_plan: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class ResearchJobRow(Base):
    __tablename__ = "research_jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    research_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("research.id"))
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
