"""Covers the build spec's own pre-launch test requirements:
"confirm duplicates are dropped and the hard filters work by feeding in a
posting under $100,000 and a posting that requires a CPA. Also confirm that
a machine learning engineer posting scores low and an AI operations
posting at a Calgary energy company scores high."

The "scores low/high" half of that needs a live Claude API call against the
real briefing.txt (see docs/test_plan.md, run by hand before scheduling).
What's testable here without either is the cheap prefilter stage: does the
ML engineer posting get dropped before it ever reaches the model, and does
the AI-ops-at-energy-co posting correctly match track 4 and pass through?

Track ids and floors below come straight from the real briefing.txt: Part G
(tracks) and Part B/H (a $100k/year full-time floor, a $5k/month floor for
Track 2 fractional/interim CFO/COO).
"""
from jobalerts.prefilter import (
    disqualifying_requirement,
    is_allowed_geography,
    matched_track,
    parse_salary_figures,
    run_prefilter,
    salary_meets_minimum,
)

MIN_ANNUAL = 100_000
MIN_MONTHLY = 5_000


def test_salary_below_minimum_fails():
    assert salary_meets_minimum("$90,000", MIN_ANNUAL, MIN_MONTHLY) is False


def test_salary_at_or_above_minimum_passes():
    assert salary_meets_minimum("$120,000", MIN_ANNUAL, MIN_MONTHLY) is True
    assert salary_meets_minimum("$100,000", MIN_ANNUAL, MIN_MONTHLY) is True


def test_salary_range_passes_if_upper_bound_clears_minimum():
    assert salary_meets_minimum("$90,000 - $130,000", MIN_ANNUAL, MIN_MONTHLY) is True


def test_salary_hourly_rate_is_annualized():
    # $60/hr * 2080 ~= $124,800 -> clears $100k
    assert salary_meets_minimum("$60/hr", MIN_ANNUAL, MIN_MONTHLY) is True
    # $20/hr * 2080 = $41,600 -> below $100k
    assert salary_meets_minimum("$20/hr", MIN_ANNUAL, MIN_MONTHLY) is False


def test_missing_or_unparseable_salary_does_not_block():
    assert salary_meets_minimum(None, MIN_ANNUAL, MIN_MONTHLY) is True
    assert salary_meets_minimum("competitive", MIN_ANNUAL, MIN_MONTHLY) is True


def test_parse_salary_figures_handles_k_suffix():
    annual, monthly = parse_salary_figures("95K - 120K")
    assert annual == 120_000
    assert monthly == 10_000


def test_fractional_track_uses_monthly_floor_not_annual():
    # $6,000/month clears the $5k Track 2 floor even though it's nowhere
    # near $100k/year -- this is the whole point of the fractional floor.
    assert salary_meets_minimum("$6,000/month", MIN_ANNUAL, MIN_MONTHLY, is_fractional=True) is True
    assert salary_meets_minimum("$4,000 a month", MIN_ANNUAL, MIN_MONTHLY, is_fractional=True) is False
    # The same $6,000/month text must NOT pass the full-time annual floor.
    assert salary_meets_minimum("$6,000/month", MIN_ANNUAL, MIN_MONTHLY, is_fractional=False) is False


def test_geography_allows_canada_and_us_and_remote():
    assert is_allowed_geography("Calgary, AB") is True
    assert is_allowed_geography("Austin, Texas") is True
    assert is_allowed_geography("Remote") is True
    assert is_allowed_geography(None) is True  # unknown location is not dropped at this cheap stage


def test_geography_blocks_clearly_foreign_locations():
    assert is_allowed_geography("London, United Kingdom") is False
    assert is_allowed_geography("Sydney, Australia") is False


def test_disqualifying_requirement_detects_cpa_requirement():
    assert disqualifying_requirement("Must be a CPA in good standing.", ["must be a cpa"]) == "must be a cpa"
    assert disqualifying_requirement("No accounting designation required.", ["must be a cpa"]) is None


def test_disqualifying_requirement_detects_peng_and_pmp(tracks_config):
    disqualifiers = tracks_config["hard_filters"]["disqualifying_phrases"]
    assert disqualifying_requirement("Candidates must hold a P.Eng required for this role.", disqualifiers)
    assert disqualifying_requirement("PMP certification required.", disqualifiers)


def test_ml_engineer_title_does_not_match_any_track(tracks_config):
    assert matched_track("Machine Learning Engineer", tracks_config) is None


def test_ai_operations_title_matches_track4(tracks_config):
    assert matched_track("Director of AI Operations", tracks_config) == "4"


def test_business_development_title_matches_track1(tracks_config):
    assert matched_track("Director of Business Development", tracks_config) == "1"


def test_fractional_cfo_title_matches_track2(tracks_config):
    assert matched_track("Fractional CFO", tracks_config) == "2"


def test_run_prefilter_drops_posting_under_100k(tracks_config):
    posting = {
        "title": "Director of Business Development", "company": "Acme Corp",
        "location": "Calgary, AB", "salary_text": "$85,000", "raw_text": "",
    }
    result = run_prefilter(posting, tracks_config, MIN_ANNUAL, MIN_MONTHLY)
    assert result.passed is False
    assert "salary_below_minimum" in result.reason


def test_run_prefilter_allows_fractional_cfo_above_monthly_floor(tracks_config):
    posting = {
        "title": "Fractional CFO", "company": "Acme Corp", "location": "Calgary, AB",
        "salary_text": "$6,000/month", "raw_text": "",
    }
    result = run_prefilter(posting, tracks_config, MIN_ANNUAL, MIN_MONTHLY)
    assert result.passed is True


def test_run_prefilter_drops_fractional_cfo_below_monthly_floor(tracks_config):
    posting = {
        "title": "Fractional CFO", "company": "Acme Corp", "location": "Calgary, AB",
        "salary_text": "$3,000/month", "raw_text": "",
    }
    result = run_prefilter(posting, tracks_config, MIN_ANNUAL, MIN_MONTHLY)
    assert result.passed is False
    assert "retainer_below_minimum" in result.reason


def test_run_prefilter_drops_posting_requiring_cpa(tracks_config):
    posting = {
        "title": "Fractional CFO", "company": "Acme Corp", "location": "Calgary, AB",
        "salary_text": "$8,000/month", "raw_text": "Candidates must be a CPA in good standing.",
    }
    result = run_prefilter(posting, tracks_config, MIN_ANNUAL, MIN_MONTHLY)
    assert result.passed is False
    assert "disqualifying_requirement" in result.reason


def test_run_prefilter_drops_ml_engineer(tracks_config):
    posting = {
        "title": "Machine Learning Engineer", "company": "Tech Co", "location": "Calgary, AB",
        "salary_text": "$150,000", "raw_text": "",
    }
    result = run_prefilter(posting, tracks_config, MIN_ANNUAL, MIN_MONTHLY)
    assert result.passed is False
    assert "title_no_track_match" in result.reason


def test_run_prefilter_passes_ai_ops_at_calgary_energy_company(tracks_config):
    posting = {
        "title": "Director of AI Operations", "company": "Calgary Energy Co",
        "location": "Calgary, AB", "salary_text": "$160,000",
        "raw_text": "Lead AI transformation across our upstream oil and gas operations.",
    }
    result = run_prefilter(posting, tracks_config, MIN_ANNUAL, MIN_MONTHLY)
    assert result.passed is True
