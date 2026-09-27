import firebase_admin
from fastapi import Header, HTTPException
from firebase_admin import auth


firebase_admin.initialize_app()


def uid_from_authorization(authorization: str | None) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    try:
        uid = auth.verify_id_token(token)["uid"]
    except (auth.InvalidIdTokenError, auth.ExpiredIdTokenError,
            auth.RevokedIdTokenError, auth.UserDisabledError, KeyError) as exc:
        raise HTTPException(status_code=401, detail="Invalid Firebase token") from exc
    return uid


def current_uid(authorization: str | None = Header(default=None)) -> str:
    return uid_from_authorization(authorization)
