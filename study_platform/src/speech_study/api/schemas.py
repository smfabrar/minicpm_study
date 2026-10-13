from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from ..domain.models import Condition
from speech_contracts import RunSettings


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StudyCreate(InputModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = ""
    settings: RunSettings = Field(default_factory=RunSettings)


class StudyUpdate(InputModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    settings: dict[str, str | int | float | bool] | None = None


class CaseInput(InputModel):
    question: str = Field(min_length=1, max_length=4000)
    category: Literal["room", "document", "calculator", "none", "custom"] = "none"
    expected_answer: str = ""
    oracle_result: str = ""
    expected_tool: str = ""
    expected_arguments: dict[str, object] = Field(default_factory=dict)
    split: Literal["development", "evaluation"] = "development"
    notes: str = ""


class ToolInput(InputModel):
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
    description: str = Field(min_length=1, max_length=1000)
    parameter: str = Field(default="query", pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
    kind: Literal["room", "document", "calculator", "fixture", "python"]
    records: dict[str, str] = Field(default_factory=dict)
    aliases: dict[str, str] = Field(default_factory=dict)
    delay_ms: int = Field(default=0, ge=0, le=60000)
    failure: Literal["none", "error", "empty"] = "none"
    parameters: dict | None = None
    python_code: str = Field(default="", max_length=65536)
    timeout_seconds: float = Field(default=10, gt=0, le=120)
    ground_arguments: bool = True


class RunCreate(InputModel):
    case_id: str
    conditions: list[Condition] = Field(min_length=1, max_length=3)


class ReviewInput(InputModel):
    verdict: Literal["correct", "incorrect", "partial", "silent", "unreviewed"]
    heard_transcript: str = ""
    notes: str = ""
    relevant_fact_ms: float | None = Field(default=None, ge=0)


class RuntimeInput(InputModel):
    url: str


class LibraryAttach(InputModel):
    library_id: str
