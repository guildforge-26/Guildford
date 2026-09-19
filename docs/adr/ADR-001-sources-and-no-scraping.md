# ADR-001: Source choices and why nothing here scrapes LinkedIn or Indeed

## Status
Accepted

## Context
LinkedIn and Indeed's terms of service prohibit automated scraping, and
both actively detect and block it -- doing so risks Tommy's personal
accounts being restricted. But their postings are still valuable signal,
and Tommy already has saved searches emailing him new matches.

## Decision
Never touch LinkedIn or Indeed directly. Instead, read four sources:

1. **Gmail alert emails (read-only Gmail API).** Tommy creates saved
   searches on LinkedIn and Indeed that email him new postings; the system
   reads those emails (not the sites) to extract title/company/location/
   link. This covers the same postings as scraping would, at zero ToS risk,
   because the mail is addressed to Tommy and Gmail's API is first-party.

2. **Public ATS board JSON (Greenhouse, Lever, Ashby, Workable).** Most
   employers who use these platforms publish a public JSON feed of their
   own open roles, meant for embedding on their own careers page. Reading
   it is reading a company's own public API about its own job postings --
   unrelated to LinkedIn/Indeed's terms. `targets.yaml` lists which
   companies to check.

3. **Adzuna (Canada endpoint).** A public, keyed, documented job-search
   API whose terms permit this kind of personal-use querying.

4. **Job Bank Canada / Government of Canada / municipal feeds.** Job Bank
   publishes labour-market *open data* (bulk/statistical), but no
   documented real-time public search API for individual postings was
   found while building this. Rather than fabricate an endpoint and claim
   it works, `collectors/job_bank.py` is wired for a generic RSS/XML feed
   and is inert (returns nothing, logs that it's unconfigured) until a
   real, verified feed URL is set in `.env`. This keeps the door open
   without pretending a nonexistent integration is real.

## Consequences
- No dependency on LinkedIn/Indeed's stability, rate limits, or anti-bot
  measures, and zero risk to Tommy's accounts.
- Coverage from sources A-C is good but not exhaustive; source D is a
  known gap until a real feed is confirmed (tracked in
  `docs/requirements.md` section 11).
- Email-alert parsing (source A) is inherently a best-effort heuristic
  against HTML templates that can change -- see `collectors/gmail_alerts.py`
  and the note in `docs/test_plan.md` about checking the first few real
  digests.
