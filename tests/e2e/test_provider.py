"""Level 3 — provider lifecycle inside a real Hermes session.

Verifies the plugin loads without breaking Hermes: a `chat -q` invocation
fails only on the (expected) missing inference provider — never with a
plugin traceback. With a relay key present, the provider reports available
without making network calls.
"""

from __future__ import annotations


class TestProviderAvailability:
    def test_available_with_relay_key(self, hermes_home, run_hermes) -> None:
        """A configured relay key flips status to available (no network)."""
        code, output = run_hermes(
            hermes_home,
            "hermes",
            "tabularius",
            "status",
            env={"TABULARIUS_API_KEY": "test-key"},
        )
        assert code == 0, output
        assert "Available:        yes" in output


class TestHermesChatIntegration:
    def test_chat_fails_only_on_inference_provider(self, hermes_home, run_hermes) -> None:
        """Hermes starts with the plugin loaded; chat's failure is about the
        inference provider, never a tabularius import/crash error."""
        code, output = run_hermes(hermes_home, "hermes", "chat", "-q", "hello", "-Q")
        assert code == 1, output
        # Either message is fine — the point is no plugin crash.
        assert (
            "No inference provider configured" in output or "No interactive TTY detected" in output
        ), output
        assert "Traceback" not in output

    def test_chat_with_plugin_env_does_not_break_hermes(self, hermes_home, run_hermes) -> None:
        """Even with a bogus relay key, Hermes must not crash on plugin load."""
        code, output = run_hermes(
            hermes_home,
            "hermes",
            "chat",
            "-q",
            "hello",
            "-Q",
            env={"TABULARIUS_API_KEY": "test-key"},
        )
        # Fails (no real inference provider) but never with a plugin crash.
        assert "Traceback" not in output
