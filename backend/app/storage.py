import hashlib
import os
import re
import shutil
import uuid
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = BASE_DIR / "storage"
UPLOAD_DIR = STORAGE_DIR / "uploads"
LEGACY_TRANSCRIPT_DIR = STORAGE_DIR / "transcripts"
USER_DIR = STORAGE_DIR / "users"


def relative_path(path: Path):
    return str(path.relative_to(BASE_DIR))


def user_directory(user_id: str):
    return USER_DIR / hashlib.sha256(user_id.encode("utf-8")).hexdigest()


def upload_alias(upload_id: str):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", upload_id):
        raise ValueError("Invalid upload ID")
    return UPLOAD_DIR / upload_id


def final_audio_path(row: dict):
    return user_directory(row["user_id"]) / "audio" / str(row["id"]) / "audio"


def final_transcript_path(row: dict):
    return user_directory(row["user_id"]) / "transcripts" / f"{row['id']}.txt"


def stored_audio_path(row: dict):
    alias = upload_alias(row["upload_id"])
    final = final_audio_path(row)
    if row["storage_path"] == relative_path(alias):
        return alias
    if row["storage_path"] == relative_path(final):
        return final
    raise ValueError("Invalid audio path")


def stored_transcript_path(row: dict):
    value = row["transcript_path"]
    if not value:
        raise ValueError("Transcript path is missing")
    path = BASE_DIR / value
    if (Path(value).is_absolute() or not re.fullmatch(r"[0-9]+\.txt", path.name)
            or path.parent not in (LEGACY_TRANSCRIPT_DIR, user_directory(row["user_id"]) / "transcripts")
            or not path.resolve().is_relative_to(path.parent.resolve())):
        raise ValueError("Invalid transcript path")
    return path


def finalize_audio(row: dict):
    stored_audio_path(row)
    alias = upload_alias(row["upload_id"])
    final = final_audio_path(row)
    final.parent.mkdir(parents=True, exist_ok=True)
    if final.is_symlink():
        raise ValueError("Invalid final audio path")
    if alias.is_symlink():
        if not final.is_file() or alias.resolve() != final.resolve():
            raise ValueError("Invalid upload alias")
        return relative_path(final)
    if not final.is_file():
        if not alias.is_file():
            raise FileNotFoundError("Uploaded audio is unavailable")
        os.link(alias, final)
    elif alias.exists() and not os.path.samefile(alias, final):
        raise ValueError("Conflicting audio files")
    temporary = alias.with_name(f".{alias.name}.{uuid.uuid4().hex}.link")
    try:
        temporary.symlink_to(final)
        os.replace(temporary, alias)
    finally:
        temporary.unlink(missing_ok=True)
    return relative_path(final)


def write_transcript(row: dict, text: str):
    final = final_transcript_path(row)
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = final.with_name(f".{final.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, final)
    finally:
        temporary.unlink(missing_ok=True)
    return relative_path(final)


def migrate_transcript(row: dict):
    source = stored_transcript_path(row)
    if source.parent != LEGACY_TRANSCRIPT_DIR:
        return relative_path(source)
    final = user_directory(row["user_id"]) / "transcripts" / source.name
    if not source.is_file():
        raise FileNotFoundError("Transcript file is unavailable")
    final.parent.mkdir(parents=True, exist_ok=True)
    if final.exists():
        if final.read_bytes() != source.read_bytes():
            raise ValueError("Conflicting transcript files")
    else:
        temporary = final.with_name(f".{final.name}.{uuid.uuid4().hex}.tmp")
        try:
            shutil.copyfile(source, temporary)
            os.replace(temporary, final)
        finally:
            temporary.unlink(missing_ok=True)
    return relative_path(final)


def remove_audio(row: dict):
    stored_audio_path(row)
    alias = upload_alias(row["upload_id"])
    final = final_audio_path(row)
    alias.unlink(missing_ok=True)
    final.unlink(missing_ok=True)
    Path(f"{alias}.info").unlink(missing_ok=True)


def remove_transcript(row: dict):
    stored_transcript_path(row).unlink(missing_ok=True)
