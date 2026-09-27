import hashlib
import json
import logging
import os
import time
from http.client import HTTPSConnection
from pathlib import Path
from urllib.parse import quote

from app import storage
from app.analysis import analyze_file, current_analysis_version
from app.database import (get_file, mark_transcript_validated, reject_file, reuse_transcription,
                          set_audio_hash, set_file_status_error, update_audio_validation,
                          update_storage_path, update_transcription)
from app.guardrails import (current_guardrail_version, guardrail_settings, validate_audio_input,
                            validate_transcript_output)
from app.layer2 import run_layer2


NO_SPEECH_ERROR = "No spoken audio was detected. Please upload a recording with clear English speech."
GENERIC_TRANSCRIPTION_ERROR = ("The transcription service could not process this audio. "
                               "Please try again or upload a different recording.")


def assemblyai_request(method: str, path: str, api_key: str, body=None, headers=None):
    connection = HTTPSConnection("api.assemblyai.com", timeout=120)
    try:
        connection.request(method, path, body=body, headers={"Authorization": api_key, **(headers or {})})
        response = connection.getresponse()
        result = json.load(response)
        if response.status >= 400:
            raise RuntimeError(result.get("error") or result.get("message") or f"AssemblyAI HTTP {response.status}")
        return result
    finally:
        connection.close()


def hash_audio(audio_path: Path):
    digest = hashlib.sha256()
    with audio_path.open("rb") as audio:
        for chunk in iter(lambda: audio.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reject_no_speech(file_id: int, language: str | None, duration_sec: float,
                     version: str, guardrail_version: str):
    update_transcription(file_id, "validating_transcript", language=language,
                         duration_sec=duration_sec, version=version)
    reject_file(file_id, "insufficient_speech", NO_SPEECH_ERROR, guardrail_version)


def validate_transcript_file(file_id: int, transcript_path: Path | None, language: str | None,
                             duration_sec: float | None, words: list | None,
                             settings, guardrail_version: str):
    try:
        if not isinstance(language, str) or not isinstance(duration_sec, (int, float)):
            raise ValueError("Missing transcription metadata")
        transcript = transcript_path.read_text(encoding="utf-8") if transcript_path else ""
        decision = validate_transcript_output(transcript, language, duration_sec, words, settings)
    except Exception:
        logging.exception("Post-transcription validation failed for file %s", file_id)
        set_file_status_error(file_id, "transcription_failed",
                              "The transcription result was incomplete and could not be validated.")
        return
    if decision.rejection_code:
        reject_file(file_id, decision.rejection_code, decision.error, guardrail_version)
        return
    mark_transcript_validated(file_id, guardrail_version)
    analyze_file(file_id, transcript_path)


def transcribe_file(file_id: int, audio_path: Path, settings, guardrail_version: str):
    language = None
    version = os.getenv("TRANSCRIPTION_VERSION") or "1"
    try:
        digest = hash_audio(audio_path)
        set_audio_hash(file_id, digest)
        row = get_file(file_id)
        cached = reuse_transcription(file_id, row["user_id"], digest, version)
        if cached:
            transcript_path = storage.stored_transcript_path(cached) if cached["transcript_path"] else None
            current = get_file(file_id)
            validate_transcript_file(file_id, transcript_path, cached["language"], current["duration_sec"],
                                     None, settings, guardrail_version)
            return

        duration = row["duration_sec"]
        update_transcription(file_id, "transcribing", language=language,
                             duration_sec=duration, version=version)
        api_key = os.environ.get("ASSEMBLYAI_API_KEY")
        if not api_key:
            raise RuntimeError("AssemblyAI API key is not configured.")

        with audio_path.open("rb") as audio:
            upload = assemblyai_request(
                "POST", "/v2/upload", api_key, audio,
                {"Content-Type": "application/octet-stream", "Content-Length": str(audio_path.stat().st_size)},
            )
        submitted = assemblyai_request(
            "POST", "/v2/transcript", api_key,
            json.dumps({"audio_url": upload["upload_url"], "language_detection": True}).encode(),
            {"Content-Type": "application/json"},
        )

        deadline = time.monotonic() + 1800
        while time.monotonic() < deadline:
            result = assemblyai_request("GET", f"/v2/transcript/{quote(submitted['id'], safe='')}", api_key)
            if result.get("status") == "completed":
                break
            if result.get("status") == "error":
                provider_error = result.get("error")
                if isinstance(provider_error, str) and "no spoken audio" in provider_error.casefold():
                    reject_no_speech(file_id, language, duration, version, guardrail_version)
                    return
                raise RuntimeError(provider_error or "AssemblyAI transcription failed.")
            if result.get("status") not in ("queued", "processing"):
                raise RuntimeError("Unexpected AssemblyAI transcript status.")
            time.sleep(3)
        else:
            raise TimeoutError("AssemblyAI transcription timed out.")

        transcript = result.get("text") if isinstance(result.get("text"), str) else ""
        language = result.get("language_code")
        if not transcript.strip():
            reject_no_speech(file_id, language, duration, version, guardrail_version)
            return
        if not language:
            update_transcription(file_id, "transcription_failed", language=language,
                                 error="The spoken language could not be detected. Please upload clear speech.",
                                 duration_sec=duration, version=version)
            return
        transcript_value = None
        transcript_path = None
        if transcript:
            row = get_file(file_id)
            transcript_value = storage.write_transcript(row, transcript)
            transcript_path = storage.final_transcript_path(row)
        update_transcription(file_id, "validating_transcript", transcript_value,
                             language, duration_sec=duration, version=version)
        validate_transcript_file(file_id, transcript_path, language, duration, result.get("words"),
                                 settings, guardrail_version)
    except Exception:
        logging.exception("Transcription failed for file %s", file_id)
        row = get_file(file_id)
        update_transcription(file_id, "transcription_failed", language=language,
                             error=GENERIC_TRANSCRIPTION_ERROR,
                             duration_sec=row["duration_sec"], version=version)


def process_file(file_id: int):
    row = get_file(file_id)
    if not row:
        return
    try:
        final_path = storage.finalize_audio(row)
        if final_path != row["storage_path"]:
            update_storage_path(file_id, final_path)
            row["storage_path"] = final_path
    except (OSError, ValueError):
        logging.exception("Could not finalize audio for file %s", file_id)
        status = ("transcription_failed"
                  if row["status"] in ("uploaded", "validating_audio", "transcribing", "validating_transcript")
                  else "layer2_failed" if row["status"] == "analyzing_layer2"
                  else "analysis_failed" if row["status"] in ("transcribed", "analyzing")
                  else row["status"])
        set_file_status_error(file_id, status, "Uploaded audio could not be finalized.")
        return
    if row["status"] not in ("uploaded", "validating_audio", "transcribing", "validating_transcript",
                             "transcribed", "analyzing", "analyzing_layer2"):
        if not row["audio_sha256"]:
            try:
                audio_path = storage.stored_audio_path(row)
                if audio_path.is_file():
                    set_audio_hash(file_id, hash_audio(audio_path))
            except ValueError:
                pass
        return
    try:
        audio_path = storage.stored_audio_path(row)
    except ValueError:
        set_file_status_error(file_id, "transcription_failed", "Uploaded audio is unavailable.")
        return
    try:
        settings = guardrail_settings()
        guardrail_version = current_guardrail_version(settings)
    except Exception:
        logging.exception("Guardrail configuration failed for file %s", file_id)
        set_file_status_error(file_id, "transcription_failed", "Audio validation could not be completed.")
        return

    if row["status"] in ("uploaded", "validating_audio", "transcribing"):
        update_audio_validation(file_id, None, guardrail_version)
        decision = validate_audio_input(audio_path, settings)
        update_audio_validation(file_id, decision.duration_sec, guardrail_version)
        if decision.rejection_code:
            reject_file(file_id, decision.rejection_code, decision.error, guardrail_version)
            return
        transcribe_file(file_id, audio_path, settings, guardrail_version)
        return

    if row["status"] == "validating_transcript":
        try:
            transcript_path = storage.stored_transcript_path(row) if row["transcript_path"] else None
        except ValueError:
            set_file_status_error(file_id, "transcription_failed", "Transcript file is unavailable.")
            return
        validate_transcript_file(file_id, transcript_path, row["language"], row["duration_sec"],
                                 None, settings, guardrail_version)
        return

    if row["transcript_path"]:
        try:
            transcript_path = storage.stored_transcript_path(row)
            if transcript_path.is_file():
                if not row["audio_sha256"]:
                    set_audio_hash(file_id, hash_audio(audio_path))
                if row["guardrail_version"] != guardrail_version:
                    update_transcription(file_id, "validating_transcript", row["transcript_path"],
                                         row["language"], duration_sec=row["duration_sec"],
                                         version=row["transcription_version"])
                    validate_transcript_file(file_id, transcript_path, row["language"], row["duration_sec"],
                                             None, settings, guardrail_version)
                elif (row["status"] == "analyzing_layer2" and row["summary"] is not None
                      and row["taxonomy"] is not None
                      and row["analysis_version"] == current_analysis_version()):
                    run_layer2(file_id, transcript_path)
                else:
                    analyze_file(file_id, transcript_path)
                return
        except ValueError:
            pass
    set_file_status_error(file_id, "transcription_failed", "Transcript file is unavailable.")


def resume_files(file_ids: list[int]):
    for file_id in file_ids:
        try:
            process_file(file_id)
        except Exception:
            logging.exception("Could not resume file %s", file_id)
