import json
from datetime import datetime, timezone
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class FileFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_from: AwareDatetime | None = None
    created_to: AwareDatetime | None = None
    duration_min: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    duration_max: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    taxonomy_label: str | None = Field(default=None, min_length=1, max_length=80)
    sentiment: Literal["positive", "neutral", "negative"] | None = None
    rms_min: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    rms_max: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    noun_count_min: int | None = Field(default=None, ge=0)
    noun_count_max: int | None = Field(default=None, ge=0)
    adjective_count_min: int | None = Field(default=None, ge=0)
    adjective_count_max: int | None = Field(default=None, ge=0)

    @field_validator("created_from", "created_to", mode="before")
    @classmethod
    def iso_datetime(cls, value):
        if not isinstance(value, str) or "T" not in value:
            raise ValueError("Use an ISO 8601 date-time with a timezone")
        return value

    @field_validator("taxonomy_label", mode="before")
    @classmethod
    def strip_label(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_ranges(self):
        for lower, upper in (("created_from", "created_to"), ("duration_min", "duration_max"),
                             ("rms_min", "rms_max"), ("noun_count_min", "noun_count_max"),
                             ("adjective_count_min", "adjective_count_max")):
            start, end = getattr(self, lower), getattr(self, upper)
            if start is not None and end is not None and start > end:
                raise ValueError(f"{lower} must not exceed {upper}")
        return self


def parse_file_filters(request: Request):
    if any(len(request.query_params.getlist(key)) != 1 for key in request.query_params):
        raise HTTPException(status_code=422, detail="Duplicate filter parameter")
    try:
        return FileFilters.model_validate(dict(request.query_params))
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_input=False, include_context=False)) from None


def matches_range(value, minimum, maximum):
    return ((minimum is None or value is not None and value >= minimum)
            and (maximum is None or value is not None and value <= maximum))


def matches_file(row: dict, filters: FileFilters):
    if filters.created_from is not None or filters.created_to is not None:
        created = datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        if not matches_range(created, filters.created_from, filters.created_to):
            return False
    if not matches_range(row["duration_sec"], filters.duration_min, filters.duration_max):
        return False
    if filters.taxonomy_label is not None:
        taxonomy = json.loads(row["taxonomy"]) if row["taxonomy"] else {}
        labels = (taxonomy.get("professional_topics", []) + taxonomy.get("personal_topics", [])
                  + taxonomy.get("upcoming_events", []))
        if filters.taxonomy_label.casefold() not in {label.casefold() for label in labels}:
            return False
    results = json.loads(row["layer2_results"])
    if filters.sentiment is not None and results.get("sentiment", {}).get("label") != filters.sentiment:
        return False
    for option, field, minimum, maximum in (
        ("rms", "rms_normalized", filters.rms_min, filters.rms_max),
        ("count_nouns", "count", filters.noun_count_min, filters.noun_count_max),
        ("count_adjectives", "count", filters.adjective_count_min, filters.adjective_count_max),
    ):
        if minimum is not None or maximum is not None:
            value = results.get(option, {}).get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not matches_range(value, minimum, maximum):
                return False
    return True


def filter_files(rows: list[dict], filters: FileFilters):
    return [row for row in rows if matches_file(row, filters)]
