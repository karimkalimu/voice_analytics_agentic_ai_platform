import json
import re
import unicodedata
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from app.llm import complete, structured_content, tier_config
from app.prompts import load_prompt


POLICY_PATH = Path(__file__).resolve().parent.parent / "policies" / "english_profanity.txt"
LEET_MAP = str.maketrans({"@": "a", "4": "a", "3": "e", "1": "i", "!": "i",
                         "0": "o", "$": "s", "5": "s", "7": "t"})


class ContentGuardrailResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    contains_profanity: bool


def normalize_term(value: str):
    return unicodedata.normalize("NFKC", value).casefold().translate(LEET_MAP)


def profanity_terms():
    return {normalize_term(line.strip()) for line in POLICY_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()}


def contains_deterministic_profanity(transcript: str):
    text = unicodedata.normalize("NFKC", transcript).casefold()
    candidates = set(re.findall(r"[a-z0-9@!$]+", text))
    candidates.update(re.sub(r"[._-]", "", value) for value in
                      re.findall(r"[a-z0-9@!$]+(?:[._-][a-z0-9@!$]+)+", text))
    candidates.update(re.sub(r"[^a-z0-9@!$]", "", value) for value in
                      re.findall(r"(?<![a-z0-9])(?:[a-z0-9@!$][^a-z0-9]+){2,}[a-z0-9@!$](?![a-z0-9])", text))
    normalized = {normalize_term(value) for value in candidates}
    return bool(normalized & profanity_terms())


def contextual_profanity(transcript: str):
    schema = ContentGuardrailResult.model_json_schema()
    response = complete(
        "fast",
        [{"role": "system", "content": load_prompt("audio_content_guardrail")},
         {"role": "user", "content": json.dumps({"transcript": transcript})}],
        {"type": "json_schema", "json_schema": {"name": "audio_content_guardrail",
                                                 "strict": True, "schema": schema}},
    )
    return ContentGuardrailResult.model_validate_json(
        structured_content(response), strict=True,
    ).contains_profanity


def content_policy_identity():
    model, base_url, _ = tier_config("fast")
    return [POLICY_PATH.read_text(encoding="utf-8"), load_prompt("audio_content_guardrail"),
            ContentGuardrailResult.model_json_schema(), model, base_url]
