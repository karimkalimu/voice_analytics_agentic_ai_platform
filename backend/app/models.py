from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.upload_options import validate_layer2_config, validate_layer2_options


class TusUpload(BaseModel):
    ID: str | None = None
    Size: int | None = None
    Offset: int | None = None
    SizeIsDeferred: bool = False
    MetaData: dict[str, str] = Field(default_factory=dict)
    Storage: dict[str, str] | None = None
    IsPartial: bool = False


class TusHttpRequest(BaseModel):
    Header: dict[str, list[str]] = Field(default_factory=dict)


class TusEvent(BaseModel):
    Upload: TusUpload
    HTTPRequest: TusHttpRequest = Field(default_factory=TusHttpRequest)


class TusHook(BaseModel):
    Type: str
    Event: TusEvent


class Layer2Request(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    options: list[str]
    config: dict = Field(default_factory=dict)

    @field_validator("options")
    @classmethod
    def validate_options(cls, options):
        return validate_layer2_options(options)

    @model_validator(mode="after")
    def validate_config(self):
        self.config = validate_layer2_config(self.config, self.options)
        return self


class AggregateJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str | None = Field(default=None, min_length=1)
    created_from: AwareDatetime | None = None
    created_to: AwareDatetime | None = None
    taxonomy_label: str | None = Field(default=None, min_length=1, max_length=80)
    group_by: Literal["all", "user", "taxonomy", "sentiment"] = "user"

    @field_validator("user_id", "taxonomy_label", mode="before")
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_dates(self):
        if self.created_from is not None and self.created_to is not None and self.created_from > self.created_to:
            raise ValueError("created_from must not exceed created_to")
        if self.group_by == "all" and self.user_id is None:
            raise ValueError("group_by all requires user_id")
        return self


class AggregateGroupResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=80)
    file_count: int = Field(ge=1)
    total_duration_sec: float = Field(gt=0)
    summary: str = Field(min_length=1, max_length=2000)


class AggregateUserGroupResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1)
    file_count: int = Field(ge=1)
    total_duration_sec: float = Field(gt=0)
    summary: str = Field(min_length=1, max_length=2000)
    professional_topics: list[str]
    personal_topics: list[str]
    upcoming_events: list[str]


class AggregateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_count: int = Field(ge=0)
    total_duration_sec: float = Field(ge=0)
    overall_summary: str = Field(min_length=1, max_length=2000)
    professional_topics: list[str]
    personal_topics: list[str]
    upcoming_events: list[str]
    group_by: Literal["all", "taxonomy", "sentiment"]
    groups: list[AggregateGroupResult]


class AggregateUserResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_count: int = Field(ge=0)
    total_duration_sec: float = Field(ge=0)
    overall_summary: str = Field(min_length=1, max_length=2000)
    group_by: Literal["user"]
    groups: list[AggregateUserGroupResult]
