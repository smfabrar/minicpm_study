from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from speech_contracts import RunSettings


def new_id() -> str:
    return uuid4().hex


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Condition(StrEnum):
    NATIVE = "B0"
    PROPOSED = "B1"
    REFERENCE = "B2"


class StudyStatus(StrEnum):
    DRAFT = "draft"
    FROZEN = "frozen"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    SILENT = "silent"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


@dataclass(slots=True)
class Case:
    id: str
    study_id: str
    question: str
    category: str = "none"
    expected_answer: str = ""
    oracle_result: str = ""
    expected_tool: str = ""
    expected_arguments: dict[str, Any] = field(default_factory=dict)
    split: str = "development"
    audio_path: str | None = None
    audio_sha256: str | None = None
    audio_origin: str | None = None
    audio_provenance: dict[str, Any] = field(default_factory=dict)
    preparation_trace: str | None = None
    notes: str = ""


@dataclass(slots=True)
class ToolDefinition:
    id: str
    study_id: str
    name: str
    description: str
    parameter: str
    kind: str
    records: dict[str, str] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)
    delay_ms: int = 0
    failure: str = "none"
    parameters: dict[str, Any] | None = None
    python_code: str = ""
    timeout_seconds: float = 10
    ground_arguments: bool = True
    library_id: str | None = None


@dataclass(slots=True)
class Study:
    id: str
    name: str
    description: str = ""
    status: StudyStatus = StudyStatus.DRAFT
    settings: RunSettings = field(default_factory=RunSettings)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    snapshot: dict[str, Any] | None = None
    deleted_at: str | None = None


@dataclass(slots=True)
class Review:
    verdict: str = "unreviewed"
    heard_transcript: str = ""
    notes: str = ""
    relevant_fact_ms: float | None = None
    updated_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class Run:
    id: str
    study_id: str
    case_id: str
    condition: Condition
    request: dict[str, Any]
    snapshot: dict[str, Any]
    study_status: StudyStatus
    status: RunStatus = RunStatus.QUEUED
    created_at: str = field(default_factory=utc_now)
    runtime_job_id: str | None = None
    runtime_url: str = ""
    result: dict[str, Any] | None = None
    error: str | None = None
    review: Review | None = None
    output_transcript: str = ""
    output_segments: list[dict[str, Any]] = field(default_factory=list)
    analysis_trace: str | None = None
    artifact_directory: str | None = None


@dataclass(slots=True)
class StudyDetails:
    study: Study
    cases: list[Case]
    tools: list[ToolDefinition]
    runs: list[Run]


@dataclass(slots=True)
class LibraryTool:
    id: str
    definition: dict[str, Any]
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
