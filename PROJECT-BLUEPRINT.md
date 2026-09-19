# Project Blueprint: Executive OS

## 1. Project Identity (The “What & Why”)
- **Project Name**: Executive OS (Autonomous Mid-Market Operating Engine)
- **One-sentence purpose**: A conversational AI operating system that interviews a CEO to build their accountability chart, 5 core responsibilities, and KPIs from first principles, then tracks execution.
- **Who is this for**: CEOs, COOs, and fractional operators managing mid-market professional services firms (law, accounting, engineering).
- **Main problem it removes**: Eliminates messy manual setup and data silos, replacing accidental management with an automated operational rhythm.
- **Success looks like**: I can open the app, run a 7-step onboarding chat with Gemini to set up a company's structure, view the generated Accountability Chart and Scorecard, and test live operational tracking—all under 5 minutes.

## 2. Core Features (The “What the User Can Do”)
| # | Feature Name | What the user can do (in plain English) | Must have for launch? |
|---|--------------|--------------------------------ov-----------------------|-----------------------|
| 1 | Conversational Onboarding Engine | Chat with a Gemini-powered agent through the 7-step sequence (Problem, Solution, Revenue, Seats, 5 Responsibilities, KPIs). | Yes |
| 2 | Accountability & Scorecard Visualizer | View the dynamically generated organizational accountability chart and weekly KPI scorecard based on the onboarding chat. | Yes |
| 3 | Operational "IDS" Triage & Weekly Review | Input weekly scorecard metrics and qualitative roadblocks to let Gemini cluster bottlenecks and output an executive briefing packet. | Yes |
| 4 | Action Item & Loop Tracker | Log commitments extracted from weekly reviews with a hard 7-day tracking clock. | Yes |

## 3. User Journey (The Happy Path)
1. User opens the app and lands on a clean executive command dashboard.
2. User clicks "Initialize Company" to start the conversational onboarding Q&A.
3. User types answers to Gemini regarding the company's problem, revenue model, and core seats.
4. User sees the app instantly compile and render the Accountability Chart and KPI Scorecard.
5. User can then navigate to the Weekly Review tab to input updates and view AI-synthesized operational bottlenecks.

## 4. Data the App Must Remember (SQLite Schema)
- **Companies**: id, name, problem_statement, solution, revenue_model, created_at
- **Seats**: id, company_id, seat_name, description
- **Responsibilities**: id, seat_id, description_1 to 5
- **KPIs**: id, seat_id, kpi_name, target_metric
- **Scorecards**: id, kpi_id, week_date, actual_value, status (Green/Red)
- **ActionItems**: id, company_id, owner_seat_id, task_description, due_date, status (Open/Closed)

*Login required?* No (Local single-tenant instance for interviews and fractional client deployment).

## 5. Screens / Pages the App Needs (Streamlit Tabs)
1. **Executive Dashboard**: High-level ecosystem health view, red metrics counter, and quick status summaries.
2. **Setup & Onboarding Chat**: Conversational interface powering the 7-step structural interview.
3. **Accountability & Scorecard**: Visual grid showing seats, 5 responsibilities, and weekly KPIs.
4. **Weekly Review & IDS**: AI synthesis tool that parses friction points and generates executive action briefs.

## 6. Look & Feel (Simple Design Rules)
- **Overall style**: Clean, professional, executive-grade dark/light minimal layout.
- **Main colors**: Slate gray, executive navy, crisp white, subtle status indicators (emerald green / alert red).
- **Must work on**: Desktop and Tablet (optimized for executive walkthroughs).
- **Branding**: None (clean custom utility).
- **Things to avoid**: Cluttered dashboards, overly playful widgets, bright neon colors.

## 7. Technical Decisions
- **Frontend & Backend**: Python + Streamlit (unified full-stack framework).
- **Database**: SQLite (via Python built-in `sqlite3` library, zero configuration).
- **AI Engine**: Google GenAI SDK (`google-genai`) using Gemini models.
- **Hosting**: Streamlit Community Cloud (Free public/private URL hosting via GitHub sync).
- **Authentication**: None needed for local execution / portfolio demos.

## 8. What Must Never Change (Invariants)
- Never delete or overwrite existing SQLite database tables without an explicit backup.
- Never store API keys in code; always fetch via `os.environ["GEMINI_API_KEY"]` or Streamlit secrets.
- Never crash the run if an LLM call fails; always catch API exceptions and show a clean error message.
- Only create or edit files needed for the active feature.

## 9. Acceptance Criteria (Feature 1: Conversational Onboarding)
It is finished when:
1. I can open the app, type my company's details into the onboarding chat, and see Gemini successfully parse and save the structure into SQLite.
2. If the API key is missing or invalid, the user sees a clear error message in the UI sidebar.
3. The layout renders cleanly without breaking on desktop browsers.
4. All database writes persist correctly across page refreshes.

## 10. Environment & Deployment Basics
- **Public access**: Yes, via a secure Streamlit Community Cloud link for interviews.
- **Secrets needed**: `GEMINI_API_KEY` stored in Streamlit Cloud secrets management or local `.env`.
