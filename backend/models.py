from datetime import datetime
from typing import Any
from sqlalchemy import Integer, String, Text, DateTime, ForeignKey, JSON, BigInteger, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    name: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(200))
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    login_token: Mapped[str | None] = mapped_column(String(128), unique=True, index=True)
    login_token_expires: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    samples: Mapped[list["Sample"]] = relationship("Sample", back_populates="owner")


class Sample(Base):
    __tablename__ = "samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    substrate_material: Mapped[str | None] = mapped_column(String(100))
    substrate_dimensions: Mapped[str | None] = mapped_column(String(100))
    film_material: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(100))
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    owner: Mapped["User | None"] = relationship("User", back_populates="samples")
    process_steps: Mapped[list["ProcessStep"]] = relationship(
        "ProcessStep", back_populates="sample",
        order_by="ProcessStep.step_order",
        cascade="all, delete-orphan",
    )
    analyses: Mapped[list["Analysis"]] = relationship(
        "Analysis", back_populates="sample",
        order_by="Analysis.performed_at",
        cascade="all, delete-orphan",
    )


class ProcessStepType(Base):
    __tablename__ = "process_step_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    parameter_schema: Mapped[list[dict] | None] = mapped_column(JSON)

    steps: Mapped[list["ProcessStep"]] = relationship("ProcessStep", back_populates="step_type")


class ProcessStep(Base):
    __tablename__ = "process_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sample_id: Mapped[int] = mapped_column(ForeignKey("samples.id", ondelete="CASCADE"))
    step_type_id: Mapped[int] = mapped_column(ForeignKey("process_step_types.id"))
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    parameters: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    notes: Mapped[str | None] = mapped_column(Text)
    performed_by: Mapped[str | None] = mapped_column(String(100))
    performed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    sample: Mapped["Sample"] = relationship("Sample", back_populates="process_steps")
    step_type: Mapped["ProcessStepType"] = relationship("ProcessStepType", back_populates="steps")


class AnalysisType(Base):
    __tablename__ = "analysis_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    parameter_schema: Mapped[list[dict] | None] = mapped_column(JSON)

    analyses: Mapped[list["Analysis"]] = relationship("Analysis", back_populates="analysis_type")


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sample_id: Mapped[int] = mapped_column(ForeignKey("samples.id", ondelete="CASCADE"))
    analysis_type_id: Mapped[int] = mapped_column(ForeignKey("analysis_types.id"))
    parameters: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    notes: Mapped[str | None] = mapped_column(Text)
    performed_by: Mapped[str | None] = mapped_column(String(100))
    performed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    sample: Mapped["Sample"] = relationship("Sample", back_populates="analyses")
    analysis_type: Mapped["AnalysisType"] = relationship("AnalysisType", back_populates="analyses")


class Attachment(Base):
    """A file attached to a process step or analysis."""
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'step' | 'analysis'
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    mime_type: Mapped[str | None] = mapped_column(String(100))
    uploaded_by: Mapped[str | None] = mapped_column(String(100))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
