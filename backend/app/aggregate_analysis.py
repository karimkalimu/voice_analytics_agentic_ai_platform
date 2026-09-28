import json
import logging
import math
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app import storage
from app.analysis import Taxonomy
from app.database import (create_aggregate_job, get_aggregate_job, list_files,
                          update_aggregate_job)
from app.llm import ProviderRefusal, complete, structured_content
from app.models import (AggregateGroupResult, AggregateJobRequest, AggregateResult,
                        AggregateUserGroupResult, AggregateUserResult)
from app.prompts import load_prompt


INPUT_CHAR_LIMIT = 24000
MAX_LABELS_PER_CATEGORY = 25
NO_MATCH_SUMMARY = "No eligible files matched this aggregate request."


class AggregateSynthesis(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    overall_summary: str = Field(min_length=1, max_length=2000)
    taxonomy: Taxonomy

    @field_validator("overall_summary")
    @classmethod
    def validate_summary(cls, value):
        if value != value.strip():
            raise ValueError("Invalid aggregate summary")
        return value

    @model_validator(mode="after")
    def limit_taxonomy(self):
        if any(len(labels) > MAX_LABELS_PER_CATEGORY for labels in (
            self.taxonomy.professional_topics,
            self.taxonomy.personal_topics,
            self.taxonomy.upcoming_events,
        )):
            raise ValueError("Too many aggregate taxonomy labels")
        return self


class AggregateGroupSynthesis(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    summary: str = Field(min_length=1, max_length=2000)

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value):
        if value != value.strip():
            raise ValueError("Invalid group summary")
        return value


class AggregateUserSynthesis(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    summary: str = Field(min_length=1, max_length=2000)
    taxonomy: Taxonomy

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value):
        if value != value.strip():
            raise ValueError("Invalid user summary")
        return value

    @model_validator(mode="after")
    def limit_taxonomy(self):
        if any(len(labels) > MAX_LABELS_PER_CATEGORY for labels in (
            self.taxonomy.professional_topics,
            self.taxonomy.personal_topics,
            self.taxonomy.upcoming_events,
        )):
            raise ValueError("Too many user taxonomy labels")
        return self


def eligible_records(request: AggregateJobRequest):
    records = []
    for row in list_files(request.user_id):
        if row["status"] != "completed" or not isinstance(row["summary"], str) or not row["summary"].strip():
            continue
        if not isinstance(row["duration_sec"], (int, float)) or isinstance(row["duration_sec"], bool):
            continue
        if not math.isfinite(row["duration_sec"]) or row["duration_sec"] <= 0:
            continue
        try:
            transcript_path = storage.stored_transcript_path(row)
            transcript_path.read_text(encoding="utf-8")
            taxonomy = Taxonomy.model_validate_json(row["taxonomy"], strict=True)
            created_at = datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            layer2_results = json.loads(row["layer2_results"])
            if not isinstance(layer2_results, dict):
                continue
        except (OSError, UnicodeError, ValueError, TypeError):
            continue
        if request.created_from is not None and created_at < request.created_from:
            continue
        if request.created_to is not None and created_at > request.created_to:
            continue
        labels = (taxonomy.professional_topics + taxonomy.personal_topics + taxonomy.upcoming_events)
        if request.taxonomy_label is not None and request.taxonomy_label.casefold() not in {
            label.casefold() for label in labels
        }:
            continue
        records.append({"row": row, "taxonomy": taxonomy, "layer2_results": layer2_results})
    return records


def compact_record(record: dict):
    taxonomy = record["taxonomy"]
    return {
        "summary": record["row"]["summary"],
        "professional_topics": taxonomy.professional_topics[:MAX_LABELS_PER_CATEGORY],
        "personal_topics": taxonomy.personal_topics[:MAX_LABELS_PER_CATEGORY],
        "upcoming_events": taxonomy.upcoming_events[:MAX_LABELS_PER_CATEGORY],
    }


def payload_size(records: list[dict]):
    return len(json.dumps({"records": records}, ensure_ascii=False, separators=(",", ":")))


def bounded_batches(records: list[dict]):
    batches = []
    current = []
    for record in records:
        candidate = [*current, record]
        if current and payload_size(candidate) > INPUT_CHAR_LIMIT:
            batches.append(current)
            current = [record]
        else:
            current = candidate
        if payload_size(current) > INPUT_CHAR_LIMIT:
            current[0]["summary"] = current[0]["summary"][:500]
            for key in ("professional_topics", "personal_topics", "upcoming_events"):
                current[0][key] = current[0][key][:10]
        if payload_size(current) > INPUT_CHAR_LIMIT:
            raise ValueError("Aggregate input record is too large")
    if current:
        batches.append(current)
    return batches


def synthesize_batch(records: list[dict]):
    response = complete(
        "quality",
        [{"role": "system", "content": load_prompt("aggregate_analysis")},
         {"role": "user", "content": json.dumps({"records": records}, ensure_ascii=False)}],
        {"type": "json_schema", "json_schema": {"name": "aggregate_analysis", "strict": True,
                                                 "schema": AggregateSynthesis.model_json_schema()}},
    )
    return AggregateSynthesis.model_validate_json(structured_content(response), strict=True)


def synthesize_records(records: list[dict]):
    current = records
    while True:
        results = [synthesize_batch(batch) for batch in bounded_batches(current)]
        if len(results) == 1:
            return results[0]
        current = [{"summary": result.overall_summary,
                    "professional_topics": result.taxonomy.professional_topics,
                    "personal_topics": result.taxonomy.personal_topics,
                    "upcoming_events": result.taxonomy.upcoming_events}
                   for result in results]


def synthesize_group_batch(records: list[dict]):
    response = complete(
        "quality",
        [{"role": "system", "content": load_prompt("aggregate_group_summary")},
         {"role": "user", "content": json.dumps({"records": records}, ensure_ascii=False)}],
        {"type": "json_schema", "json_schema": {"name": "aggregate_group_summary", "strict": True,
                                                 "schema": AggregateGroupSynthesis.model_json_schema()}},
    )
    return AggregateGroupSynthesis.model_validate_json(structured_content(response), strict=True)


def synthesize_group_records(records: list[dict]):
    current = records
    while True:
        results = [synthesize_group_batch(batch) for batch in bounded_batches(current)]
        if len(results) == 1:
            return results[0].summary
        current = [{"summary": result.summary, "professional_topics": [],
                    "personal_topics": [], "upcoming_events": []} for result in results]


def synthesize_user_batch(records: list[dict]):
    response = complete(
        "quality",
        [{"role": "system", "content": load_prompt("aggregate_user_summary")},
         {"role": "user", "content": json.dumps({"records": records}, ensure_ascii=False)}],
        {"type": "json_schema", "json_schema": {"name": "aggregate_user_summary", "strict": True,
                                                 "schema": AggregateUserSynthesis.model_json_schema()}},
    )
    return AggregateUserSynthesis.model_validate_json(structured_content(response), strict=True)


def synthesize_user_records(records: list[dict]):
    current = records
    while True:
        results = [synthesize_user_batch(batch) for batch in bounded_batches(current)]
        if len(results) == 1:
            return results[0]
        current = [{"summary": result.summary,
                    "professional_topics": result.taxonomy.professional_topics,
                    "personal_topics": result.taxonomy.personal_topics,
                    "upcoming_events": result.taxonomy.upcoming_events}
                   for result in results]


def grouped_records(records: list[dict], group_by: str):
    grouped = {}
    for record in records:
        if group_by == "all":
            keys = ["all"]
        elif group_by == "user":
            keys = [record["row"]["user_id"]]
        elif group_by == "taxonomy":
            taxonomy = record["taxonomy"]
            keys = list(dict.fromkeys(taxonomy.professional_topics + taxonomy.personal_topics
                                      + taxonomy.upcoming_events)) or ["unclassified"]
        else:
            label = record["layer2_results"].get("sentiment", {}).get("label")
            keys = [label if label in ("positive", "neutral", "negative") else "unclassified"]
        for key in keys:
            grouped.setdefault(key, []).append(record)
    return sorted(grouped.items(), key=lambda item: item[0].casefold())


def group_results(records: list[dict], group_by: str, overall_summary: str):
    groups = []
    for key, members in grouped_records(records, group_by):
        if group_by == "user":
            synthesis = synthesize_user_records([compact_record(record) for record in members])
            groups.append(AggregateUserGroupResult(
                user_id=key,
                file_count=len(members),
                total_duration_sec=round(sum(record["row"]["duration_sec"] for record in members), 6),
                summary=synthesis.summary,
                professional_topics=synthesis.taxonomy.professional_topics,
                personal_topics=synthesis.taxonomy.personal_topics,
                upcoming_events=synthesis.taxonomy.upcoming_events,
            ))
            continue
        summary = overall_summary if group_by == "all" else synthesize_group_records(
            [compact_record(record) for record in members]
        )
        values = {
            "file_count": len(members),
            "total_duration_sec": round(sum(record["row"]["duration_sec"] for record in members), 6),
            "summary": summary,
        }
        groups.append(AggregateGroupResult(key=key, **values))
    return groups


def aggregate_result(records: list[dict], group_by: str):
    total_duration = round(sum(record["row"]["duration_sec"] for record in records), 6)
    if not records:
        if group_by == "user":
            return AggregateUserResult(
                file_count=0,
                total_duration_sec=0.0,
                overall_summary=NO_MATCH_SUMMARY,
                group_by="user",
                groups=[],
            ).model_dump()
        return AggregateResult(
            file_count=0,
            total_duration_sec=0.0,
            overall_summary=NO_MATCH_SUMMARY,
            professional_topics=[],
            personal_topics=[],
            upcoming_events=[],
            group_by=group_by,
            groups=[],
        ).model_dump()
    if group_by == "user":
        groups = group_results(records, group_by, "")
        overall_summary = (groups[0].summary if len(groups) == 1
                           else f"Aggregate includes {len(records)} eligible files across {len(groups)} users. "
                                "Per-user summaries are provided in groups.")
        return AggregateUserResult(
            file_count=len(records),
            total_duration_sec=total_duration,
            overall_summary=overall_summary,
            group_by="user",
            groups=groups,
        ).model_dump()
    synthesis = synthesize_records([compact_record(record) for record in records])
    return AggregateResult(
        file_count=len(records),
        total_duration_sec=total_duration,
        overall_summary=synthesis.overall_summary,
        professional_topics=synthesis.taxonomy.professional_topics,
        personal_topics=synthesis.taxonomy.personal_topics,
        upcoming_events=synthesis.taxonomy.upcoming_events,
        group_by=group_by,
        groups=group_results(records, group_by, synthesis.overall_summary),
    ).model_dump()


def queue_aggregate_job(request: AggregateJobRequest):
    return create_aggregate_job(request.user_id, request.model_dump(mode="json"))


def run_aggregate_job(job_id: int):
    job = get_aggregate_job(job_id)
    if job is None or job["status"] not in ("queued", "running"):
        return
    update_aggregate_job(job_id, "running")
    try:
        stored_request = json.loads(job["request_json"])
        if "user_id" not in stored_request:
            stored_request["user_id"] = job["user_id"]
        request = AggregateJobRequest.model_validate(stored_request)
        records = eligible_records(request)
        result = aggregate_result(records, request.group_by)
    except ProviderRefusal:
        logging.exception("Aggregate provider refused job %s", job_id)
        update_aggregate_job(job_id, "failed", error="The analysis provider refused this aggregate request.")
    except ValueError:
        logging.exception("Invalid aggregate output for job %s", job_id)
        update_aggregate_job(job_id, "failed", error="Aggregate analysis output could not be validated.")
    except Exception:
        logging.exception("Aggregate analysis failed for job %s", job_id)
        update_aggregate_job(job_id, "failed", error="Aggregate analysis could not be completed.")
    else:
        update_aggregate_job(job_id, "completed", result=result)


def resume_aggregate_jobs(job_ids: list[int]):
    for job_id in job_ids:
        run_aggregate_job(job_id)
