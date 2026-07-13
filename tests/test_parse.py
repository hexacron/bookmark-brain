import json

import pytest

from lib.parse import parse_any, parse_chrome_json, parse_html_export


NETSCAPE_HEADER = (
    "<!DOCTYPE NETSCAPE-Bookmark-file-1>\n"
    "<TITLE>Bookmarks</TITLE>\n"
    "<H1>Bookmarks</H1>\n"
    "<DL><p>\n"
)


def test_parse_html_export_flat_list(tmp_path):
    html = NETSCAPE_HEADER + (
        '<DT><A HREF="https://example.com" ADD_DATE="1000">Example</A>\n'
        '<DT><A HREF="https://example.org" ADD_DATE="2000">Example Org</A>\n'
        "</DL><p>\n"
    )
    path = tmp_path / "bookmarks.html"
    path.write_text(html, encoding="utf-8")

    result = parse_html_export(path)

    assert result == [
        {"title": "Example", "url": "https://example.com", "add_date": 1000, "folder": "(root)"},
        {"title": "Example Org", "url": "https://example.org", "add_date": 2000, "folder": "(root)"},
    ]


def test_parse_html_export_nested_folders(tmp_path):
    html = NETSCAPE_HEADER + (
        "<DT><H3>Work</H3>\n"
        "<DL><p>\n"
        '<DT><A HREF="https://work.example.com" ADD_DATE="1000">Work Link</A>\n'
        "<DT><H3>Deep</H3>\n"
        "<DL><p>\n"
        '<DT><A HREF="https://deep.example.com" ADD_DATE="2000">Deep Link</A>\n'
        "</DL><p>\n"
        "</DL><p>\n"
        "</DL><p>\n"
    )
    path = tmp_path / "bookmarks.html"
    path.write_text(html, encoding="utf-8")

    result = parse_html_export(path)

    assert result == [
        {"title": "Work Link", "url": "https://work.example.com", "add_date": 1000, "folder": "Work"},
        {"title": "Deep Link", "url": "https://deep.example.com", "add_date": 2000, "folder": "Work/Deep"},
    ]


def test_parse_html_export_missing_add_date_is_none(tmp_path):
    html = NETSCAPE_HEADER + (
        '<DT><A HREF="https://example.com">No Date</A>\n'
        "</DL><p>\n"
    )
    path = tmp_path / "bookmarks.html"
    path.write_text(html, encoding="utf-8")

    result = parse_html_export(path)

    assert result[0]["add_date"] is None


def test_parse_html_export_empty_file(tmp_path):
    path = tmp_path / "bookmarks.html"
    path.write_text(NETSCAPE_HEADER + "</DL><p>\n", encoding="utf-8")

    assert parse_html_export(path) == []


def _chrome_json(bookmark_bar_children=None, other_children=None):
    return {
        "roots": {
            "bookmark_bar": {
                "name": "Bookmarks bar",
                "type": "folder",
                "children": bookmark_bar_children or [],
            },
            "other": {
                "name": "Other bookmarks",
                "type": "folder",
                "children": other_children or [],
            },
        }
    }


def test_parse_chrome_json_flat_list(tmp_path):
    data = _chrome_json(bookmark_bar_children=[
        {"type": "url", "name": "Example", "url": "https://example.com", "date_added": "13300000000000000"},
    ])
    path = tmp_path / "Bookmarks"
    path.write_text(json.dumps(data), encoding="utf-8")

    result = parse_chrome_json(path)

    assert len(result) == 1
    assert result[0]["title"] == "Example"
    assert result[0]["url"] == "https://example.com"
    assert result[0]["folder"] == "Bookmarks bar"


def test_parse_chrome_json_converts_webkit_timestamp_to_unix_seconds(tmp_path):
    # 11_644_473_600 seconds between the Windows epoch (1601) and Unix epoch (1970).
    # A date_added of exactly that many seconds (in microseconds) should map to unix time 0.
    webkit_epoch_offset_micros = str(11_644_473_600 * 1_000_000)
    data = _chrome_json(bookmark_bar_children=[
        {"type": "url", "name": "Epoch", "url": "https://example.com", "date_added": webkit_epoch_offset_micros},
    ])
    path = tmp_path / "Bookmarks"
    path.write_text(json.dumps(data), encoding="utf-8")

    result = parse_chrome_json(path)

    assert result[0]["add_date"] == 0


def test_parse_chrome_json_missing_date_added_is_none(tmp_path):
    data = _chrome_json(bookmark_bar_children=[
        {"type": "url", "name": "No Date", "url": "https://example.com"},
    ])
    path = tmp_path / "Bookmarks"
    path.write_text(json.dumps(data), encoding="utf-8")

    result = parse_chrome_json(path)

    assert result[0]["add_date"] is None


def test_parse_chrome_json_nested_folders_join_with_slash(tmp_path):
    data = _chrome_json(bookmark_bar_children=[
        {
            "type": "folder",
            "name": "Dev",
            "children": [
                {"type": "url", "name": "Deep", "url": "https://deep.example.com"},
            ],
        },
    ])
    path = tmp_path / "Bookmarks"
    path.write_text(json.dumps(data), encoding="utf-8")

    result = parse_chrome_json(path)

    assert result[0]["folder"] == "Bookmarks bar/Dev"


def test_parse_chrome_json_walks_bookmark_bar_and_other_roots(tmp_path):
    data = _chrome_json(
        bookmark_bar_children=[{"type": "url", "name": "Bar", "url": "https://bar.example.com"}],
        other_children=[{"type": "url", "name": "Other", "url": "https://other.example.com"}],
    )
    path = tmp_path / "Bookmarks"
    path.write_text(json.dumps(data), encoding="utf-8")

    result = parse_chrome_json(path)

    urls = {b["url"] for b in result}
    assert urls == {"https://bar.example.com", "https://other.example.com"}


def test_parse_any_detects_by_extension(tmp_path):
    html_path = tmp_path / "export.html"
    html_path.write_text(NETSCAPE_HEADER + '<DT><A HREF="https://example.com">E</A>\n</DL><p>\n',
                          encoding="utf-8")
    json_path = tmp_path / "export.json"
    json_path.write_text(json.dumps(_chrome_json()), encoding="utf-8")

    assert parse_any(html_path) == parse_html_export(html_path)
    assert parse_any(json_path) == parse_chrome_json(json_path)


def test_parse_any_detects_chrome_json_by_filename(tmp_path):
    path = tmp_path / "Bookmarks"
    path.write_text(json.dumps(_chrome_json()), encoding="utf-8")

    assert parse_any(path) == parse_chrome_json(path)


def test_parse_any_sniffs_json_content_without_extension(tmp_path):
    path = tmp_path / "mystery_export"
    path.write_text(json.dumps(_chrome_json()), encoding="utf-8")

    assert parse_any(path) == parse_chrome_json(path)


def test_parse_any_sniffs_html_content_without_extension(tmp_path):
    path = tmp_path / "mystery_export"
    path.write_text(NETSCAPE_HEADER + "</DL><p>\n", encoding="utf-8")

    assert parse_any(path) == []


def test_parse_any_raises_on_unrecognizable_content(tmp_path):
    path = tmp_path / "mystery_export"
    path.write_text("just some plain text, not a bookmarks file", encoding="utf-8")

    with pytest.raises(ValueError, match="Could not detect bookmarks format"):
        parse_any(path)
