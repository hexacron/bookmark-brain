import json

import pytest

from lib.llm import parse_json_response


def test_parses_plain_json_object():
    result = parse_json_response('{"summary": "a page", "tags": ["a", "b"]}')
    assert result == {"summary": "a page", "tags": ["a", "b"]}


def test_strips_generic_code_fence():
    text = '```\n{"summary": "a page"}\n```'
    assert parse_json_response(text) == {"summary": "a page"}


def test_strips_json_labeled_code_fence():
    text = '```json\n{"summary": "a page"}\n```'
    assert parse_json_response(text) == {"summary": "a page"}


def test_strips_surrounding_whitespace():
    text = '  \n {"summary": "a page"}  \n '
    assert parse_json_response(text) == {"summary": "a page"}


def test_raises_json_decode_error_on_malformed_json():
    with pytest.raises(json.JSONDecodeError):
        parse_json_response("not json at all")


def test_raises_value_error_on_bare_list():
    with pytest.raises(ValueError, match="expected a JSON object"):
        parse_json_response('["summary", "tags"]')


def test_raises_value_error_on_bare_string():
    with pytest.raises(ValueError, match="expected a JSON object"):
        parse_json_response('"just a string"')


def test_raises_value_error_on_bare_number():
    with pytest.raises(ValueError, match="expected a JSON object"):
        parse_json_response("42")
