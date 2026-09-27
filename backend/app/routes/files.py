import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response

from app import storage
from app.auth import current_uid, uid_from_authorization
from app.database import (delete_owned_file, get_file, get_file_by_upload_id, list_files,
                          register_file, set_file_error)
from app.filters import filter_files, parse_file_filters
from app.guardrails import current_guardrail_version, guardrail_settings
from app.layer2 import prepare_layer2, run_layer2
from app.models import Layer2Request, TusHook
from app.transcription import process_file
from app.upload_options import parse_layer2_config, parse_layer2_options, validate_original_name


router = APIRouter()


def file_response(file: dict):
    raw_taxonomy = file.pop("taxonomy")
    file.pop("layer2_pending_options", None)
    taxonomy = json.loads(raw_taxonomy) if raw_taxonomy else {}
    file["layer2_options"] = json.loads(file["layer2_options"])
    file["layer2_config"] = json.loads(file["layer2_config"])
    file["layer2_results"] = json.loads(file["layer2_results"])
    file["layer2_version"] = json.loads(file["layer2_version"])
    file.update({"professional_topics": taxonomy.get("professional_topics", []),
                 "personal_topics": taxonomy.get("personal_topics", []),
                 "upcoming_events": taxonomy.get("upcoming_events", []),
                 "transcript_available": file["transcript_path"] is not None})
    return file


@router.get("/files")
def get_files(request: Request, user_id: str = Depends(current_uid)):
    return [file_response(file) for file in filter_files(list_files(user_id), parse_file_filters(request))]


@router.get("/files/{file_id}")
def get_file_details(file_id: int, user_id: str = Depends(current_uid)):
    file = get_file(file_id, user_id)
    if file is None:
        raise HTTPException(status_code=404, detail="File not found")
    return file_response(file)


@router.get("/files/{file_id}/transcript")
def get_transcript(file_id: int, user_id: str = Depends(current_uid)):
    file = get_file(file_id, user_id)
    if file is None:
        raise HTTPException(status_code=404, detail="File not found")
    if not file["transcript_path"]:
        raise HTTPException(status_code=404, detail="Transcript not available")
    try:
        path = storage.stored_transcript_path(file)
    except ValueError:
        set_file_error(file_id, "Transcript file is unavailable.")
        raise HTTPException(status_code=404, detail="Transcript not available") from None
    if not path.is_file():
        set_file_error(file_id, "Transcript file is unavailable.")
        raise HTTPException(status_code=404, detail="Transcript not available")
    try:
        return {"transcript": path.read_text(encoding="utf-8")}
    except (OSError, UnicodeError):
        set_file_error(file_id, "Transcript file is unavailable.")
        raise HTTPException(status_code=404, detail="Transcript not available") from None


@router.post("/files/{file_id}/layer2")
def request_layer2(file_id: int, body: Layer2Request, background_tasks: BackgroundTasks,
                   response: Response, user_id: str = Depends(current_uid)):
    result, transcript_path = prepare_layer2(file_id, user_id, body.options, body.config)
    if result == "not_found":
        raise HTTPException(status_code=404, detail="File not found")
    if result == "conflict":
        raise HTTPException(status_code=409, detail="File is still processing")
    if result == "unavailable":
        raise HTTPException(status_code=409, detail="Transcript or Layer 1 result is not available")
    if result == "scheduled":
        background_tasks.add_task(run_layer2, file_id, transcript_path)
        response.status_code = 202
    return file_response(get_file(file_id, user_id))


@router.delete("/files/{file_id}", status_code=204)
def delete_file(file_id: int, user_id: str = Depends(current_uid)):
    result = delete_owned_file(file_id, user_id)
    if result is None:
        raise HTTPException(status_code=404, detail="File not found")
    if result is False:
        raise HTTPException(status_code=409, detail="File is still processing")


@router.post("/hooks/tusd")
def tusd_hook(hook: TusHook, request: Request, background_tasks: BackgroundTasks):
    if not request.client or request.client.host not in ("127.0.0.1", "::1"):
        raise HTTPException(status_code=403, detail="Local hook only")

    upload = hook.Event.Upload
    metadata = upload.MetaData

    if hook.Type == "pre-create":
        headers = hook.Event.HTTPRequest.Header
        authorization = next(
            (value[0] for key, value in headers.items() if key.lower() == "authorization" and value),
            None,
        )
        try:
            user_id = uid_from_authorization(authorization)
        except HTTPException:
            return {"RejectUpload": True, "HTTPResponse": {"StatusCode": 401}}
        if metadata.get("user_id") != user_id:
            return {"RejectUpload": True, "HTTPResponse": {"StatusCode": 400}}
        try:
            validate_original_name(metadata.get("filename"))
            options = parse_layer2_options(metadata)
            parse_layer2_config(metadata, options)
        except ValueError:
            return {"RejectUpload": True, "HTTPResponse": {"StatusCode": 400}}
        return {}

    if hook.Type != "post-finish" or upload.IsPartial:
        return {}

    storage_data = upload.Storage or {}
    try:
        layer2_options = parse_layer2_options(metadata)
        layer2_config = parse_layer2_config(metadata, layer2_options)
        validate_original_name(metadata.get("filename"))
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid upload metadata") from None
    raw_path = storage_data.get("Path")
    if not upload.ID or not metadata.get("user_id") or not raw_path:
        raise HTTPException(status_code=422, detail="Incomplete upload data")
    if get_file_by_upload_id(upload.ID):
        return {}

    try:
        alias = storage.upload_alias(upload.ID)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid upload ID") from None
    path = Path(raw_path)
    path = (path if path.is_absolute() else storage.BASE_DIR / path).absolute()
    if path != alias or path.is_symlink() or not path.is_file():
        raise HTTPException(status_code=422, detail="Upload file is missing or outside storage/uploads")
    if (upload.Size is None or upload.Offset is None or upload.SizeIsDeferred
            or upload.Size < 0 or upload.Offset != upload.Size or path.stat().st_size != upload.Size):
        raise HTTPException(status_code=422, detail="Upload size does not match completed tusd upload")

    settings = guardrail_settings()
    file_id = register_file(metadata["user_id"], upload.ID, metadata["filename"],
                            storage.relative_path(path), layer2_options, layer2_config,
                            settings.max_active_files_per_user, current_guardrail_version(settings))
    if file_id is not None:
        background_tasks.add_task(process_file, file_id)
    return {}
