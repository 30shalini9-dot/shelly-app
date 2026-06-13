from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EvaluationStatus(str, Enum):
    not_started = "Not Started"
    in_progress = "In Progress"
    completed = "Completed"


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class StepCreate(BaseModel):
    step_no: int = Field(ge=1)
    title: str = Field(min_length=1)
    description: str = ""
    max_marks: float = Field(gt=0)


class QuestionCreate(BaseModel):
    question_no: str = Field(min_length=1)
    question_text: str = Field(min_length=1)
    max_marks: float = Field(gt=0)
    question_type: str = "General"
    display_order: int = Field(ge=1)
    reference_solution: str = ""
    steps: list[StepCreate] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_step_total(self) -> "QuestionCreate":
        step_total = sum(step.max_marks for step in self.steps)
        if abs(step_total - self.max_marks) > 0.0001:
            raise ValueError(
                f"Step maximum marks ({step_total:g}) must equal question maximum marks "
                f"({self.max_marks:g})"
            )
        return self


class QuestionPaperCreate(BaseModel):
    paper_code: str = Field(min_length=1)
    subject_code: str = Field(min_length=1)
    subject_name: str = Field(min_length=1)
    class_code: str = Field(min_length=1)
    version: int = Field(default=1, ge=1)
    status: str = "active"
    questions: list[QuestionCreate] = Field(min_length=1)


class MarkRequest(BaseModel):
    awarded_marks: float = Field(ge=0)


class ChangeQuestionMappingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_question_id: str
    page_id: str | None = None
    bbox: dict[str, float] | None = None


class BoundingBox(BaseModel):
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    w: float = Field(gt=0)
    h: float = Field(gt=0)


class AnnotationCreate(BaseModel):
    question_id: str
    step_id: str | None = None
    page_id: str
    text: str = Field(min_length=1, max_length=100)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(default=0.12, gt=0, le=1)
    height: float = Field(default=0.06, gt=0, le=1)


class AnnotationUpdate(BaseModel):
    x: float | None = Field(default=None, ge=0, le=1)
    y: float | None = Field(default=None, ge=0, le=1)
    width: float | None = Field(default=None, gt=0, le=1)
    height: float | None = Field(default=None, gt=0, le=1)


class AiVisionNoteCreate(BaseModel):
    question_id: str
    page_id: str
    analysis: str = Field(min_length=1)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)


class SubmissionMetadata(BaseModel):
    student_id: str = Field(min_length=1)
    student_name: str | None = None
    paper_code: str = Field(min_length=1)
    assigned_evaluator_id: str = "eval_001"
    evaluation_batch: str = "Default"
    mappings: list[dict[str, Any]] = Field(default_factory=list)
