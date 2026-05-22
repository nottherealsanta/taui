"""Tests for model catalog helpers."""

from taui.llm_provider.models import get_model_variants


def test_get_model_variants_returns_empty_for_catalog_miss(monkeypatch):
    monkeypatch.setattr("taui.llm_provider.models.fetch_models", lambda force=False: {})

    assert get_model_variants("codex", "gpt-4o") == []


def test_get_model_variants_uses_catalog_entries(monkeypatch):
    monkeypatch.setattr(
        "taui.llm_provider.models.fetch_models",
        lambda force=False: {
            "openai": {
                "models": {
                    "gpt-5.3-codex": {
                        "name": "GPT-5.3 Codex",
                        "tool_call": True,
                        "reasoning": True,
                    }
                }
            }
        },
    )

    assert get_model_variants("codex", "gpt-5.3-codex") == [
        "none",
        "low",
        "medium",
        "high",
        "xhigh",
    ]
