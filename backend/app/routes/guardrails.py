from fastapi import APIRouter

from app.guardrails import guardrails_response


router = APIRouter()


@router.get("/guardrails")
def get_guardrails():
    return guardrails_response()
