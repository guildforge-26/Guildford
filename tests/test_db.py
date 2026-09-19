from jobalerts import db as dbmod
from jobalerts.dedupe import build_posting_record


def _sample_posting(**overrides):
    base = dict(
        source="adzuna", source_id="1", title="Director of Business Development",
        company="Acme Corp", location="Calgary, AB", url="https://example.com/jobs/1",
        salary_text="$150,000", posted_at=None, collected_at="2026-09-19T00:00:00+00:00", run_id="run1",
    )
    base.update(overrides)
    return build_posting_record(**base)


def test_upsert_posting_is_idempotent(conn):
    record = _sample_posting()
    id1, is_new1 = dbmod.upsert_posting(conn, record)
    id2, is_new2 = dbmod.upsert_posting(conn, record)
    assert id1 == id2
    assert is_new1 is True
    assert is_new2 is False


def test_upsert_posting_cross_source_duplicate_detected_by_dedupe_key(conn):
    record_a = _sample_posting(source="email_linkedin", source_id="msg1", url="https://linkedin.com/jobs/view/999")
    record_b = _sample_posting(source="greenhouse", source_id="42", url="https://boards.greenhouse.io/acme/jobs/42")
    id_a, is_new_a = dbmod.upsert_posting(conn, record_a)
    id_b, is_new_b = dbmod.upsert_posting(conn, record_b)
    assert is_new_a is True
    assert is_new_b is False  # same dedupe_key (company|title|location) -> treated as the same posting
    assert id_a == id_b


def test_record_alert_is_idempotent(conn):
    posting_id, _ = dbmod.upsert_posting(conn, _sample_posting())
    first = dbmod.record_alert(conn, posting_id, "ntfy", "immediate_a", "run1")
    second = dbmod.record_alert(conn, posting_id, "ntfy", "immediate_a", "run1")
    assert first is True
    assert second is False


def test_score_saved_once_and_marks_posting_scored(conn):
    posting_id, _ = dbmod.upsert_posting(conn, _sample_posting())
    assert dbmod.has_score(conn, posting_id) is False
    row = dict(
        verified=1, track="1", tier="A", total_score=85, breakdown_json="{}", hard_filter_passed=1,
        hard_filter_reason=None, matching_facts_json="[]", top_gaps_json="[]", resume_version="v1",
        warm_angle="angle", next_action="apply", ai_bonus_score=0, ai_bonus_notes=None,
        model_used="gemini-2.5-flash", input_tokens=100, output_tokens=50, cost_usd=0.0, raw_json="{}",
    )
    dbmod.save_score(conn, posting_id, row, "run1")
    assert dbmod.has_score(conn, posting_id) is True
    assert dbmod.get_posting(conn, posting_id)["status"] == "scored"


def test_postings_needing_scoring_includes_enriched_and_errored(conn):
    # A posting whose scoring call fails (e.g. a free-tier rate limit) must
    # be retried on a later run -- dedupe means it can never be re-collected,
    # so this is the only path back into the scoring queue for it.
    enriched_id, _ = dbmod.upsert_posting(conn, _sample_posting(
        source_id="1", title="Director of Operations", url="https://example.com/jobs/1"))
    dbmod.set_posting_enriched(conn, enriched_id, "some posting text")

    errored_id, _ = dbmod.upsert_posting(conn, _sample_posting(
        source_id="2", title="Chief of Staff", url="https://example.com/jobs/2"))
    dbmod.set_posting_enriched(conn, errored_id, "some other posting text")
    dbmod.set_posting_status(conn, errored_id, "error", "429 rate limited")

    needing = {r["id"] for r in dbmod.postings_needing_scoring(conn)}
    assert needing == {enriched_id, errored_id}


def test_postings_needing_scoring_excludes_scored_and_unenriched(conn):
    scored_id, _ = dbmod.upsert_posting(conn, _sample_posting(
        source_id="3", title="General Manager", url="https://example.com/jobs/3"))
    dbmod.set_posting_enriched(conn, scored_id, "text")
    dbmod.save_score(conn, scored_id, dict(
        verified=1, track="3", tier="B", total_score=70, breakdown_json="{}", hard_filter_passed=1,
        hard_filter_reason=None, matching_facts_json="[]", top_gaps_json="[]", resume_version="v1",
        warm_angle="angle", next_action="apply", ai_bonus_score=0, ai_bonus_notes=None,
        model_used="gemini-2.5-flash", input_tokens=100, output_tokens=50, cost_usd=0.0, raw_json="{}",
    ), "run1")

    unenriched_id, _ = dbmod.upsert_posting(conn, _sample_posting(
        source_id="4", title="Growth Director", url="https://example.com/jobs/4"))
    dbmod.set_posting_status(conn, unenriched_id, "prefiltered_out", "salary_below_minimum")

    needing = {r["id"] for r in dbmod.postings_needing_scoring(conn)}
    assert scored_id not in needing
    assert unenriched_id not in needing


def test_processed_emails_idempotent(conn):
    assert dbmod.is_email_processed(conn, "msg1") is False
    dbmod.mark_email_processed(conn, "msg1", "linkedin")
    assert dbmod.is_email_processed(conn, "msg1") is True
    dbmod.mark_email_processed(conn, "msg1", "linkedin")  # must not raise on repeat


def test_digest_log_idempotent(conn):
    assert dbmod.has_digest_sent(conn, "2026-09-19", "am") is False
    dbmod.record_digest_sent(conn, "2026-09-19", "am", "draft123")
    assert dbmod.has_digest_sent(conn, "2026-09-19", "am") is True


def test_applications_due_followup(conn):
    posting_id, _ = dbmod.upsert_posting(conn, _sample_posting())
    dbmod.add_application(conn, posting_id, "Acme Corp", "Director of BD", None, "2026-09-01", "2026-09-08")
    due = dbmod.applications_due_followup(conn, "2026-09-19")
    assert len(due) == 1
    assert due[0]["company"] == "Acme Corp"

    dbmod.update_application_status(conn, due[0]["id"], "rejected")
    due_after = dbmod.applications_due_followup(conn, "2026-09-19")
    assert len(due_after) == 0  # rejected applications drop off the follow-up list
