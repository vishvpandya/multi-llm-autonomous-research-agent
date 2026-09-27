from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from openai import OpenAI


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    key: str
    display_name: str
    api_key_env: str
    default_model: str
    base_url: str | None = None


PROVIDERS: dict[str, ProviderConfig] = {
    "openai": ProviderConfig(
        key="openai",
        display_name="OpenAI / ChatGPT",
        api_key_env="OPENAI_API_KEY",
        default_model="gpt-5.5",
    ),
    "deepseek": ProviderConfig(
        key="deepseek",
        display_name="DeepSeek",
        api_key_env="DEEPSEEK_API_KEY",
        default_model="deepseek-flash",
        base_url="https://api.deepseek.com",
    ),
    "gemini": ProviderConfig(
        key="gemini",
        display_name="Google Gemini",
        api_key_env="GEMINI_API_KEY",
        default_model="gemini-3.8-flash",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    ),
    "groq": ProviderConfig(
        key="groq",
        display_name="Groq",
        api_key_env="GROQ_API_KEY",
        default_model="openai/gpt-oss-20b",
        base_url="https://api.groq.com/openai/v1",
    ),
    "custom": ProviderConfig(
        key="custom",
        display_name="Custom OpenAI-compatible API",
        api_key_env="CUSTOM_LLM_API_KEY",
        default_model="",
        base_url=None,
    ),
}


class LLMClient(Protocol):
    provider_name: str
    model: str

    def generate(self, prompt: str) -> str: ...

    def chat(
        self, messages: list[dict[str, str]], system_prompt: str | None = None
    ) -> str: ...


class OpenAICompatibleClient:
    """One adapter for providers that expose OpenAI-compatible Chat Completions."""

    def __init__(
        self,
        api_key: str,
        model: str,
        provider_name: str,
        base_url: str | None = None,
    ) -> None:
        if not api_key:
            raise ValueError(f"An API key is required for {provider_name}.")
        if not model:
            raise ValueError("A model name is required.")
        self.provider_name = provider_name
        self.model = model
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def generate(self, prompt: str) -> str:
        return self.chat([{"role": "user", "content": prompt}])

    def chat(
        self, messages: list[dict[str, str]], system_prompt: str | None = None
    ) -> str:
        request_messages: list[dict[str, str]] = []
        if system_prompt:
            request_messages.append({"role": "system", "content": system_prompt})
        request_messages.extend(
            {
                "role": message["role"],
                "content": message["content"],
            }
            for message in messages
            if message.get("role") in {"user", "assistant", "system"}
            and message.get("content")
        )
        response = self._client.chat.completions.create(
            model=self.model,
            messages=request_messages,
        )
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError(f"{self.provider_name} returned an empty response.")
        return content if isinstance(content, str) else str(content)


def create_llm_client(
    provider: str,
    api_key: str,
    model: str | None = None,
    custom_base_url: str | None = None,
) -> OpenAICompatibleClient:
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown LLM provider: {provider}")
    config = PROVIDERS[provider]
    base_url = custom_base_url if provider == "custom" else config.base_url
    if provider == "custom" and not base_url:
        raise ValueError("A base URL is required for a custom provider.")
    return OpenAICompatibleClient(
        api_key=api_key,
        model=model or config.default_model,
        provider_name=config.display_name,
        base_url=base_url,
    )
