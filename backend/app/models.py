import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Integer, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base

def now():
    return datetime.now(timezone.utc)

def uid():
    return str(uuid.uuid4())

class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    repository_path: Mapped[str] = mapped_column(String(255), default="/sample-repo")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Pipeline(Base):
    __tablename__ = "pipelines"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    name: Mapped[str] = mapped_column(String(120))
    steps_config: Mapped[list] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    pipeline_id: Mapped[str] = mapped_column(ForeignKey("pipelines.id"), index=True)
    fixture: Mapped[str] = mapped_column(String(20), default="success")
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(String(100))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    jobs: Mapped[list["Job"]] = relationship(back_populates="run", cascade="all, delete-orphan", order_by="Job.step_order")

class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    step_order: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(40))
    command_label: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    exit_code: Mapped[int | None] = mapped_column(Integer)
    logs: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    run: Mapped[Run] = relationship(back_populates="jobs")
