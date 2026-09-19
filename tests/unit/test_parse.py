from finagent.ingest.parse import strip_repeated_lines


def test_strip_repeated_lines_drops_running_headers_and_page_numbers():
    pages = [f"Annual Report 2025 | {n}\n{w} body\nfooter" for n, w in enumerate("abcdefgh", 1)]
    out = strip_repeated_lines(pages)
    assert all("Annual Report" not in p and "footer" not in p for p in out)
    assert out[2] == "c body"  # page-specific line survives


def test_strip_repeated_lines_leaves_short_docs_alone():
    assert strip_repeated_lines(["a", "a"]) == ["a", "a"]
