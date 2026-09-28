import os
from typing import Literal

from litellm import completion
from litellm.exceptions import ContentPolicyViolationError, PermissionDeniedError


class ProviderRefusal(Exception):
    pass


def structured_content(response):
    choice = response.choices[0]
    if (getattr(choice.message, "refusal", None)
            or getattr(choice, "finish_reason", None) in ("content_filter", "refusal")):
        raise ProviderRefusal()
    content = choice.message.content
    if not isinstance(content, str) or getattr(choice, "finish_reason", None) == "length":
        raise ValueError("Invalid model response")
    return content


def tier_config(tier: Literal["fast", "quality"]):
    if tier not in ("fast", "quality"):
        raise ValueError("Invalid LLM tier.")
    prefix = f"LLM_{tier.upper()}_"
    model = os.getenv(prefix + "MODEL")
    api_base = os.getenv(prefix + "BASE_URL")
    api_key = os.getenv(prefix + "API_KEY")
    if not model or not api_base:
        raise RuntimeError(f"{tier} LLM tier is not configured.")
    return model, api_base, api_key


def complete(tier: Literal["fast", "quality"], messages: list[dict[str, str]], response_format: dict):
    model, api_base, api_key = tier_config(tier)
    if not api_key:
        raise RuntimeError(f"{tier} LLM tier is not configured.")
    try:
        return completion(model=f"openai/{model}", api_base=api_base, api_key=api_key,
                          messages=messages, response_format=response_format, timeout=60)
    except (ContentPolicyViolationError, PermissionDeniedError) as exc:
        raise ProviderRefusal() from exc
