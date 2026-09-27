import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.audio import rms_normalized
from app.database import cached_layer2_result, claim_layer2, get_file, save_layer2_result, update_layer2_status
from app.llm import ProviderRefusal, complete, structured_content, tier_config
from app.prompts import load_prompt
from app import storage
from app.upload_options import validate_layer2_config, validate_layer2_options


class CountResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    count: int = Field(ge=0)


class SentimentResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    label: Literal["positive", "neutral", "negative"]


SCHEMAS = {"count_nouns": CountResult, "count_adjectives": CountResult,
           "sentiment": SentimentResult, "topic_mentions": CountResult}


def current_layer2_version(option: str, transcript_digest: str | None = None, config: dict | None = None):
    if option == "rms":
        identity = ["rms", "pcm16", "mono", 16000]
    else:
        model, base_url, _ = tier_config("weak")
        option_config = (config or {}).get(option, {"unique_only": False} if option == "count_nouns" else {})
        identity = [transcript_digest, load_prompt(f"layer2_{option}"), model, base_url,
                    SCHEMAS[option].model_json_schema(), option_config]
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
    return f"{os.getenv('LAYER2_VERSION') or '1'}:{digest}"


def run_option(option: str, audio_path: Path, transcript_path: Path, config: dict):
    if option == "rms":
        return {"rms_normalized": rms_normalized(audio_path)}
    schema = SCHEMAS[option]
    content = {"transcript": transcript_path.read_text(encoding="utf-8")}
    if option in ("count_nouns", "topic_mentions"):
        content["configuration"] = config[option]
    response = complete(
        "weak",
        [{"role": "system", "content": load_prompt(f"layer2_{option}")},
         {"role": "user", "content": json.dumps(content)}],
        {"type": "json_schema", "json_schema": {"name": f"layer2_{option}", "strict": True,
                                                 "schema": schema.model_json_schema()}},
    )
    return schema.model_validate_json(structured_content(response), strict=True).model_dump()


def prepare_layer2(file_id: int, user_id: str, options: list[str], config: dict):
    row = get_file(file_id, user_id)
    if row is None:
        return "not_found", None
    if row["status"] not in ("completed", "layer2_failed"):
        return "conflict", None
    if not row["transcript_path"] or row["summary"] is None or row["taxonomy"] is None:
        return "unavailable", None
    try:
        transcript_path = storage.stored_transcript_path(row)
        transcript_bytes = transcript_path.read_bytes()
        transcript_bytes.decode("utf-8")
    except (OSError, UnicodeError, ValueError):
        return "unavailable", None
    digest = hashlib.sha256(transcript_bytes).hexdigest()
    versions = {}
    for option in options:
        try:
            versions[option] = current_layer2_version(option, digest, config)
        except Exception:
            versions[option] = None
    return claim_layer2(file_id, user_id, options, config, versions, row["transcript_path"]), transcript_path


def run_layer2(file_id: int, transcript_path: Path):
    row = get_file(file_id)
    options = json.loads(row["layer2_pending_options"])
    if not options:
        update_layer2_status(file_id, "completed")
        return
    update_layer2_status(file_id, "analyzing_layer2")
    try:
        validate_layer2_options(options)
        config = validate_layer2_config(json.loads(row["layer2_config"]), json.loads(row["layer2_options"]))
    except (ValueError, TypeError):
        logging.exception("Invalid Layer 2 configuration for file %s", file_id)
        update_layer2_status(file_id, "layer2_failed", "Layer 2 configuration is invalid.")
        return
    results = json.loads(row["layer2_results"])
    versions = json.loads(row["layer2_version"])
    try:
        transcript_digest = (hashlib.sha256(transcript_path.read_bytes()).hexdigest()
                             if any(option != "rms" for option in options) else None)
    except Exception:
        logging.exception("Could not read transcript for file %s", file_id)
        update_layer2_status(file_id, "layer2_failed", "Transcript file is unavailable.")
        return
    for option in options:
        try:
            version = current_layer2_version(option, transcript_digest, config)
            if versions.get(option) == version and option in results:
                continue
            result = cached_layer2_result(row, option, version) if row["audio_sha256"] else None
            if result is None:
                audio_path = storage.stored_audio_path(row)
                result = run_option(option, audio_path, transcript_path, config)
            save_layer2_result(file_id, option, result, version)
        except ProviderRefusal:
            logging.exception("Layer 2 provider refused option %s for file %s", option, file_id)
            update_layer2_status(file_id, "layer2_failed", "The analysis provider refused this request.")
            return
        except ValueError:
            logging.exception("Invalid Layer 2 output for file %s", file_id)
            update_layer2_status(file_id, "layer2_failed", "Layer 2 output could not be validated.")
            return
        except Exception:
            logging.exception("Layer 2 option %s failed for file %s", option, file_id)
            update_layer2_status(file_id, "layer2_failed", "Layer 2 analysis could not be completed.")
            return
    update_layer2_status(file_id, "completed")
