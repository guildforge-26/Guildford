"""Tests the Workday CXS response parsing against the documented API shape
(see collectors/workday.py's module docstring for the verification caveat
-- this mocks the HTTP layer since a live tenant couldn't be reached from
this sandbox)."""
from types import SimpleNamespace

import pytest

from jobalerts.collectors import workday as workday_mod


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise workday_mod.requests.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._payload


def _page(job_postings, total):
    return {"total": total, "jobPostings": job_postings}


def _job(title="Director of Operations", external_path="/job/Calgary/Director-of-Operations_R1234",
         location="Calgary, AB", posted_on="Posted 3 Days Ago"):
    return {"title": title, "externalPath": external_path, "locationsText": location, "postedOn": posted_on}


def test_fetch_workday_jobs_parses_single_page(monkeypatch):
    calls = []

    def fake_post(url, json, headers, timeout):
        calls.append((url, json))
        return FakeResponse(_page([_job()], total=1))

    monkeypatch.setattr(workday_mod.requests, "post", fake_post)

    postings = workday_mod.fetch_workday_jobs("Clark Builders", "cbgoc", "wd3", "cb")

    assert len(postings) == 1
    posting = postings[0]
    assert posting["title"] == "Director of Operations"
    assert posting["company"] == "Clark Builders"
    assert posting["location"] == "Calgary, AB"
    assert posting["source"] == "workday"
    assert posting["url"] == "https://cbgoc.wd3.myworkdayjobs.com/en-US/cb/job/Calgary/Director-of-Operations_R1234"
    assert posting["posted_at"] == "Posted 3 Days Ago"
    assert len(calls) == 1
    assert calls[0][0] == "https://cbgoc.wd3.myworkdayjobs.com/wday/cxs/cbgoc/cb/jobs"


def test_fetch_workday_jobs_paginates_until_total_reached(monkeypatch):
    pages = [
        _page([_job(title=f"Role {i}", external_path=f"/job/{i}") for i in range(20)], total=25),
        _page([_job(title=f"Role {i}", external_path=f"/job/{i}") for i in range(20, 25)], total=25),
    ]
    call_count = {"n": 0}

    def fake_post(url, json, headers, timeout):
        page = pages[call_count["n"]]
        call_count["n"] += 1
        return FakeResponse(page)

    monkeypatch.setattr(workday_mod.requests, "post", fake_post)

    postings = workday_mod.fetch_workday_jobs("Clark Builders", "cbgoc", "wd3", "cb")

    assert len(postings) == 25
    assert call_count["n"] == 2


def test_fetch_workday_jobs_stops_on_empty_page(monkeypatch):
    def fake_post(url, json, headers, timeout):
        return FakeResponse(_page([], total=0))

    monkeypatch.setattr(workday_mod.requests, "post", fake_post)

    postings = workday_mod.fetch_workday_jobs("Clark Builders", "cbgoc", "wd3", "cb")
    assert postings == []


def test_collect_from_workday_returns_empty_with_no_targets(tmp_path):
    targets_file = tmp_path / "targets.yaml"
    targets_file.write_text("targets: []\n")
    assert workday_mod.collect_from_workday(str(targets_file)) == []


def test_collect_from_workday_isolates_one_bad_target(monkeypatch, tmp_path):
    targets_file = tmp_path / "targets.yaml"
    targets_file.write_text(
        "targets:\n"
        "  - company: Good Co\n"
        "    board_type: workday\n"
        "    tenant: goodco\n"
        "    wd_host: wd1\n"
        "    site: careers\n"
        "  - company: Bad Co\n"
        "    board_type: workday\n"
        "    tenant: badco\n"
        "    wd_host: wd1\n"
        "    site: careers\n"
    )

    def fake_post(url, json, headers, timeout):
        if "goodco" in url:
            return FakeResponse(_page([_job(title="Good Role")], total=1))
        raise workday_mod.requests.ConnectionError("boom")

    monkeypatch.setattr(workday_mod.requests, "post", fake_post)

    postings = workday_mod.collect_from_workday(str(targets_file))
    assert len(postings) == 1
    assert postings[0]["title"] == "Good Role"


def test_collect_from_workday_raises_when_all_targets_fail(monkeypatch, tmp_path):
    targets_file = tmp_path / "targets.yaml"
    targets_file.write_text(
        "targets:\n"
        "  - company: Bad Co\n"
        "    board_type: workday\n"
        "    tenant: badco\n"
        "    wd_host: wd1\n"
        "    site: careers\n"
    )

    def fake_post(url, json, headers, timeout):
        raise workday_mod.requests.ConnectionError("boom")

    monkeypatch.setattr(workday_mod.requests, "post", fake_post)

    with pytest.raises(workday_mod.WorkdayError):
        workday_mod.collect_from_workday(str(targets_file))
