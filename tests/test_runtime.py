"""Composition-root tests: entry-point discovery and config-driven provider switching."""

from app.plugins.base import discover_plugin_classes
from app.runtime import get_runtime, reset_runtime_for_tests


def test_entry_points_discover_bundled_plugins():
    classes = discover_plugin_classes()
    assert {"anthropic", "openrouter", "ollama", "langfuse", "feedly"} <= set(classes)


async def test_runtime_degrades_without_credentials():
    """With no API keys set, LLM plugins refuse to initialize and the runtime runs
    degraded: embeddings work, LLM operations raise a clear error."""
    reset_runtime_for_tests()
    runtime = await get_runtime()
    assert runtime.plugins.get("ollama") is not None  # no credentials needed
    assert runtime.plugins.get("anthropic") is None  # PluginInitError: no key

    try:
        runtime.llm_for("classification")
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "No LLM plugin available" in str(exc)


async def test_provider_switch_via_config_alone(monkeypatch):
    """Switching providers is a config change, not a code change: set the key and
    flip ai_config, and classification resolves to a different provider."""
    from sqlalchemy import text

    from app.config import settings
    from app.database import async_session
    from app.providers.llm.openrouter import OpenRouterProvider

    monkeypatch.setattr(settings, "openrouter_api_key", "sk-or-test")
    async with async_session() as db:
        await db.execute(
            text(
                """UPDATE ai_config SET config_value =
                   '{"provider": "openrouter", "model": "meta-llama/llama-3.3-70b-instruct", "temperature": 0.3}'
                   WHERE config_key = 'llm_classification'"""
            )
        )
        await db.execute(
            text("UPDATE plugins SET enabled = true WHERE id = 'openrouter'")
        )
        await db.commit()

    reset_runtime_for_tests()
    try:
        runtime = await get_runtime()
        provider, params = runtime.llm_for("classification")
        assert isinstance(provider, OpenRouterProvider)
        assert params["model"] == "meta-llama/llama-3.3-70b-instruct"
    finally:
        # restore registry state for other tests
        async with async_session() as db:
            await db.execute(
                text("UPDATE plugins SET enabled = false WHERE id = 'openrouter'")
            )
            await db.execute(
                text(
                    """UPDATE ai_config SET config_value =
                       '{"provider": "anthropic", "model": "claude-haiku-4-5-20251001", "temperature": 0.3, "max_tokens": 1024}'
                       WHERE config_key = 'llm_classification'"""
                )
            )
            await db.commit()
        reset_runtime_for_tests()
