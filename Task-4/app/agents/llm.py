"""Centralized LLM configuration and invocation."""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from app.config import logger, settings


def get_chat_model() -> BaseChatModel:
    """Instantiate the configured chat model."""
    provider = settings.llm_provider.lower().strip()
    logger.info("Initializing LLM | provider=%s", provider)

    if provider == "gemini":
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required when LLM_PROVIDER=gemini")
        return ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            google_api_key=settings.gemini_api_key,
            temperature=0,
        )

    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
    return ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=0,
    )


def invoke_llm(system_prompt: str, user_prompt: str) -> str:
    """Run a single-turn chat completion and return text content."""
    model = get_chat_model()
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]
    logger.debug("Invoking LLM | system_len=%d user_len=%d", len(system_prompt), len(user_prompt))
    response = model.invoke(messages)
    content = (response.content or "").strip()
    logger.debug("LLM response received | length=%d", len(content))
    return content
