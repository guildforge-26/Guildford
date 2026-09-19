# AGENTS.md — Constitutional Project Rules

This document is binding on any human or AI agent (including Claude Code)
making changes to this repository. `PROJECT-BLUEPRINT.md` defines the
architecture; this document defines the rules that keep implementation work
consistent with that blueprint. Where the two conflict, raise it explicitly
rather than picking one silently — see §6.

## 1. Purpose

Guildford is a **Level 2 Executive OS**: Streamlit UI + local SQLite storage
+ bounded, user-triggered Gemini reasoning calls. Every rule below exists to
protect that shape: local-first, human-approved, single-stack, no hidden
autonomy.

## 2. Non-Negotiable Architecture Rules

1. **UI is Streamlit only.** No parallel frontend framework, no separate
   JS/React app, no second UI layer.
2. **Storage is local SQLite only.** No Postgres/MySQL, no hosted DB, no
   cloud object storage as a default dependency. One SQLite file is the
   single source of truth.
3. **Reasoning is Gemini only**, accessed through a single, central client
   module. No other LLM provider is added without an amendment (§6).
4. **No hidden autonomy.** The reasoning layer never writes to the database
   directly and never triggers external actions (sending messages, calling
   other APIs, filesystem changes outside the app's own data) without an
   explicit, per-instance user approval step in the UI. This is the Level 2
   boundary — do not build Level 3 behavior under a Level 2 label.
5. **No hidden background jobs.** Any Gemini call or data mutation is the
   direct result of a user action in the current session. No cron jobs,
   daemons, or schedulers are added as part of the default app without an
   amendment.
6. **No new top-level dependencies** (frameworks, services, SaaS
   integrations) without going through §6.

## 3. Coding Standards

- Python 3.11+, type-hinted, formatted consistently (prefer `black`/`ruff`
  conventions once tooling is set up).
- Keep modules small and single-purpose: UI (Streamlit pages), data access
  (SQLite), reasoning (Gemini client), domain logic (task/decision/note
  operations) are separate layers — UI code does not embed raw SQL, and
  data-access code does not call Gemini.
- No speculative abstraction: build what the current feature needs. Don't
  add configurability, plugin systems, or multi-backend support "for later."
- Prefer explicit, readable code over clever code. This is a personal tool
  maintained by a small number of people (including AI agents) — optimize
  for future readability over line count.

## 4. Data & Privacy Rules

- All user data lives in the local SQLite file by default. Nothing is
  synced elsewhere automatically.
- The only outbound network traffic the app initiates is to the Gemini API,
  and only in direct response to a user action.
- AI-generated content that gets persisted must be tagged with provenance
  (`generated_by`) and, where it represents a suggestion (draft task,
  briefing, priority score), must carry an explicit approval flag before it
  is treated as authoritative user data.
- Do not log full prompt/response bodies containing user data to any
  destination outside the local `logs/` directory (if/when logging is
  added), and never to a third-party logging service.

## 5. Security Rules

- Secrets (Gemini API key, etc.) are provided via environment variables or a
  local `.env` file only. `.env` is gitignored; `.env.example` documents
  required variable names with placeholder values, never real ones.
- Never commit API keys, tokens, or personal data fixtures to the
  repository. If a secret is accidentally committed, it must be treated as
  compromised and rotated, not just removed from a later commit.
- Validate/sanitize any data that crosses a trust boundary (e.g. content
  pulled into a Gemini prompt from external sources) enough to prevent
  prompt injection from silently causing the app to take unapproved actions
  — reinforcing §2 rule 4, the approval step is the actual safety boundary,
  not prompt hygiene alone.

## 6. Amendment Process

The architecture in `PROJECT-BLUEPRINT.md` and the rules in this file are
not meant to be permanent or unchangeable, but they are not to be silently
overridden by an implementation detail either. To change them:

1. Propose the change explicitly (to the user, in the PR/commit description,
   or in conversation) — state what rule or architectural element is being
   changed and why the current one is insufficient.
2. Get explicit user sign-off before implementing the change.
3. Update `PROJECT-BLUEPRINT.md` and/or this file in the same change set as
   the code that depends on the new rule, so the documents never drift from
   reality.

Silent deviation (e.g. adding a second database, a new LLM provider, or an
autonomous action path without discussion) is not permitted regardless of
how small or "temporary" it seems.

## 7. What Agents Must Not Do

- Must not add scope beyond what was requested (new pages, new integrations,
  speculative features) without asking first.
- Must not weaken the human-approval gate on AI-generated content that gets
  persisted or acted upon.
- Must not introduce a second storage engine, UI framework, or LLM provider.
- Must not commit secrets or real user data fixtures.
- Must not write feature code before the architecture it depends on is
  confirmed understood (this file and the blueprint) — when in doubt about
  which layer something belongs in, ask rather than guess.
