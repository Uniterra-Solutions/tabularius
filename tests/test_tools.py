"""Tests for tools.py — hand-written memory tools (real tmp dirs)."""

import json

import pytest

from tabularius import tools


@pytest.fixture
def memory_root(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Point the memory directory at a real tmp dir via HERMES_HOME."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    root = tmp_path / "memory"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _parse(result: str) -> dict:
    return json.loads(result)


class TestMemoryRead:
    def test_reads_existing_file(self, memory_root) -> None:
        (memory_root / "a.md").write_text("# A\ncontent\n", encoding="utf-8")
        result = _parse(tools.memory_read("a.md"))
        assert result["ok"] is True
        assert result["content"] == "# A\ncontent\n"

    def test_missing_file_returns_error(self, memory_root) -> None:
        result = _parse(tools.memory_read("missing.md"))
        assert result["ok"] is False
        assert "not found" in result["error"]

    def test_rejects_traversal(self, memory_root) -> None:
        result = _parse(tools.memory_read("../secret.md"))
        assert result["ok"] is False
        assert "escapes" in result["error"]

    def test_rejects_absolute_path(self, memory_root) -> None:
        result = _parse(tools.memory_read("/etc/passwd"))
        assert result["ok"] is False

    def test_nul_byte_path_returns_error_json(self, memory_root) -> None:
        # A NUL byte makes pathlib.resolve() raise ValueError; the tool must
        # translate that into error JSON instead of propagating the exception.
        result = _parse(tools.memory_read("a\x00b.md"))
        assert result["ok"] is False
        result = _parse(tools.memory_write("a\x00b.md", "x", "create"))
        assert result["ok"] is False


class TestMemoryWrite:
    def test_create_new_file(self, memory_root) -> None:
        result = _parse(tools.memory_write("new.md", "# New\n", "create"))
        assert result["ok"] is True
        assert (memory_root / "new.md").read_text(encoding="utf-8") == "# New\n"

    def test_create_refuses_overwrite(self, memory_root) -> None:
        (memory_root / "a.md").write_text("original", encoding="utf-8")
        result = _parse(tools.memory_write("a.md", "clobbered", "create"))
        assert result["ok"] is False
        assert "overwrite" in result["error"]
        # Existing content untouched.
        assert (memory_root / "a.md").read_text(encoding="utf-8") == "original"

    def test_merge_updates_existing(self, memory_root) -> None:
        (memory_root / "a.md").write_text("old", encoding="utf-8")
        result = _parse(tools.memory_write("a.md", "old\nnew-line\n", "merge"))
        assert result["ok"] is True
        assert (memory_root / "a.md").read_text(encoding="utf-8") == "old\nnew-line\n"

    def test_merge_requires_existing(self, memory_root) -> None:
        result = _parse(tools.memory_write("ghost.md", "x", "merge"))
        assert result["ok"] is False
        assert "create" in result["error"]

    def test_invalid_action_rejected(self, memory_root) -> None:
        result = _parse(tools.memory_write("a.md", "x", "upsert"))
        assert result["ok"] is False

    def test_merge_preserves_old_content_semantics(self, memory_root) -> None:
        # merge must never silently drop existing content — the tool layer
        # requires the agent to have read first and pass the full final
        # content; a create on an existing file is refused.
        (memory_root / "a.md").write_text("keep-me", encoding="utf-8")
        merged = _parse(tools.memory_write("a.md", "keep-me\n+added", "merge"))
        assert merged["ok"] is True
        assert (memory_root / "a.md").read_text(encoding="utf-8") == "keep-me\n+added"

    def test_atomic_write_leaves_no_tmp_files(self, memory_root) -> None:
        tools.memory_write("a.md", "content", "create")
        leftovers = [p.name for p in memory_root.iterdir() if ".tmp" in p.name]
        assert leftovers == []

    def test_write_rejects_traversal(self, memory_root) -> None:
        result = _parse(tools.memory_write("../evil.md", "x", "create"))
        assert result["ok"] is False

    def test_write_to_existing_directory_returns_error_json(self, memory_root) -> None:
        # Tools must return error JSON, never raise (contract: JSON strings only).
        (memory_root / "subdir").mkdir()
        result = _parse(tools.memory_write("subdir", "x", "create"))
        assert result["ok"] is False
        assert "write failed" in result["error"]

    def test_write_when_parent_is_file_returns_error_json(self, memory_root) -> None:
        (memory_root / "afile.md").write_text("x", encoding="utf-8")
        result = _parse(tools.memory_write("afile.md/child.md", "x", "create"))
        assert result["ok"] is False


class TestMemoryList:
    def test_no_index_scans_directory(self, memory_root) -> None:
        (memory_root / "user-profile.md").write_text("- User is Alice\n", encoding="utf-8")
        (memory_root / "agent-notes.md").write_text("- note\n", encoding="utf-8")
        result = _parse(tools.memory_list())
        assert result == {
            "ok": True,
            "entries": [
                {"path": "agent-notes.md", "description": ""},
                {"path": "user-profile.md", "description": ""},
            ],
        }

    def test_empty_dir_returns_empty(self, memory_root) -> None:
        result = _parse(tools.memory_list())
        assert result == {"ok": True, "entries": []}

    def test_parses_index_entries(self, memory_root) -> None:
        (memory_root / "INDEX.md").write_text(
            "# Memory Index\n\n## Categories\n"
            "- `uniterra-vps-infra.md` — VPS 基礎設施細節\n"
            "- `uniterra-email.md` — 郵件設定\n",
            encoding="utf-8",
        )
        result = _parse(tools.memory_list())
        assert result["ok"] is True
        assert result["entries"] == [
            {"path": "uniterra-vps-infra.md", "description": "VPS 基礎設施細節"},
            {"path": "uniterra-email.md", "description": "郵件設定"},
        ]

    def test_ignores_non_category_sections(self, memory_root) -> None:
        (memory_root / "INDEX.md").write_text(
            "# Memory Index\n\n## Other\n- `junk.md` — not an entry\n\n## Categories\n"
            "- `real.md` — real entry\n",
            encoding="utf-8",
        )
        result = _parse(tools.memory_list())
        assert result["entries"] == [{"path": "real.md", "description": "real entry"}]


class TestIndexUpdate:
    def test_writes_canonical_index(self, memory_root) -> None:
        result = _parse(
            tools.index_update(
                [
                    {"path": "a.md", "description": "Desc A", "related": ["b.md"]},
                    {"path": "b.md", "description": "Desc B"},
                ]
            )
        )
        assert result["ok"] is True
        assert result["count"] == 2
        content = (memory_root / "INDEX.md").read_text(encoding="utf-8")
        assert "# Memory Index" in content
        assert "auto-generated by tabularius" in content
        assert "- `a.md` — Desc A" in content

    def test_rejects_invalid_entries(self, memory_root) -> None:
        result = _parse(tools.index_update([{"path": "a.md"}]))
        assert result["ok"] is False

    def test_roundtrip_with_memory_list(self, memory_root) -> None:
        tools.index_update([{"path": "x.md", "description": "X desc"}])
        listed = _parse(tools.memory_list())
        assert listed["entries"] == [{"path": "x.md", "description": "X desc"}]


class TestSpawnReader:
    def test_returns_reader_output(self, memory_root, monkeypatch: pytest.MonkeyPatch) -> None:
        (memory_root / "a.md").write_text("Some doc content", encoding="utf-8")

        # Stub the underlying agent loop so no LLM is needed.
        class _FakeOutput:
            def model_dump_json(self) -> str:
                return json.dumps(
                    {
                        "path": "a.md",
                        "summary": "summary",
                        "key_topics": ["t"],
                        "category_hint": "c",
                    }
                )

        def _fake_run_agent(system, user, tools, schema, *, client=None):
            return _FakeOutput()

        monkeypatch.setattr("tabularius.agent_loop.run_agent", _fake_run_agent)
        result = _parse(tools.spawn_reader("a.md"))
        assert result == {
            "path": "a.md",
            "summary": "summary",
            "key_topics": ["t"],
            "category_hint": "c",
        }

    def test_missing_file_returns_error(self, memory_root) -> None:
        result = _parse(tools.spawn_reader("missing.md"))
        assert result["ok"] is False


class TestRegistry:
    def test_all_schemas_have_handlers(self) -> None:
        names = [s["function"]["name"] for s in tools.TOOL_SCHEMAS]
        assert set(names) == set(tools.TOOL_REGISTRY)
