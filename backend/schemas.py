from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict


# ── Attachments ────────────────────────────────────────────────────────────────

class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    entity_type: str
    entity_id: int
    original_filename: str
    file_size: int | None
    mime_type: str | None
    uploaded_by: str | None
    uploaded_at: datetime


# ── Process step types ─────────────────────────────────────────────────────────

class ProcessStepTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str | None
    parameter_schema: list[dict] | None


# ── Process steps ──────────────────────────────────────────────────────────────

class ProcessStepCreate(BaseModel):
    step_type_id: int
    parameters: dict[str, Any] | None = None
    notes: str | None = None
    performed_by: str | None = None
    performed_at: datetime | None = None

class ProcessStepUpdate(BaseModel):
    parameters: dict[str, Any] | None = None
    notes: str | None = None
    performed_by: str | None = None
    performed_at: datetime | None = None

class ProcessStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sample_id: int
    position: int | None
    step_type: ProcessStepTypeOut
    parameters: dict[str, Any] | None
    notes: str | None
    performed_by: str | None
    performed_at: datetime | None
    created_at: datetime
    attachments: list[AttachmentOut] = []


# ── Analysis types ─────────────────────────────────────────────────────────────

class AnalysisTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str | None
    parameter_schema: list[dict] | None


# ── Analyses ───────────────────────────────────────────────────────────────────

class AnalysisCreate(BaseModel):
    analysis_type_id: int
    parameters: dict[str, Any] | None = None
    notes: str | None = None
    performed_by: str | None = None
    performed_at: datetime | None = None

class AnalysisUpdate(BaseModel):
    parameters: dict[str, Any] | None = None
    notes: str | None = None
    performed_by: str | None = None
    performed_at: datetime | None = None

class AnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sample_id: int
    analysis_type: AnalysisTypeOut
    parameters: dict[str, Any] | None
    notes: str | None
    performed_by: str | None
    performed_at: datetime | None
    created_at: datetime
    attachments: list[AttachmentOut] = []


# ── Samples ────────────────────────────────────────────────────────────────────

class SampleCreate(BaseModel):
    name: str
    substrate_material: str | None = None
    substrate_dimensions: str | None = None
    film_material: str | None = None
    description: str | None = None
    created_by: str | None = None

class SampleUpdate(BaseModel):
    name: str | None = None
    substrate_material: str | None = None
    substrate_dimensions: str | None = None
    film_material: str | None = None
    description: str | None = None

class SampleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    substrate_material: str | None
    substrate_dimensions: str | None
    film_material: str | None
    description: str | None
    created_by: str | None
    created_at: datetime
    process_steps: list[ProcessStepOut] = []
    analyses: list[AnalysisOut] = []

class SampleListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    substrate_material: str | None
    film_material: str | None
    created_by: str | None
    created_at: datetime
