from __future__ import annotations

import os
import re
from typing import Any

import streamlit as st
from dotenv import load_dotenv

from research_agent import PROVIDERS, ResearchAgent, ResearchMemory
from research_agent.exporters import markdown_bytes, pdf_bytes


load_dotenv()
st.set_page_config(
    page_title="Multi-LLM Research Chat",
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_resource
def get_memory() -> ResearchMemory:
    return ResearchMemory(os.getenv("RESEARCH_DB_PATH", "data/research_history.db"))


def filename_for(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]
    return slug or "research-report"


def conversation_title(message: str) -> str:
    compact = " ".join(message.split())
    words = compact.split()[:8]
    title = " ".join(words)
    if len(title) > 52:
        title = title[:49].rstrip() + "…"
    elif len(words) < len(compact.split()):
        title += "…"
    return title or "New chat"


def message_metadata(outcome: Any, agent: ResearchAgent) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "intent": outcome.decision.intent,
        "reasoning": outcome.decision.reasoning,
        "provider": agent.provider,
        "model": agent.model,
        "web_search": outcome.report is not None,
    }
    if outcome.report:
        planned_backends = [
            task.search_backend
            for task in outcome.report.plan.tasks
            if task.search_backend and task.search_backend != "auto"
        ]
        metadata.update(
            {
                "report_id": outcome.report.memory_id,
                "duration_seconds": outcome.report.duration_seconds,
                "search_backend": ", ".join(dict.fromkeys(planned_backends))
                or agent.search.name,
                "sources": [source.to_dict() for source in outcome.report.sources],
                "plan": outcome.report.plan.to_dict(),
            }
        )
    return metadata


def render_assistant_metadata(message: dict[str, Any]) -> None:
    metadata = message.get("metadata", {})
    if not metadata:
        return
    if metadata.get("web_search"):
        with st.expander("Research details"):
            plan = metadata.get("plan", {})
            if plan.get("reasoning"):
                st.write(plan["reasoning"])
            for index, task in enumerate(plan.get("tasks", []), start=1):
                st.markdown(f'**{index}. {task.get("query", "Research task")}**')
                if task.get("rationale"):
                    st.caption(task["rationale"])
                strategy = []
                if task.get("search_backend"):
                    strategy.append(f'Backend: {task["search_backend"]}')
                if task.get("preferred_domains"):
                    strategy.append(
                        "Domains: " + ", ".join(task["preferred_domains"])
                    )
                if task.get("preferred_sources"):
                    strategy.append(
                        "Source types: " + ", ".join(task["preferred_sources"])
                    )
                if strategy:
                    st.caption(" • ".join(strategy))
            st.caption(
                f'{len(metadata.get("sources", []))} unique sources • '
                f'{metadata.get("duration_seconds", 0):.1f} seconds • '
                f'{metadata.get("search_backend", "Web search")}'
            )
        base_name = filename_for(message["content"].splitlines()[0])
        left, right = st.columns(2)
        with left:
            st.download_button(
                "Download Markdown",
                data=markdown_bytes(message["content"]),
                file_name=f"{base_name}.md",
                mime="text/markdown",
                key=f'md_{message["id"]}',
                use_container_width=True,
            )
        with right:
            st.download_button(
                "Download PDF",
                data=pdf_bytes(message["content"], base_name),
                file_name=f"{base_name}.pdf",
                mime="application/pdf",
                key=f'pdf_{message["id"]}',
                use_container_width=True,
            )
    details = [
        str(metadata.get("intent", "response")).replace("_", " "),
        f'{metadata.get("provider", "LLM")} / {metadata.get("model", "")}'.strip(" /"),
    ]
    details.append("web research" if metadata.get("web_search") else "no web search")
    st.caption(" • ".join(details))


memory = get_memory()
conversations = memory.list_conversations()
active_id = st.session_state.get("active_conversation_id")
if not active_id or memory.get_conversation(active_id) is None:
    active_id = conversations[0]["id"] if conversations else memory.create_conversation()
    st.session_state["active_conversation_id"] = active_id

with st.sidebar:
    st.title("Chats")
    if st.button("＋ New chat", type="primary", use_container_width=True):
        new_id = memory.create_conversation()
        st.session_state["active_conversation_id"] = new_id
        st.rerun()

    conversations = memory.list_conversations()
    for conversation in conversations:
        is_active = conversation["id"] == active_id
        if st.button(
            conversation["title"],
            key=f'thread_{conversation["id"]}',
            type="primary" if is_active else "secondary",
            use_container_width=True,
            help=f'{conversation["message_count"]} messages • {conversation["updated_at"]}',
        ):
            st.session_state["active_conversation_id"] = conversation["id"]
            st.rerun()

    if st.button("Delete current chat", use_container_width=True):
        memory.delete_conversation(active_id)
        remaining = memory.list_conversations()
        st.session_state["active_conversation_id"] = (
            remaining[0]["id"] if remaining else memory.create_conversation()
        )
        st.rerun()

    st.divider()
    st.subheader("Model and search settings")
    provider_keys = list(PROVIDERS)
    configured_default = os.getenv("LLM_PROVIDER", "openai").lower()
    default_index = (
        provider_keys.index(configured_default)
        if configured_default in provider_keys
        else 0
    )
    provider_key = st.selectbox(
        "LLM provider",
        provider_keys,
        index=default_index,
        format_func=lambda key: PROVIDERS[key].display_name,
    )
    provider_config = PROVIDERS[provider_key]
    model = st.text_input(
        "Model ID",
        value=os.getenv("RESEARCH_MODEL") or provider_config.default_model,
        key=f"model_{provider_key}",
    )
    environment_key = os.getenv(provider_config.api_key_env, "")
    api_key = environment_key or st.text_input(
        f"{provider_config.display_name} API key",
        type="password",
        help=f"Or set {provider_config.api_key_env} in .env",
        key=f"api_key_{provider_key}",
    )
    if environment_key:
        st.success(f"Using {provider_config.api_key_env} from the environment.")

    custom_base_url = None
    if provider_key == "custom":
        custom_base_url = st.text_input(
            "OpenAI-compatible base URL",
            value=os.getenv("CUSTOM_LLM_BASE_URL", ""),
            placeholder="https://provider.example/v1",
        )

    backends = ["auto", "duckduckgo", "tavily", "serpapi"]
    configured_backend = os.getenv("SEARCH_BACKEND", "auto").lower()
    search_backend = st.selectbox(
        "Web search backend",
        backends,
        index=backends.index(configured_backend)
        if configured_backend in backends
        else 0,
        help=(
            "Auto lets the LLM choose the best available backend for each research task. "
            "Without paid search keys, it uses key-free DuckDuckGo."
        ),
    )
    tavily_environment_key = os.getenv("TAVILY_API_KEY", "")
    tavily_key = tavily_environment_key
    if search_backend == "tavily" and not tavily_environment_key:
        tavily_key = st.text_input("Tavily API key", type="password")
    serpapi_environment_key = os.getenv("SERPAPI_API_KEY", "")
    serpapi_key = serpapi_environment_key
    if search_backend == "serpapi" and not serpapi_environment_key:
        serpapi_key = st.text_input("SerpAPI API key", type="password")

    st.caption("Threads and messages are saved locally in SQLite.")

active_conversation = memory.get_conversation(active_id)
st.title("🔎 Multi-LLM Autonomous Research Agent")
st.caption(
    "Chat normally or ask for current, multi-source research. This thread remembers your "
    "earlier messages and remains available after the app restarts."
)
if active_conversation and active_conversation["title"] != "New chat":
    st.subheader(active_conversation["title"])

thread_messages = memory.messages(active_id)
if not thread_messages:
    st.info(
        "Start a conversation. I can remember details within this thread, answer normal "
        "questions, or run parallel web research when current evidence is needed."
    )

for message in thread_messages:
    avatar = "🔎" if message["role"] == "assistant" else None
    with st.chat_message(message["role"], avatar=avatar):
        st.markdown(message["content"])
        if message["role"] == "assistant":
            render_assistant_metadata(message)

user_message = st.chat_input("Message the research agent…")
if user_message:
    validation_error = None
    if not api_key:
        validation_error = (
            f"Enter an API key in Model and search settings, or set "
            f"{provider_config.api_key_env} in .env."
        )
    elif not model.strip():
        validation_error = "Enter a model ID."
    elif provider_key == "custom" and not custom_base_url:
        validation_error = "Enter the base URL for the custom OpenAI-compatible API."
    elif search_backend == "tavily" and not tavily_key:
        validation_error = "Enter a Tavily API key or choose DuckDuckGo."
    elif search_backend == "serpapi" and not serpapi_key:
        validation_error = "Enter a SerpAPI API key or choose another search backend."

    if validation_error:
        st.error(validation_error)
    else:
        prior_messages = memory.messages(active_id)
        memory.add_message(active_id, "user", user_message)
        if active_conversation and active_conversation["title"] == "New chat":
            memory.update_conversation(active_id, title=conversation_title(user_message))

        with st.status("Thinking…", expanded=True) as status:
            try:
                agent = ResearchAgent(
                    provider=provider_key,
                    api_key=api_key,
                    model=model.strip(),
                    custom_base_url=custom_base_url,
                    search_backend=search_backend,
                    tavily_api_key=tavily_key,
                    serpapi_api_key=serpapi_key,
                    memory=memory,
                )

                def update_status(message: str) -> None:
                    status.write(message)

                outcome = agent.run(
                    user_message,
                    progress=update_status,
                    history=prior_messages,
                    conversation_id=active_id,
                )
                memory.add_message(
                    active_id,
                    "assistant",
                    outcome.message,
                    message_metadata(outcome, agent),
                )
                memory.update_conversation(
                    active_id, provider=agent.provider, model=agent.model
                )
                status.update(label="Response ready", state="complete", expanded=False)
            except Exception as exc:
                error_message = f"I couldn't complete that request: {exc}"
                memory.add_message(
                    active_id,
                    "assistant",
                    error_message,
                    {"intent": "error", "provider": provider_config.display_name, "model": model},
                )
                status.update(label="Request failed", state="error", expanded=True)
        st.rerun()
