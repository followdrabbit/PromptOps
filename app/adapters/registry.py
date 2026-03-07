from __future__ import annotations

from app.adapters.openai_compatible import OpenAICompatibleProvider


PROVIDER_REGISTRY = {
    "openai-compatible": OpenAICompatibleProvider,
    "generic-rest": OpenAICompatibleProvider,
}


def get_provider_class(provider_name: str):
    return PROVIDER_REGISTRY.get(provider_name, OpenAICompatibleProvider)
