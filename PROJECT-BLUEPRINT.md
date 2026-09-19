# PROJECT BLUEPRINT — Guildford

## 1. Product Vision

Guildford is a **Level 2 Executive OS**: a local-first personal command center
that helps a single executive/founder triage information, track decisions and
commitments, and get AI-assisted judgment on demand — without handing data to
a third-party cloud service beyond the model calls the user explicitly makes.

### Level definitions (roadmap framing)

| Level | Description |
|---|---|
| **Level 0** | Static notes / spreadsheets. No structure, no assistance. |
| **Level 1** | Structured dashboard. Data is organized (tasks, notes, calendar) but there is no reasoning layer — the user does all synthesis themselves. |
| **Level 2 (this project)** | Structured dashboard **+ an LLM reasoning layer** (Gemini) that summarizes, drafts, prioritizes, and flags — but every consequential action requires explicit human approval. The system suggests; it does not act autonomously. |
| **Level 3 (future, out of scope now)** | Bounded autonomous execution — the assistant can take pre-approved classes of action (e.g. send a drafted email) without a human in the loop for each instance. |

Guildford targets Level 2 only. Anything that would push the system toward
autonomous action without per-instance human approval is a Level 3 feature
and is explicitly **out of scope** until a deliberate, separate decision is
made to move up a level (see AGENTS.md §6, Amendment Process).

## 2. Core Tech Stack

| Layer | Choice | Why |
|---|---|---|
| UI | **Streamlit** | Fast to build and iterate on a single-user internal tool; Python-native, no separate frontend build/deploy pipeline. |
| Storage | **Local SQLite** (single file, e.g. `data/guildford.db`) | Zero-ops, file-based, trivially backed up, no network dependency, keeps the user's data on their own machine. |
| Reasoning | **Gemini API** | Used only for specific, bounded reasoning tasks (summarization, drafting, prioritization, Q&A over the user's own data) — never as an implicit background agent. |
| Language/runtime | Python 3.11+ | Matches Streamlit and the broader ecosystem of the SQLite/Gemini client libraries. |

No other database, message queue, background worker framework, or cloud
storage/service is part of the stack unless AGENTS.md's amendment process is
followed.

## 3. System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Streamlit App (UI)                  │
│  Pages: Dashboard | Inbox/Triage | Tasks | Decisions |   │
│         Knowledge Base | Daily Briefing | Settings       │
└───────────────┬───────────────────────────┬─────────────┘
                │                           │
                ▼                           ▼
      ┌──────────────────┐         ┌──────────────────────┐
      │   Data Layer      │         │   Reasoning Layer      │
      │  (SQLite, local)  │◄────────┤  (Gemini API client)   │
      │  data/guildford.db│  reads  │  bounded, explicit     │
      └──────────────────┘  data   │  per-call invocations   │
                                    └──────────────────────┘
```

- The **Data Layer** is the single source of truth. All persistent state
  (tasks, notes, decisions, briefing history, settings) lives in SQLite.
- The **Reasoning Layer** is stateless between calls: it is given data read
  from SQLite, asked to do one bounded task (summarize, draft, score,
  prioritize), and returns a result that is shown to the user for approval
  before anything is written back to the database.
- The UI never talks to Gemini directly — it goes through a single reasoning
  client module so prompts, guardrails, and logging are centralized.

## 4. Data Model (initial sketch)

Core tables (exact schema to be finalized in `sql/schema.sql` when
implementation begins):

- `items` — inbox/triage entries (source, raw content, status, created_at)
- `tasks` — actionable items (title, description, status, due_date, priority,
  source_item_id)
- `decisions` — a log of decisions made, with context and rationale
  (title, context, decision, rationale, created_at)
- `notes` — freeform knowledge base entries (title, body, tags, created_at)
- `briefings` — generated daily/periodic briefing snapshots (date, content,
  generated_by = "gemini", approved_by_user boolean)
- `settings` — key/value app configuration (never API keys — see AGENTS.md §5)

All AI-generated content that gets persisted (briefings, drafts, suggested
priorities) is stored with provenance (`generated_by`) and an explicit
approval flag so the system can always distinguish human-authored from
AI-suggested content.

## 5. Gemini Integration Principles

- Every Gemini call is triggered by an explicit user action (e.g. "Generate
  briefing", "Summarize this item", "Draft a reply") — never a hidden
  background job.
- Gemini calls are read-only with respect to the database: the model never
  writes to SQLite directly. Its output is staged and requires user approval
  before being persisted as a task, decision, or note.
- Prompts are built from the user's own local data only. No data is sent to
  any third party other than the Gemini API itself.
- API keys are read from environment variables / a local `.env` file, never
  hardcoded, never committed (see AGENTS.md §5).

## 6. UI Structure (Streamlit pages)

1. **Dashboard** — at-a-glance view of open tasks, recent decisions, today's
   briefing status.
2. **Inbox / Triage** — raw items awaiting classification into tasks, notes,
   or decisions, optionally with Gemini-assisted triage suggestions.
3. **Tasks** — task list with status, priority, due dates.
4. **Decisions** — a running decision log (what was decided, why, when).
5. **Knowledge Base** — searchable notes.
6. **Daily Briefing** — Gemini-generated summary of the day's priorities,
   pending decisions, and overdue items, pending user approval.
7. **Settings** — local configuration (Gemini API key entry, model
   parameters, data export/backup).

## 7. Security & Privacy

- All persistent data stays local (SQLite file on the user's machine).
- No telemetry, no analytics, no third-party sync services.
- The only outbound network calls are to the Gemini API, and only when the
  user explicitly triggers a reasoning action.
- Secrets (Gemini API key) are never committed to the repository; `.env` is
  gitignored and `.env.example` documents required variables without values.

## 8. Non-Goals (for this level)

- No multi-user support / auth system (single local user).
- No autonomous execution of external actions (sending emails, making
  purchases, etc.) — see Level 3 note in §1.
- No cloud database or hosted deployment as a default configuration.
- No background schedulers/daemons beyond what the user explicitly runs.

## 9. Amendments

This blueprint is the architectural contract for the project. Changes to the
stack, storage model, or the Level 2 boundary must go through the amendment
process defined in `AGENTS.md`.
