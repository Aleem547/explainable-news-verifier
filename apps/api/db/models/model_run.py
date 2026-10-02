from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from apps.api.db.enums import PredictionTask


class ModelRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "model_runs"

    model_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )

    model_version: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )

    task: Mapped[PredictionTask] = mapped_column(
        SQLEnum(PredictionTask, name="prediction_task"),
        nullable=False,
        index=True,
    )

    framework: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )

    mlflow_run_id: Mapped[str | None] = mapped_column(
        String(255),
        unique=True,
        nullable=True,
    )

    artifact_uri: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
    )

    dataset_version: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    git_commit_sha: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    parameters: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    metrics: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    is_production: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
