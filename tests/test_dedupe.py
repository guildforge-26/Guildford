from jobalerts.dedupe import (
    build_dedupe_key,
    build_posting_record,
    canonicalize_url,
    compute_posting_id,
    normalize_text,
)


def test_canonicalize_url_strips_tracking_params():
    a = canonicalize_url("https://Example.com/jobs/123?utm_source=linkedin&ref=abc")
    b = canonicalize_url("https://example.com/jobs/123")
    assert a == b


def test_canonicalize_url_strips_trailing_slash():
    assert canonicalize_url("https://example.com/jobs/123/") == canonicalize_url("https://example.com/jobs/123")


def test_normalize_text_collapses_whitespace_and_case():
    assert normalize_text("  Director   of BD! ") == "director of bd"


def test_build_dedupe_key_same_job_different_casing_matches():
    a = build_dedupe_key("Acme Corp", "Director of Business Development", "Calgary, AB")
    b = build_dedupe_key("acme corp", "director of business development", "calgary, ab")
    assert a == b


def test_compute_posting_id_prefers_url_and_is_stable():
    id1 = compute_posting_id("https://example.com/jobs/1", "acme|director|calgary")
    id2 = compute_posting_id("https://example.com/jobs/1", "acme|director|calgary")
    id3 = compute_posting_id(None, "acme|director|calgary")
    assert id1 == id2
    assert id1 != id3  # url-based and dedupe-key-based bases must not collide


def test_cross_source_duplicate_same_dedupe_key_same_id():
    record_a = build_posting_record(
        source="email_linkedin", source_id="msg1", title="Director of Business Development",
        company="Acme Corp", location="Calgary, AB", url="https://linkedin.com/jobs/view/999?utm_source=x",
        salary_text=None, posted_at=None, collected_at="2026-09-19T00:00:00+00:00", run_id="run1",
    )
    record_b = build_posting_record(
        source="greenhouse", source_id="42", title="Director of Business Development",
        company="Acme Corp", location="Calgary, AB", url="https://boards.greenhouse.io/acme/jobs/42",
        salary_text=None, posted_at=None, collected_at="2026-09-19T01:00:00+00:00", run_id="run1",
    )
    # Different canonical URLs -> different ids by design (URL-based id), but
    # the SAME dedupe_key -- it's the DB's UNIQUE index on dedupe_key that
    # actually catches this cross-source duplicate at upsert time.
    assert record_a["dedupe_key"] == record_b["dedupe_key"]
