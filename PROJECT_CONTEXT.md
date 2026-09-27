# Project Context — Multi-LLM Autonomous Research Agent

> Recovery document for continuing this project in a new chat. Read this file before making
> changes. Keep it updated after every material project change.

**Last updated:** 2026-09-27  
**Workspace:** repository root  
**Current verified state:** Python compilation passes, 28 automated tests pass, and the
Streamlit UI smoke test passes.

## 1. Project goal

Build an internship-assessment-quality autonomous research assistant that:

- accepts ordinary chat messages and research questions;
- decides whether web research is actually required;
- autonomously plans appropriate source types and search queries;
- gathers multiple evidence streams in parallel;
- extracts, filters, and deduplicates relevant information;
- produces a structured report with key points, findings, actionable insights, limitations,
  and clickable references;
- exports research reports as Markdown and PDF;
- supports multiple LLM providers;
- persists chat threads, current-thread context, research history, and selected durable user
  facts in local SQLite storage.

## 2. Current user experience

The application is a Streamlit chatbot resembling ChatGPT/Gemini:

- The sidebar has **New chat**, saved thread buttons, and **Delete current chat**.
- Complete user/assistant message history is rendered with `st.chat_message`.
- Input uses `st.chat_input`.
- Model and search settings are permanently visible in the sidebar; they are not inside a
  collapsible expander.
- The sidebar has an optional **Use TypeSafe Jev** toggle and session API-key input. Missing
  credentials do not block the app; the existing LLM router remains active.
- There is intentionally no visible **Long-term memory** section.
- Long-term memory still operates silently in the background.
- Research answers include an expandable research-details area showing every task's chosen
  backend, preferred domains, source types, and rationale, plus Markdown/PDF downloads.
- Every assistant answer shows the detected intent, provider/model, web-search state, and
  whether routing used Jev, the LLM router, or the automatic LLM fallback.

## 3. Memory model

The project has three distinct persistence layers:

1. **Thread history** — all messages in the active conversation are stored in SQLite and
   replayed to the selected LLM on subsequent turns. Different threads have separate message
   transcripts.
2. **Long-term user facts** — a small curated set of durable facts is shared across threads.
   Examples include `preferred_name`, occupation, stable preferences, and ongoing goals.
   Explicit name statements such as “My name is Vishv” and “Call me Vishv” are captured
   deterministically; the LLM router may extract other explicitly stated durable facts.
3. **Research memory** — completed research plans, reports, sources, model metadata, and
   durations are stored in the legacy `searches` table.

Long-term memory safety rules:

- Only explicitly stated facts should be saved; do not infer user facts.
- Passwords, API keys, access tokens, payment secrets, and similar credentials are rejected.
- Long-term facts are supplied to the intent router, research planner, and report synthesizer.
- A one-time `memory_backfill_v1` migration extracts explicit names from existing user
  messages.
- The UI for inspecting/clearing facts was removed at the user's request. Storage methods
  (`long_term_facts`, `forget_fact`, and `clear_long_term_memory`) remain available.

## 4. Intent and research flow

For every new message:

```text
User message
    │
    ├─ Load current thread history
    ├─ Load cross-thread durable facts
    ▼
Optional TypeSafe Jev router
    ├─ successful typed decision ─► selected intent + confidence
    └─ disabled/missing key/error ─► existing LLM intent router

Selected intent
    ├─ casual_chat ───────────────► direct conversational response
    ├─ simple_question ───────────► direct answer
    ├─ clarification_required ────► one clarifying question
    ├─ current_information ───────► autonomous research workflow
    └─ research_request ──────────► autonomous research workflow

Research workflow:
LLM plan with per-task backend/domain selection → 3–5 parallel searches → page extraction → source deduplication
→ LLM synthesis → cited report → SQLite + chat message → Markdown/PDF export
```

The five allowed intent values are defined by the router prompt in
`research_agent/agent.py`. Only `current_information` and `research_request` trigger web
search. When Jev selects a research intent, the agent skips the generative LLM classification
call and starts planning. For conversational or clarification routes, the selected LLM still
writes the response and extracts explicit durable-memory updates. Any Jev exception or invalid
response is caught and routed through the original LLM classifier.

## 5. LLM providers

All providers use an OpenAI-compatible Chat Completions adapter in
`research_agent/providers.py`.

| Provider key | Display name | Default model | API key variable | Base URL |
|---|---|---|---|---|
| `openai` | OpenAI / ChatGPT | `gpt-5.5` | `OPENAI_API_KEY` | SDK default |
| `deepseek` | DeepSeek | `deepseek-flash` | `DEEPSEEK_API_KEY` | `https://api.deepseek.com` |
| `gemini` | Google Gemini | `gemini-3.8-flash` | `GEMINI_API_KEY` | Google OpenAI-compatible URL |
| `groq` | Groq | `openai/gpt-oss-20b` | `GROQ_API_KEY` | Groq OpenAI-compatible URL |
| `custom` | Custom OpenAI-compatible API | user supplied | `CUSTOM_LLM_API_KEY` | user supplied |

`OpenAICompatibleClient.chat()` accepts prior user/assistant messages plus a system prompt.
`generate()` is a one-message convenience wrapper.

Model IDs are editable because provider model availability can change. Verify current model
IDs against provider documentation before changing defaults.

## 6. Optional TypeSafe Jev routing

`research_agent/jev.py` integrates TypeSafe Jev as a specialized decision layer, not as a
generative LLM provider.

- Official endpoint: `POST https://api.typesafe.ai/v1/systemone`.
- Default model alias: `jev-latest`.
- Input includes the newest query plus bounded recent-conversation and durable-fact context.
- A typed `choice` question maps the request to the same five intents used by the LLM router.
- Valid responses store the selected intent and confidence in assistant message metadata.
- Decisions below `JEV_MIN_CONFIDENCE` (default `0.60`) fall back to the LLM router while
  retaining the observed confidence in message metadata.
- Research/current-information routes proceed without a separate LLM classification call.
- Direct-answer and clarification routes retain Jev's intent while the selected LLM writes
  the user-facing response and extracts memory updates.
- Disabled Jev, a missing key, HTTP errors, timeouts, malformed data, or unsupported choices
  automatically fall back to the existing LLM intent router.
- Jev is enabled with `JEV_ENABLED=true` or the Streamlit toggle. It is never required for
  the core application to work.

## 7. Web search and evidence

The LLM provider is intentionally separated from the search provider so every model vendor
gets the same research capability.

- `SEARCH_BACKEND=auto`: expose all configured backends to the LLM planner, which chooses
  the most appropriate backend independently for each research task. The deterministic
  fallback order is Tavily, SerpAPI, then DuckDuckGo.
- `duckduckgo`: key-free search using `ddgs` plus readable HTML extraction.
- `tavily`: Tavily advanced search with raw content when available.
- `serpapi`: structured Google organic results through SerpAPI followed by readable-page
  extraction.
- Every planned task records preferred source types, authoritative domains, and its chosen
  backend. Domain preferences are enforced with `site:` query constraints for DuckDuckGo
  and SerpAPI and Tavily's native `include_domains` option.
- Selecting a specific backend in the UI is an explicit user override; autonomous per-task
  backend selection operates when the backend is `auto`.
- Invalid or unavailable LLM backend choices are sanitized to the best configured fallback.
- Each search task returns at most four sources.
- Up to `MAX_PARALLEL_SEARCHES` tasks run through `ThreadPoolExecutor`.
- HTML extraction removes scripts, styles, navigation, footers, forms, and `noscript`.
- Page requests reject obvious local/private literal URLs and validate redirects.
- Retrieved content is treated as untrusted evidence. The synthesis prompt explicitly says
  never to follow instructions found inside sources.
- Source deduplication canonicalizes URLs, removes common tracking parameters, and collapses
  highly similar titles.

## 8. SQLite schema

Default database: `data/research_history.db` (ignored by Git).

Tables:

- `conversations`: thread ID, title, provider, model, created/updated timestamps.
- `messages`: ordered user/assistant/system messages, JSON metadata, thread foreign key with
  cascade deletion.
- `memory_facts`: cross-thread key/value facts with optional source-conversation reference.
- `searches`: completed research query, model metadata, plan JSON, report Markdown, sources,
  and duration.
- `app_metadata`: one-time migration markers such as `memory_backfill_v1`.

SQLite foreign keys are enabled for every connection. Thread IDs are UUIDs. A first user
message automatically generates a short thread title.

## 9. Project structure

```text
app.py                         Streamlit chat UI and thread orchestration
research_agent/
  __init__.py                 Public package exports
  agent.py                    Jev/LLM routing, context, planning, research, synthesis
  jev.py                      Optional TypeSafe typed intent-decision adapter
  providers.py                Multi-provider OpenAI-compatible LLM adapter
  search.py                   DuckDuckGo/Tavily search and webpage extraction
  memory.py                   SQLite threads, messages, facts, and research history
  models.py                   Dataclasses including per-task source/domain/backend choices
  deduplication.py            URL canonicalization and title-based source deduplication
  exporters.py                Markdown bytes and ReportLab PDF rendering
tests/
  test_agent_helpers.py       Routing, parallelism, autonomous sources, recall, provider tests
  test_jev.py                 Jev request parsing, research routing, and fallback tests
  test_memory.py              Research history, threads, facts, deletion, clearing persistence
  test_deduplication.py       URL and source deduplication
  test_exporters.py           Markdown and PDF exports
  test_search.py              SerpAPI parsing, auto-backend priority, and key validation
README.md                     User-facing setup and architecture documentation
.env.example                  Configuration variable template without secrets
requirements.txt              Python dependencies
AGENTS.md                     Requires this context document to stay synchronized
PROJECT_CONTEXT.md            This recovery document
```

## 10. Configuration

`.env.example` defines all supported variables:

```dotenv
OPENAI_API_KEY=
DEEPSEEK_API_KEY=
GEMINI_API_KEY=
GROQ_API_KEY=
CUSTOM_LLM_API_KEY=
CUSTOM_LLM_BASE_URL=
JEV_ENABLED=false
JEV_API_KEY=
JEV_MODEL=jev-latest
JEV_BASE_URL=https://api.typesafe.ai
JEV_MIN_CONFIDENCE=0.60
TAVILY_API_KEY=
SERPAPI_API_KEY=
LLM_PROVIDER=openai
RESEARCH_MODEL=
SEARCH_BACKEND=auto
MAX_PARALLEL_SEARCHES=4
RESEARCH_DB_PATH=data/research_history.db
```

Never copy values from the real `.env` into documentation, test output, commits, or chat.

## 11. Setup and commands

PowerShell setup:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Run the application:

```powershell
.venv\Scripts\python.exe -m streamlit run app.py
```

Run verification:

```powershell
.venv\Scripts\python.exe -m compileall -q app.py research_agent tests
.venv\Scripts\python.exe -m pytest -q
```

Current expected result: `28 passed`.

## 12. Important design decisions

- Local history replay is used instead of provider-specific conversation IDs so memory works
  consistently with OpenAI, DeepSeek, Gemini, Groq, and custom compatible services.
- Jev is modeled as an optional decision router rather than a sixth chat provider because it
  returns typed decisions, not long-form text. This preserves clean provider responsibilities.
- The Jev integration is fail-open to the pre-existing LLM router so missing credentials or
  an external outage cannot disable the agent.
- Web research is decoupled from built-in vendor tools because provider capabilities differ.
- In automatic search mode, the LLM makes per-task backend and authoritative-domain choices;
  those choices are validated against configured providers and enforced during search.
- Ordinary chat does not perform web search, reducing cost and latency.
- Full chat transcripts are visible and persistent; recent messages are trimmed only when the
  provider-neutral context budget would exceed roughly 60,000 characters.
- Long-term memory is deliberately small and fact-oriented rather than copying entire chats
  across threads.
- API calls are excluded from automated tests to avoid spending credits.
- The public README is product-focused and avoids internship-rubric or assessment-checklist
  language; capabilities are demonstrated through feature summaries and workflow diagrams.
- The user's real `.env` exists locally and must be preserved; never display or overwrite it.

## 13. Current verification coverage

The 28-test suite currently verifies:

- research planning and mocked end-to-end synthesis;
- correct TypeSafe `/v1/systemone` typed-choice request construction and response parsing;
- a Jev research decision bypassing the generative LLM intent-classification call;
- automatic fallback to the LLM router when Jev fails;
- fallback remaining operational when Jev is enabled without an API key;
- low-confidence Jev decisions falling back to the LLM router;
- actual use of multiple worker threads;
- execution of an LLM-selected search backend with its selected authoritative domains;
- intent routing that skips search for greetings;
- research intent running the full workflow;
- same-thread follow-up recall;
- cross-thread preferred-name recall through long-term memory;
- conversation/message persistence after reopening the database;
- cascade deletion of a thread's messages;
- explicit-name extraction;
- cleared long-term memory remaining cleared after restart;
- provider defaults and custom-provider validation;
- clickable source-ID replacement;
- URL canonicalization and duplicate removal;
- SerpAPI result parsing, automatic search-backend priority, domain query constraints, and
  required-key validation;
- Markdown and PDF export generation.

A Streamlit `AppTest` smoke check has also verified that the app renders without exceptions,
contains one chat input, has no visible Long-term memory expander, and has no collapsible
Model and search settings expander.

## 14. Known limitations and next sensible improvements

- Durable fact extraction beyond explicit names relies on the selected LLM returning valid
  `memory_updates` JSON.
- Long conversations are character-trimmed rather than token-counted or summarized.
- DuckDuckGo/page extraction quality varies across sites; Tavily and SerpAPI are more
  consistent but need separate API keys.
- The SQLite database is local and single-user; authentication and cloud synchronization are
  outside the current assessment scope.
- There is no streaming-token UI yet; responses appear after completion.
- Thread titles are derived from the first user message rather than generated semantically.
- Jev is an optional external early-access service; automated tests mock its API, so a valid
  account/key is required for a live integration demonstration.

## 15. Maintenance checklist

After every material change:

1. Update the relevant sections of this file.
2. Update **Last updated** and **Current verified state**.
3. Update the project structure, schema, configuration, behavior, limitations, and design
   decisions when affected.
4. Run compilation and tests.
5. Record the new test count or any verification failure here.
6. Never include secrets or the contents of the real `.env`.
