from datetime import date, datetime
from typing import Any
from sqlalchemy import Integer, String, Text, Date, DateTime, ForeignKey, JSON, BigInteger, Boolean, Float, UniqueConstraint, func
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
    # Used in sample IDs (e.g. ASS-2026-001); 2–4 capital letters, unique.
    initials: Mapped[str | None] = mapped_column(String(4), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    samples: Mapped[list["Sample"]] = relationship("Sample", back_populates="owner", foreign_keys="Sample.owner_id")

    @property
    def display_name(self) -> str:
        return self.name or self.username


SAMPLE_TYPES = {"thin_film": "Thin film", "bulk": "Bulk", "commercial": "Commercial", "collaboration": "Collaboration"}
POLISHING = {"single": "Single side", "double": "Double side", "none": "Unpolished"}


class Substrate(Base):
    """Shared library of substrates that thin-film and bulk samples are made from."""
    __tablename__ = "substrates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    material: Mapped[str] = mapped_column(String(100), nullable=False)
    orientation: Mapped[str | None] = mapped_column(String(50))
    thickness_um: Mapped[float | None] = mapped_column(Float)
    polishing: Mapped[str | None] = mapped_column(String(20))   # key of POLISHING
    size: Mapped[str | None] = mapped_column(String(100))       # e.g. 2-inch wafer
    supplier: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    created_by: Mapped["User | None"] = relationship("User", lazy="selectin")


class Collaborator(Base):
    """A university or research centre that sends us samples. Its code numbers
    their samples the way a researcher's initials do (e.g. UMIN-2026-001)."""
    __tablename__ = "collaborators"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # 2–6 capital letters; unique, and never the same as a researcher's initials
    code: Mapped[str] = mapped_column(String(6), unique=True, nullable=False)
    country: Mapped[str | None] = mapped_column(String(100))
    contact_name: Mapped[str | None] = mapped_column(String(120))
    contact_email: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    created_by: Mapped["User | None"] = relationship("User", lazy="selectin")


class Sample(Base):
    __tablename__ = "samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Generated, never changes: <researcher initials>-<year>-<number>, and
    # pieces append -A, -B, -REF (pieces of pieces -1, -2, …). See sample_ids.py.
    code: Mapped[str | None] = mapped_column(String(60), unique=True)
    # Optional personal description
    label: Mapped[str | None] = mapped_column(String(100), index=True)
    sample_type: Mapped[str] = mapped_column(String(20), default="thin_film", server_default="thin_film", nullable=False)
    substrate_id: Mapped[int | None] = mapped_column(ForeignKey("substrates.id"), index=True)
    external_id: Mapped[str | None] = mapped_column(String(100))   # e.g. ID given by whoever cut a bulk piece
    collaborator_id: Mapped[int | None] = mapped_column(ForeignKey("collaborators.id"), index=True)  # collaboration samples
    supplier: Mapped[str | None] = mapped_column(String(120))      # commercial samples
    tags: Mapped[list[str] | None] = mapped_column(JSON)
    substrate_dimensions: Mapped[str | None] = mapped_column(String(100))
    film_material: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # Set when someone created the sample on the owner's behalf and the owner
    # hasn't confirmed it yet: the person who created it.
    requested_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    # Set when this sample is a piece cut from another: the parent's "Cut" step.
    # The piece inherits the parent's timeline up to that step.
    cut_step_id: Mapped[int | None] = mapped_column(
        ForeignKey("process_steps.id", use_alter=True, name="fk_samples_cut_step_id"), index=True)
    is_reference: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    owner: Mapped["User | None"] = relationship(
        "User", back_populates="samples", foreign_keys=[owner_id], lazy="selectin")
    requested_by: Mapped["User | None"] = relationship("User", foreign_keys=[requested_by_id], lazy="selectin")
    substrate: Mapped["Substrate | None"] = relationship("Substrate", lazy="selectin")
    collaborator: Mapped["Collaborator | None"] = relationship("Collaborator", lazy="selectin")
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

    @property
    def type_label(self) -> str:
        return SAMPLE_TYPES.get(self.sample_type, self.sample_type)

    @property
    def researcher(self) -> str | None:
        return self.owner.display_name if self.owner else None

    @property
    def substrate_material(self) -> str | None:
        return self.substrate.material if self.substrate else None

    @property
    def title(self) -> str:
        """How the sample is referred to in links and headings."""
        return self.code or f"#{self.id}"


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
    # Position in the sample's timeline, shared with Analysis.position.
    position: Mapped[int | None] = mapped_column(Integer)
    parameters: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    notes: Mapped[str | None] = mapped_column(Text)
    # Who did it: a user (who can then see and edit this entry, even without
    # access to the sample), or a name typed in for someone without an account.
    performer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    performed_by: Mapped[str | None] = mapped_column(String(100))
    location: Mapped[str | None] = mapped_column(String(120))   # where it was done (shared list "location")
    # Entries added to several samples at once share a run id
    run_id: Mapped[str | None] = mapped_column(String(32), index=True)
    performed_at: Mapped[date | None] = mapped_column(Date)   # the day only; order within a day is `position`
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    sample: Mapped["Sample"] = relationship("Sample", back_populates="process_steps", foreign_keys=[sample_id])
    step_type: Mapped["ProcessStepType"] = relationship("ProcessStepType", back_populates="steps")
    performer: Mapped["User | None"] = relationship("User", lazy="selectin")

    @property
    def performer_name(self) -> str | None:
        return self.performer.display_name if self.performer else self.performed_by


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
    # Who did it: a user (who can then see and edit this entry, even without
    # access to the sample), or a name typed in for someone without an account.
    performer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    performed_by: Mapped[str | None] = mapped_column(String(100))
    location: Mapped[str | None] = mapped_column(String(120))   # where it was done (shared list "location")
    # Entries added to several samples at once share a run id
    run_id: Mapped[str | None] = mapped_column(String(32), index=True)
    performed_at: Mapped[date | None] = mapped_column(Date)   # the day only; order within a day is `position`
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    sample: Mapped["Sample"] = relationship("Sample", back_populates="analyses")
    analysis_type: Mapped["AnalysisType"] = relationship("AnalysisType", back_populates="analyses")
    performer: Mapped["User | None"] = relationship("User", lazy="selectin")

    @property
    def performer_name(self) -> str | None:
        return self.performer.display_name if self.performer else self.performed_by


class Attachment(Base):
    """A file attached to a process step or analysis."""
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)  # step | analysis | sample | substrate
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    mime_type: Mapped[str | None] = mapped_column(String(100))
    # Small JPEG preview for images (created on upload, or on first view)
    thumbnail_filename: Mapped[str | None] = mapped_column(String(255))
    uploaded_by: Mapped[str | None] = mapped_column(String(100))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ChoiceOption(Base):
    """A value in one of the shared dropdowns on the step and analysis forms
    (machines, targets, atmospheres, where it was done, …). A list grows when
    someone types a new value; admins can remove values."""
    __tablename__ = "choice_options"
    __table_args__ = (UniqueConstraint("list", "value"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    list: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    value: Mapped[str] = mapped_column(String(200), nullable=False)
    # For equipment ("located" lists): where it is, e.g. INESC MN. The forms
    # only offer equipment at the place chosen under Where.
    location: Mapped[str | None] = mapped_column(String(120))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


SUGGESTION_KINDS = {"idea": "Idea", "problem": "Problem", "question": "Question"}


class Suggestion(Base):
    """Feedback from a user; admins reply and mark it solved."""
    __tablename__ = "suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="idea", nullable=False)  # key of SUGGESTION_KINDS
    text: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[str | None] = mapped_column(String(300))   # where it was submitted from
    solved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    solved_at: Mapped[datetime | None] = mapped_column(DateTime)
    # When the author last looked at it, to flag replies they haven't seen
    author_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User | None"] = relationship("User", lazy="selectin")
    replies: Mapped[list["SuggestionReply"]] = relationship(
        "SuggestionReply", back_populates="suggestion", order_by="SuggestionReply.id",
        cascade="all, delete-orphan", lazy="selectin",
    )

    @property
    def kind_label(self) -> str:
        return SUGGESTION_KINDS.get(self.kind, self.kind)


class SuggestionReply(Base):
    __tablename__ = "suggestion_replies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    suggestion_id: Mapped[int] = mapped_column(ForeignKey("suggestions.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    suggestion: Mapped["Suggestion"] = relationship("Suggestion", back_populates="replies")
    user: Mapped["User | None"] = relationship("User", lazy="selectin")
