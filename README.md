# Multi-LLM Autonomous Research Agent

An internship-assessment project that accepts a topic, autonomously chooses suitable
external sources, researches several angles in parallel, removes duplicate evidence, and
returns a structured report with clickable citations and actionable insights.

The reasoning model and search engine are independent. You can switch LLM providers
without rewriting the research workflow.

## Supported LLM providers

| Provider | Default model | API key variable |
|---|---|---|
| OpenAI / ChatGPT | `gpt-5.5` | `OPENAI_API_KEY` |
| DeepSeek | `deepseek-flash` | `DEEPSEEK_API_KEY` |
| Google Gemini | `gemini-3.8-flash` | `GEMINI_API_KEY` |
| Groq | `openai/gpt-oss-20b` | `GROQ_API_KEY` |
| Any OpenAI-compatible API | User supplied | `CUSTOM_LLM_API_KEY` |

Model IDs can be changed directly in the interface, which is useful when providers add or
retire models. Provider URLs and defaults live in `research_agent/providers.py`.

## Features

- **Intent-first routing:** every message is understood before action. Greetings and simple
  questions receive direct answers, ambiguous requests receive a clarification question,
  and only current-information or research requests trigger web searches.
- **Persistent chat threads:** create, switch, and delete ChatGPT-style conversations. Every
  user and assistant message is stored in SQLite and restored after an app restart.
- **Conversation-aware replies:** the current thread transcript is sent with each new turn,
  so follow-ups, names, preferences, pronouns, and references to earlier messages work.
- **Long-term user memory:** durable facts explicitly provided by the user—such as a
  preferred name, occupation, preferences, or ongoing goals—are available across separate
  chat threads. Secrets such as passwords and API keys are rejected.
- **Multi-provider LLM layer:** one adapter supports OpenAI, DeepSeek, Gemini, Groq, and
  custom OpenAI-compatible endpoints.
- **Provider-independent web research:** choose key-free DuckDuckGo, Tavily, or SerpAPI.
  The same workflow works even when an LLM vendor has no built-in search tool.
- **Autonomous source planning and execution:** the selected LLM classifies the topic and
  chooses search angles, source types, authoritative domains, and the most appropriate
  available search backend for each task. Domain choices are enforced during retrieval,
  and each choice is visible in the report's Research details panel.
- **Parallel gathering:** independent searches run concurrently with a configurable worker
  limit.
- **Evidence extraction:** the agent retrieves search snippets and readable webpage text.
- **Evidence safety:** retrieved pages are treated as untrusted data, and the synthesis
  prompt explicitly rejects instructions embedded in sources.
- **Deduplication:** tracking parameters are stripped and duplicate URL/title variants are
  collapsed before synthesis.
- **Structured output:** reports contain an executive summary, key points, findings,
  actionable insights, limitations, and references.
- **Exports:** download reports as Markdown or PDF.
- **Memory:** chat threads, messages, completed searches, plans, reports, model metadata,
  and sources are stored in local SQLite.

## Architecture

```text
                         ┌─ OpenAI
                         ├─ DeepSeek
Chat thread ─► LLM adapter├─ Gemini   ─► intent router
                         ├─ Groq           ├─ casual/simple/unclear ─► direct response
                         └─ Custom         │
                                          └─ current/research
                                                   │
                                                   ▼
                                      autonomous search plan
                                                   │
                              ┌────────────────────┼────────────────────┐
                              ▼                    ▼                    ▼
                         web search           web search           web search
                         + extraction         + extraction         + extraction
                              └────────────────────┼────────────────────┘
                                                   ▼
                                      deduplicate evidence/sources
                                                   │
                                                   ▼
                                      selected LLM synthesizes report
                                                   │
                                  ┌────────────────┴────────────────┐
                                  ▼                                 ▼
                    SQLite threads + messages                Markdown / PDF
```

## Setup

Requires Python 3.11 or newer.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Add at least one LLM provider key to `.env`. For example, to use Gemini:

```dotenv
GEMINI_API_KEY=your_key_here
LLM_PROVIDER=gemini
```

Then run:

```powershell
streamlit run app.py
```

Open `http://localhost:8501`. You can also paste an API key into the sidebar for the
current session instead of saving it in `.env`.

Use **New chat** to create an independent conversation. Choose any earlier thread in the
sidebar to reopen its complete transcript. Messages remain isolated per thread, while the
small set of durable user facts is intentionally shared across threads in the background.
This mirrors the distinction between conversational context and user memory.

## Search configuration

`SEARCH_BACKEND=auto` exposes every configured search backend to the LLM planner. The LLM
then chooses the most appropriate available backend separately for each parallel research
task. Tavily is suited to deep content extraction, SerpAPI to broad Google/current coverage,
and DuckDuckGo to general key-free discovery. If the planner returns an unavailable backend,
the application safely falls back to the best configured provider. Selecting a specific
backend in the sidebar overrides autonomous backend selection.

The planner also selects authoritative domains where appropriate. DuckDuckGo and SerpAPI
receive `site:` constraints, while Tavily receives native `include_domains` filters.

```dotenv
SEARCH_BACKEND=auto
TAVILY_API_KEY=
SERPAPI_API_KEY=
MAX_PARALLEL_SEARCHES=4
```

Tavily is useful for extracted research content, SerpAPI provides structured Google organic
results, and DuckDuckGo keeps the project easy to evaluate without another paid account.

## Custom provider

Any service exposing an OpenAI-compatible Chat Completions endpoint can be used:

```dotenv
LLM_PROVIDER=custom
CUSTOM_LLM_API_KEY=your_key
CUSTOM_LLM_BASE_URL=https://provider.example/v1
RESEARCH_MODEL=provider-model-id
```

The same values can be entered in the sidebar.

## Run tests

```powershell
pytest -q
```

Tests cover provider configuration, same-thread recall, cross-thread long-term recall,
persistent threads, memory clearing, cascade deletion, an end-to-end mocked multi-provider
research run, actual parallel task execution, source deduplication, and both export formats.
External API calls are mocked so tests do not spend credits.

## Assessment requirement mapping

| Requirement | Implementation |
|---|---|
| Accept a query/topic | Streamlit chat input |
| Understand before acting | Five-way intent router before the research planner |
| Current thread history | SQLite conversations/messages plus full chat rendering |
| Conversation awareness | Earlier active-thread messages replayed on each LLM request |
| Long-term memory | Curated SQLite facts shared across threads with user controls |
| Search external sources | DuckDuckGo, Tavily, or SerpAPI adapter |
| Extract relevant information | Search snippets plus webpage text extraction |
| Remove duplicate/irrelevant content | URL normalization, title similarity, synthesis filter |
| Structured summary | Six fixed report sections with linked citations |
| Autonomous source selection | LLM selects source types, authoritative domains, and an available backend per task; retrieval enforces those choices |
| Parallel gathering | `ThreadPoolExecutor` with configurable concurrency |
| Multiple LLMs | OpenAI-compatible provider adapter and UI selector |
| PDF or Markdown export | ReportLab PDF and UTF-8 Markdown downloads |
| Store previous searches | Research reports stored with their assistant chat messages |

## Provider documentation

- [OpenAI web search](https://developers.openai.com/api/docs/guides/tools-web-search)
- [OpenAI conversation state](https://developers.openai.com/api/docs/guides/conversation-state)
- [Google Gemini OpenAI compatibility](https://ai.google.dev/gemini-api/docs/openai)
- [DeepSeek Responses API compatibility](https://api-docs.deepseek.com/guides/responses_api/)
- [Groq OpenAI compatibility](https://console.groq.com/docs/openai)
- [SerpAPI Google Search API](https://serpapi.com/search-api)
