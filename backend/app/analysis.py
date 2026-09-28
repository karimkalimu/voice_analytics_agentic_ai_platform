import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.database import cached_analysis, get_file, save_analysis, update_analysis_status
from app.layer2 import run_layer2
from app.llm import ProviderRefusal, complete, structured_content, tier_config
from app.prompts import load_prompt


TaxonomyLabel = Annotated[str, Field(min_length=1, max_length=80)]


class Taxonomy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    professional_topics: list[TaxonomyLabel]
    personal_topics: list[TaxonomyLabel]
    upcoming_events: list[TaxonomyLabel]

    @field_validator("professional_topics", "personal_topics", "upcoming_events", mode="before")
    @classmethod
    def normalize_labels(cls, labels):
        if not isinstance(labels, list):
            return labels
        normalized = []
        seen = set()
        for label in labels:
            if not isinstance(label, str):
                normalized.append(label)
                continue
            canonical = " ".join(label.split())
            key = canonical.casefold()
            if key not in seen:
                normalized.append(canonical)
                seen.add(key)
        return normalized

    @field_validator("professional_topics", "personal_topics", "upcoming_events")
    @classmethod
    def validate_labels(cls, labels):
        seen = set()
        for label in labels:
            canonical = " ".join(label.split())
            if (not canonical or canonical != label or len(label) > 80
                    or canonical.casefold() in ("none", "n/a", "not applicable")
                    or canonical.casefold() in seen):
                raise ValueError("Invalid taxonomy label")
            seen.add(canonical.casefold())
        return labels

    @model_validator(mode="after")
    def validate_distinct_categories(self):
        labels = self.professional_topics + self.personal_topics + self.upcoming_events
        if (len({label.casefold() for label in labels}) != len(labels)
                or len({frozenset(label.casefold().split()) for label in labels}) != len(labels)):
            raise ValueError("Duplicate taxonomy label")
        return self


class LayerOne(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    summary: str = Field(min_length=1, max_length=1200)
    taxonomy: Taxonomy

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, summary):
        if summary != summary.strip():
            raise ValueError("Invalid summary")
        return summary


def current_analysis_version():
    model, base_url, _ = tier_config("quality")
    config = json.dumps([load_prompt("layer1"), model, base_url, LayerOne.model_json_schema()], sort_keys=True)
    digest = hashlib.sha256(config.encode()).hexdigest()[:16]
    return f"{os.getenv('LAYER1_VERSION') or '1'}:{digest}"


def analyze_file(file_id: int, transcript_path: Path):
    update_analysis_status(file_id, "analyzing")
    version = None
    try:
        version = current_analysis_version()
        row = get_file(file_id)
        cached = None
        if row and row["audio_sha256"]:
            cached = cached_analysis(row["user_id"], row["audio_sha256"],
                                     row["transcription_version"], version, file_id)
        if cached:
            save_analysis(file_id, cached[0], cached[1], version)
        else:
            response = complete(
                "quality",
                [
                    {"role": "system", "content": load_prompt("layer1")},
                    {"role": "user", "content": json.dumps({"transcript": transcript_path.read_text(encoding="utf-8")})},
                ],
                {"type": "json_schema", "json_schema": {"name": "layer_one", "strict": True,
                                                         "schema": LayerOne.model_json_schema()}},
            )
            result = LayerOne.model_validate_json(structured_content(response), strict=True)
            if not result.summary.strip():
                raise ValueError("Empty summary")
            save_analysis(file_id, result.summary, result.taxonomy.model_dump_json(), version)
    except ProviderRefusal:
        logging.exception("Layer 1 provider refused file %s", file_id)
        update_analysis_status(file_id, "analysis_failed", "The analysis provider refused this request.", version)
    except ValueError:
        logging.exception("Invalid Layer 1 output for file %s", file_id)
        update_analysis_status(file_id, "analysis_failed", "Analysis output could not be validated.", version)
    except Exception:
        logging.exception("Layer 1 failed for file %s", file_id)
        update_analysis_status(file_id, "analysis_failed", "Analysis could not be completed.", version)
    else:
        run_layer2(file_id, transcript_path)
