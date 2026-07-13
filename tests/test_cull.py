from lib.cull import conservative_cull


def _bookmark(url, add_date=None, title="Untitled"):
    return {"url": url, "title": title, "folder": "(root)", "add_date": add_date}


def test_keeps_valid_http_and_https_urls():
    bookmarks = [_bookmark("http://example.com"), _bookmark("https://example.org")]
    kept, removed = conservative_cull(bookmarks)
    assert kept == bookmarks
    assert removed == {}


def test_drops_empty_url():
    kept, removed = conservative_cull([_bookmark("")])
    assert kept == []
    assert "empty_url" in removed


def test_drops_junk_schemes():
    junk = [
        _bookmark("chrome://settings"),
        _bookmark("chrome-extension://abc/page.html"),
        _bookmark("about:blank"),
        _bookmark("javascript:void(0)"),
        _bookmark("file:///etc/passwd"),
        _bookmark("data:text/html,hi"),
    ]
    kept, removed = conservative_cull(junk)
    assert kept == []
    assert sum(len(v) for v in removed.values()) == len(junk)


def test_drops_non_http_scheme_not_in_junk_list():
    kept, removed = conservative_cull([_bookmark("ftp://example.com/file")])
    assert kept == []
    assert "no_http" in removed


def test_drops_url_with_no_host():
    kept, removed = conservative_cull([_bookmark("http:///path-only")])
    assert kept == []
    assert "no_host" in removed


def test_drops_localhost_variants():
    localhost_urls = [
        _bookmark("http://localhost/app"),
        _bookmark("http://localhost:8080/app"),
        _bookmark("http://127.0.0.1/app"),
        _bookmark("http://127.0.0.1:3000/app"),
        _bookmark("http://0.0.0.0/app"),
    ]
    kept, removed = conservative_cull(localhost_urls)
    assert kept == []
    assert sum(len(v) for v in removed.values()) == len(localhost_urls)


def test_dedupes_by_url_keeping_more_recent():
    older = _bookmark("https://example.com", add_date=100, title="Old title")
    newer = _bookmark("https://example.com", add_date=200, title="New title")
    kept, removed = conservative_cull([older, newer])
    assert kept == [newer]
    assert removed["duplicate"] == [older]


def test_dedupes_by_url_keeps_first_when_dates_equal():
    first = _bookmark("https://example.com", add_date=100, title="First")
    second = _bookmark("https://example.com", add_date=100, title="Second")
    kept, removed = conservative_cull([first, second])
    assert kept == [first]
    assert removed["duplicate"] == [second]


def test_dedupes_when_duplicate_arrives_before_original_by_date():
    newer_first = _bookmark("https://example.com", add_date=200, title="Newer, seen first")
    older_second = _bookmark("https://example.com", add_date=100, title="Older, seen second")
    kept, removed = conservative_cull([newer_first, older_second])
    assert kept == [newer_first]
    assert removed["duplicate"] == [older_second]


def test_missing_add_date_treated_as_zero_for_dedup():
    no_date = _bookmark("https://example.com", add_date=None, title="No date")
    with_date = _bookmark("https://example.com", add_date=1, title="Has date")
    kept, removed = conservative_cull([no_date, with_date])
    assert kept == [with_date]
    assert removed["duplicate"] == [no_date]


def test_empty_input_returns_empty_output():
    kept, removed = conservative_cull([])
    assert kept == []
    assert removed == {}


def test_preserves_order_of_kept_bookmarks():
    bookmarks = [_bookmark(f"https://example.com/{i}") for i in range(5)]
    kept, _ = conservative_cull(bookmarks)
    assert kept == bookmarks


def test_url_field_missing_entirely_treated_as_empty():
    kept, removed = conservative_cull([{"title": "No url key", "folder": "(root)", "add_date": None}])
    assert kept == []
    assert "empty_url" in removed
