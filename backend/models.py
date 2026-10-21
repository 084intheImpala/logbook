from datetime import datetime
from typing import Any
from sqlalchemy import Integer, String, Text, DateTime, ForeignKey, JSON, BigInteger, Boolean, UniqueConstraint, func
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
    # Names may repeat; the integer id is the unique identifier.
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    tags: Mapped[list[str] | None] = mapped_column(JSON)
    substrate_material: Mapped[str | None] = mapped_column(String(100))
    substrate_dimensions: Mapped[str | None] = mapped_column(String(100))
    film_material: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(100))
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # Set when this sample is a piece cut from another: the parent's "Cut" step.
    # The piece inherits the parent's timeline up to that step.
    cut_step_id: Mapped[int | None] = mapped_column(
        ForeignKey("process_steps.id", use_alter=True, name="fk_samples_cut_step_id"), index=True)
    is_reference: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    owner: Mapped["User | None"] = relationship("User", back_populates="samples")
    process_steps: Mapped[list["ProcessStep"]] = relationship(
        "ProcessStep", back_populates="sample", foreign_keys="ProcessStep.sample_id",
        order_by="ProcessStep.position",
        cascade="all, delete-orphan",
    )
    analyses: Mapped[list["Analysis"]] = relationship(
        "Analysis", back_populates="sample",
        order_by="Analysis.position",
        cascade="all, delete-orphan",
    )
    # Always loaded: permission checks need them wherever a sample is used.
    shares: Mapped[list["SampleShare"]] = relationship(
        "SampleShare", back_populates="sample", lazy="selectin",
        cascade="all, delete-orphan",
    )


class SampleShare(Base):
    """Grants a user access to another user's sample (view, or view + edit)."""
    __tablename__ = "sample_shares"
    __table_args__ = (UniqueConstraint("sample_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sample_id: Mapped[int] = mapped_column(ForeignKey("samples.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    can_edit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    sample: Mapped["Sample"] = relationship("Sample", back_populates="shares")
    user: Mapped["User"] = relationship("User", lazy="selectin")


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
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)  # legacy; mirrors position
    # Position in the sample's timeline, shared with Analysis.position.
    position: Mapped[int | None] = mapped_column(Integer)
    parameters: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    notes: Mapped[str | None] = mapped_column(Text)
    performed_by: Mapped[str | None] = mapped_column(String(100))
    performed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    sample: Mapped["Sample"] = relationship("Sample", back_populates="process_steps", foreign_keys=[sample_id])
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
    # Position in the sample's timeline, shared with ProcessStep.position.
    position: Mapped[int | None] = mapped_column(Integer)
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
