"""Pydantic contracts shared by HTTP handlers and the analysis layer."""
from datetime import date
from typing import Any, Literal
from pydantic import BaseModel, Field, ConfigDict

Role = Literal["Admin", "Editor/Reviewer", "Viewer"]


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=256)
    role: Role


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class AnalysisEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    analysis: dict[str, Any]


class TopicEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topics: list[dict[str, Any]]


class MeetingMetadata(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    meeting_date: date
    notes: str = Field(default="", max_length=2000)


class TopicSplit(BaseModel):
    at_line: int = Field(ge=1)


class TopicMerge(BaseModel):
    target_topic_id: str


class TranscriptPreview(BaseModel):
    transcript: str = ""
    filename: str | None = None
