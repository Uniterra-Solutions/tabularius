"""Level 1 — plugin installation smoke tests.

Verify the plugin is discovered by Hermes as a memory provider and its CLI
is reachable inside a fresh Docker container with a mounted HERMES_HOME.

These tests need no LLM API key: discovery and CLI wiring are offline.
"""

from __future__ import annotations


class TestMemoryProviderDiscovery:
    def test_memory_status_lists_tabularius_active(self, hermes_home, run_hermes) -> None:
        code, output = run_hermes(hermes_home, "hermes", "memory", "status")
        assert code == 0, output
        assert "tabularius" in output
        assert "← active" in output

    def test_provider_loads_without_plugin_errors(self, hermes_home, run_hermes) -> None:
        code, output = run_hermes(hermes_home, "hermes", "memory", "status")
        assert code == 0, output
        # A broken plugin would surface a traceback or "not installed".
        assert "Traceback" not in output


class TestTabulariusCliDiscovery:
    def test_tabularius_subcommand_discovered(self, hermes_home, run_hermes) -> None:
        """`hermes tabularius status` exists once memory.provider is set."""
        code, output = run_hermes(hermes_home, "hermes", "tabularius", "status")
        assert code == 0, output
        assert "Provider:         tabularius" in output
        assert "Committed:" in output

    def test_cli_absent_without_provider_config(self, tmp_path, run_hermes) -> None:
        """Without memory.provider: tabularius the subcommand is not wired."""
        # Bare HERMES_HOME: no plugin shim, no config gating.
        home = tmp_path / "bare"
        home.mkdir()
        code, output = run_hermes(home, "hermes", "tabularius", "status")
        assert code != 0
        assert "invalid choice" in output
