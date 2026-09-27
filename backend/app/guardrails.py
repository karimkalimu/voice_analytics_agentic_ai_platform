import hashlib
import json
import logging
import math
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from app.audio import probe_audio, rms_normalized
from app.content_policy import (contains_deterministic_profanity, content_policy_identity,
                                contextual_profanity)


@dataclass(frozen=True)
class GuardrailSettings:
    max_duration_sec: float
    max_size_mb: float
    max_active_files_per_user: int
    min_audio_rms: float
    min_transcript_words: int
    min_transcript_words_per_minute: float
    min_avg_word_confidence: float


@dataclass(frozen=True)
class GuardrailDecision:
    rejection_code: str | None = None
    error: str | None = None
    duration_sec: float | None = None


def number(name: str, default: str, minimum: float = 0, maximum: float | None = None):
    try:
        value = float(os.getenv(name, default))
    except ValueError as exc:
        raise RuntimeError(f"Invalid {name}") from exc
    if not math.isfinite(value) or value < minimum or maximum is not None and value > maximum:
        raise RuntimeError(f"Invalid {name}")
    return value


def integer(name: str, default: str, minimum: int = 1):
    value = number(name, default, minimum)
    if not value.is_integer():
        raise RuntimeError(f"Invalid {name}")
    return int(value)


def guardrail_settings():
    return GuardrailSettings(
        max_duration_sec=number("POC_MAX_AUDIO_DURATION_SEC", "90", 1),
        max_size_mb=number("POC_MAX_AUDIO_SIZE_MB", "25", 0.001),
        max_active_files_per_user=integer("POC_MAX_ACTIVE_FILES_PER_USER", "5"),
        min_audio_rms=number("POC_MIN_AUDIO_RMS", "0.001", 0, 1),
        min_transcript_words=integer("POC_MIN_TRANSCRIPT_WORDS", "3"),
        min_transcript_words_per_minute=number("POC_MIN_TRANSCRIPT_WORDS_PER_MINUTE", "5", 0),
        min_avg_word_confidence=number("POC_MIN_AVG_WORD_CONFIDENCE", "0.35", 0, 1),
    )


def display_number(value: float):
    return str(int(value)) if value.is_integer() else str(value)


def current_guardrail_version(settings: GuardrailSettings | None = None):
    settings = settings or guardrail_settings()
    identity = ["audio-input-guardrails-v1", asdict(settings), content_policy_identity()]
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
    return f"{os.getenv('GUARDRAIL_VERSION') or '1'}:{digest}"


def validate_audio_input(audio_path: Path, settings: GuardrailSettings):
    try:
        size = audio_path.stat().st_size
    except Exception:
        logging.exception("Audio file could not be read at %s", audio_path)
        return GuardrailDecision("invalid_audio", "The uploaded file is not valid decodable audio.")
    if size > settings.max_size_mb * 1024 * 1024:
        return GuardrailDecision("file_size_exceeded",
                                 f"This POC supports audio files up to {display_number(settings.max_size_mb)} MB.")
    try:
        duration = probe_audio(audio_path)
    except Exception:
        logging.exception("Audio probe failed for %s", audio_path)
        return GuardrailDecision("invalid_audio", "The uploaded file is not valid decodable audio.")
    if duration > settings.max_duration_sec:
        return GuardrailDecision("duration_exceeded",
                                 f"This POC supports audio up to {display_number(settings.max_duration_sec)} seconds.",
                                 duration)
    try:
        rms = rms_normalized(audio_path)
    except Exception:
        logging.exception("Audio decode failed for %s", audio_path)
        return GuardrailDecision("invalid_audio", "The uploaded file is not valid decodable audio.", duration)
    if rms < settings.min_audio_rms:
        return GuardrailDecision("insufficient_audible_content",
                                 "The audio does not contain enough audible content for analysis.", duration)
    return GuardrailDecision(duration_sec=duration)


def usable_words(transcript: str):
    return re.findall(r"[A-Za-z]+(?:['’][A-Za-z]+)*", transcript)


def validate_transcript_output(transcript: str, language: str, duration_sec: float,
                               words: list | None, settings: GuardrailSettings):
    if language != "en" and not language.startswith(("en_", "en-")):
        return GuardrailDecision("unsupported_language", "This POC currently supports English speech only.",
                                 duration_sec)
    minimum_words = max(settings.min_transcript_words,
                        math.ceil(duration_sec / 60 * settings.min_transcript_words_per_minute))
    if len(usable_words(transcript)) < minimum_words:
        return GuardrailDecision("insufficient_speech",
                                 "The audio does not contain enough intelligible speech for analysis.", duration_sec)
    confidences = [word.get("confidence") for word in words or [] if isinstance(word, dict)]
    confidences = [value for value in confidences
                   if (isinstance(value, (int, float)) and not isinstance(value, bool)
                       and math.isfinite(value) and 0 <= value <= 1)]
    if (len(confidences) >= settings.min_transcript_words
            and sum(confidences) / len(confidences) < settings.min_avg_word_confidence):
        return GuardrailDecision("unreliable_transcription",
                                 "The speech could not be transcribed reliably enough for analysis.", duration_sec)
    if contains_deterministic_profanity(transcript):
        return GuardrailDecision("prohibited_content",
                                 "This POC does not process audio containing profanity.", duration_sec)
    try:
        contains_profanity = contextual_profanity(transcript)
    except Exception:
        logging.exception("Contextual audio content validation failed")
        return GuardrailDecision("content_validation_failed",
                                 "Audio content validation could not be completed.", duration_sec)
    if contains_profanity:
        return GuardrailDecision("prohibited_content",
                                 "This POC does not process audio containing profanity.", duration_sec)
    return GuardrailDecision(duration_sec=duration_sec)


def guardrails_response(settings: GuardrailSettings | None = None):
    settings = settings or guardrail_settings()
    return {
        "limits": {
            "max_audio_duration_sec": settings.max_duration_sec,
            "max_audio_size_mb": settings.max_size_mb,
            "max_active_files_per_user": settings.max_active_files_per_user,
            "min_audio_rms": settings.min_audio_rms,
            "min_transcript_words": settings.min_transcript_words,
            "min_transcript_words_per_minute": settings.min_transcript_words_per_minute,
            "min_avg_word_confidence": settings.min_avg_word_confidence,
        },
        "sections": [
            {"id": "access_upload_protection", "title": "Access and upload protection", "items": [
                "Firebase ID tokens are verified, and the authenticated UID must match the upload user_id metadata.",
                "File list, details, transcript, Layer 2, and delete operations are limited to the authenticated owner.",
                "Filenames must be printable, at most 255 characters, not \".\" or \"..\", and contain no path separators.",
                "Only the Layer 2 option IDs rms, count_nouns, count_adjectives, sentiment, and topic_mentions and their supported configuration fields are accepted.",
                "Completed uploads must resolve to regular files inside managed upload storage.",
            ]},
            {"id": "audio_validation", "title": "Audio validation", "items": [
                "The upload must contain a decodable audio stream with a positive duration.",
                f"File size cannot exceed {display_number(settings.max_size_mb)} MB.",
                f"Audio duration cannot exceed {display_number(settings.max_duration_sec)} seconds.",
                f"Normalized RMS must be at least {settings.min_audio_rms}.",
                f"A user cannot exceed {settings.max_active_files_per_user} actively processing files.",
            ]},
            {"id": "transcript_content_validation", "title": "Transcript and content validation", "items": [
                "The detected language must be English.",
                f"Usable words must meet the greater of {settings.min_transcript_words} words and the duration-based requirement of {display_number(settings.min_transcript_words_per_minute)} words per minute.",
                f"When at least {settings.min_transcript_words} valid word-confidence values are available, their average must be at least {settings.min_avg_word_confidence}.",
                "Profanity is checked with a deterministic policy and a contextual classifier.",
                "Failed policy checks persist status rejected, a rejection_code, and a safe user-facing error.",
            ]},
            {"id": "llm_input_isolation", "title": "LLM input isolation", "items": [
                "Transcripts and user-entered topic values are serialized separately and treated as untrusted data.",
                "Instructions, role claims, and prompt-change requests inside user data are ignored.",
                "Only backend-controlled system prompts define analysis behavior.",
                "User content cannot request or reveal backend instructions.",
            ]},
            {"id": "layer1_output_validation", "title": "Layer 1 output validation", "items": [
                "Output must contain only summary and taxonomy.",
                "summary must be trimmed, non-empty, and between 1 and 1200 characters.",
                "taxonomy must contain professional_topics, personal_topics, and upcoming_events arrays.",
                "Every taxonomy label must be a non-empty canonical string no longer than 80 characters.",
                "Placeholder labels None, N/A, and Not applicable are rejected.",
                "Case-insensitive duplicate labels, including duplicates across categories and reordered-word duplicates, are rejected.",
                "Missing fields, incorrect types, or additional fields cause analysis_failed.",
            ]},
            {"id": "layer2_validation", "title": "Layer 2 validation", "items": [
                "rms is calculated deterministically from mono 16 kHz PCM audio and returns only {\"rms_normalized\": <number from 0 to 1>}.",
                "count_nouns, count_adjectives, and topic_mentions return only {\"count\": <non-negative integer>}.",
                "sentiment returns only {\"label\": \"positive\"}, {\"label\": \"neutral\"}, or {\"label\": \"negative\"}.",
                "count_nouns.unique_only must be a boolean.",
                "topic_mentions.topic is trimmed, required, and limited to 1–100 characters.",
                "Missing fields, incorrect types, unsupported or duplicate options, and additional fields are rejected.",
            ]},
            {"id": "failure_handling", "title": "Failure handling", "items": [
                "Rejections and processing failures remain stored on the file.",
                "User-facing errors never contain internal exception details.",
                "Existing successful Layer 1 and Layer 2 results remain available when a later Layer 2 analysis fails.",
                "Files in terminal failure or rejected states remain visible and can be deleted.",
            ]},
        ],
    }
