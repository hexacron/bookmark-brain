"""Shared Anthropic client construction and LLM JSON response parsing."""
import json
import os

import anthropic


def build_client() -> anthropic.Anthropic:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set. Did you run setup.sh?")
    return anthropic.Anthropic(api_key=key)


def parse_json_response(text: str) -> dict:
    """Parse an LLM response as a JSON object, stripping markdown code fences if present.

    Raises json.JSONDecodeError on malformed JSON, and ValueError if the parsed
    value isn't a JSON object (e.g. the model returned a bare list or string).
    """
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError(f"expected a JSON object, got {type(parsed).__name__}")
    return parsed
