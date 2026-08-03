"""CLI commands for tabularius (issues #11, #12).

Follows the Hermes memory-provider CLI convention: ``register_cli(subparser)``
builds ``hermes tabularius <status|setup|update|init|reindex>`` and
``tabularius_command`` dispatches (see ``plugins.memory.discover_plugin_cli_commands``).
Discovery is gated on ``memory.provider: tabularius`` in config.yaml.

- ``status`` — provider availability + extraction/reindex state (#11)
- ``setup`` — ensure the memory directory and activate the provider (#11)
- ``update`` — fabricium-based self-update (pip/git) (#11)
- ``init`` — batch-extract unprocessed sessions from state.db, rebuild the
  index, back up memory entries, and (with ``--force``) switch MEMORY.md to
  the INDEX.md pointer (#12)
- ``reindex`` — rebuild INDEX.md + Related only (#12)
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from fabricium import HermesPlugin
from fabricium.prompts import prompt_yes_no

from tabularius.agents.index import run_index_agent
from tabularius.agents.memory import run_memory_agent
from tabularius.llm import LLMClient
from tabularius.provider import PROVIDER_NAME, create_provider
from tabularius.sessions import (
    SessionRecord,
    default_db_path,
    find_unprocessed,
    load_transcript,
)
from tabularius.state import (
    legacy_processed_sessions,
    load_state,
    record_extraction,
    record_reindex,
)
from tabularius.tools import _atomic_write, memory_dir, memory_write

BATCH_SIZE = 5
MEMORY_POINTER = "Memory → see ~/.hermes/memory/INDEX.md"


class TabulariusPlugin(HermesPlugin):
    """Fabricium lifecycle manager for tabularius (issue #11).

    Reuses the caelterra/jovaltus setup/status/update pattern. Tabularius
    ships no bundled skills and installs to no profile, so profile syncing
    is a deliberate no-op.
    """

    def _sync_installed_profiles(self, context: str = "") -> None:
        return


_plugin = TabulariusPlugin(name="tabularius", plugin_dir=Path(__file__).resolve().parent)


# ---------------------------------------------------------------------------
# argparse wiring (Hermes memory-plugin convention)
# ---------------------------------------------------------------------------


def register_cli(subparser: Any) -> None:
    """Build the ``hermes tabularius`` argparse tree."""
    subs = subparser.add_subparsers(dest="tabularius_command")

    subs.add_parser("status", help="Show provider availability and extraction state")
    subs.add_parser("setup", help="Ensure the memory directory and activate the provider")

    init_parser = subs.add_parser(
        "init", help="Extract all unprocessed sessions from state.db (default: dry run)"
    )
    init_parser.add_argument(
        "--force", action="store_true", help="Actually extract, rebuild, and clear MEMORY.md"
    )
    init_parser.add_argument(
        "--db", default=None, help="Path to Hermes state.db (default: auto-detected)"
    )

    subs.add_parser("reindex", help="Rebuild INDEX.md and Related blocks")

    update_parser = subs.add_parser("update", help="Check for and apply tabularius updates")
    update_parser.add_argument("--check", action="store_true", help="Only check, do not update")
    mode_group = update_parser.add_mutually_exclusive_group()
    mode_group.add_argument("--git", action="store_true", help="Force git-based update")
    mode_group.add_argument("--pip", action="store_true", help="Force pip-based update")

    subparser.set_defaults(func=tabularius_command)


def tabularius_command(args: Any) -> None:
    """Dispatch ``hermes tabularius <subcommand>``."""
    sub = getattr(args, "tabularius_command", None)
    if sub == "status":
        cmd_status(args)
    elif sub == "setup":
        cmd_setup(args)
    elif sub == "update":
        cmd_update(args)
    elif sub == "init":
        cmd_init(args)
    elif sub == "reindex":
        cmd_reindex(args)
    else:
        print(f"Usage: hermes {PROVIDER_NAME} <status|setup|update|init|reindex>")
        sys.exit(2)


# ---------------------------------------------------------------------------
# status / setup / update (issue #11)
# ---------------------------------------------------------------------------


def cmd_status(args: Any) -> None:
    """Show provider availability + recent extraction state."""
    print(f"📊 {PROVIDER_NAME.title()} Status")
    print("━" * 40)

    s = load_state()
    committed = s.get("committed_sessions", {})
    stats = s.get("extraction_stats", {})

    provider = create_provider()
    available = provider.is_available()
    print(f"\n  Provider:         {PROVIDER_NAME}")
    hint = "yes" if available else "no (set TABULARIUS_API_KEY or OPENAI_API_KEY)"
    print(f"  Available:        {hint}")
    print(f"  Committed:        {len(committed)} session(s)")
    last_extraction = _latest_stat_time(stats)
    print(f"  Last extraction:  {last_extraction or '—'}")
    print(f"  Last reindex:     {s.get('last_reindex') or '—'}")


def cmd_setup(args: Any) -> None:
    """Ensure the memory directory and activate tabularius as the provider."""
    print(f"⚡ {PROVIDER_NAME.title()} Setup")
    print("━" * 40)

    root = memory_dir()
    root.mkdir(parents=True, exist_ok=True)
    print(f"\n  ✓ Memory directory: {root}")

    if prompt_yes_no(f"  Activate {PROVIDER_NAME} as the Hermes memory provider?", default=True):
        if _activate_provider():
            print("  ✓ memory.provider = tabularius")
        else:
            print(f"    Run manually: hermes config set memory.provider {PROVIDER_NAME}")

    print(f"\n  Next: hermes {PROVIDER_NAME} init --force   (migrate existing sessions)")


def cmd_update(args: Any) -> None:
    """Check for / apply updates via fabricium (pip preferred, git fallback)."""
    if getattr(args, "check", False):
        _plugin._update_check(args)
    else:
        _plugin._update_pull(args)


def _activate_provider() -> bool:
    """Set ``memory.provider: tabularius`` via the Hermes CLI."""
    try:
        subprocess.run(
            ["hermes", "config", "set", "memory.provider", PROVIDER_NAME],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _latest_stat_time(stats: dict[str, Any]) -> str | None:
    times = [str(entry.get("at", "")) for entry in stats.values() if isinstance(entry, dict)]
    return max(times) if times else None


# ---------------------------------------------------------------------------
# init / reindex (issue #12)
# ---------------------------------------------------------------------------


def cmd_init(
    args: Any,
    *,
    client: LLMClient | None = None,
    reader_client: LLMClient | None = None,
) -> int:
    """Batch-extract unprocessed sessions from state.db.

    Default is a dry run that only reports what would happen. ``--force``
    performs the full migration: backup entries → extract in batches of 5 →
    rebuild index → record state → switch MEMORY.md to the INDEX.md pointer
    (USER.md untouched).
    """
    db_path = Path(args.db) if getattr(args, "db", None) else default_db_path()
    force = bool(getattr(args, "force", False))

    committed = _committed_ids()
    unprocessed = find_unprocessed(db_path, committed)

    print(f"Scanning {db_path}: {len(unprocessed)} unprocessed session(s)")

    if not force:
        _report_dry_run(unprocessed)
        return 0

    backup_path = backup_memory_entries()
    print(f"  ✓ Backed up memory entries: {backup_path}")

    for start in range(0, len(unprocessed), BATCH_SIZE):
        batch = unprocessed[start : start + BATCH_SIZE]
        transcripts = [load_transcript(db_path, record.id) for record in batch]
        if not any(transcripts):
            continue
        output = run_memory_agent(transcripts, client=client)
        failures = 0
        for doc in output.documents:
            write = json.loads(memory_write(doc.path, doc.content, doc.action))
            if not write.get("ok"):
                failures += 1
                print(f"  ! write failed for {doc.path}: {write.get('error')}")
        if failures:
            print(f"  ! batch of {len(batch)} skipped commit (write failures)")
            continue
        for record in batch:
            record_extraction(record.id, output.stats)
        print(f"  ✓ extracted {len(batch)} session(s)")

    print("  Rebuilding index...")
    run_index_agent(client=client, reader_client=reader_client)
    record_reindex()

    cleared = clear_memory_file()
    print(f"  ✓ MEMORY.md switched to INDEX.md pointer: {cleared}")

    print("  ✅ init complete")
    return 0


def cmd_reindex(
    args: Any,
    *,
    client: LLMClient | None = None,
    reader_client: LLMClient | None = None,
) -> int:
    """Rebuild INDEX.md + Related blocks only (idempotent)."""
    print("Rebuilding index...")
    run_index_agent(client=client, reader_client=reader_client)
    record_reindex()
    print("  ✅ index rebuilt")
    return 0


def _report_dry_run(unprocessed: list[SessionRecord]) -> None:
    """Print what ``init --force`` would do without executing anything."""
    print("DRY RUN — pass --force to execute.")
    for record in unprocessed[:20]:
        count = record.message_count
        suffix = f" ({count} message(s))" if count is not None else ""
        print(f"  - {record.id}{suffix}")
    if len(unprocessed) > 20:
        print(f"  … and {len(unprocessed) - 20} more")
    batches = (len(unprocessed) + BATCH_SIZE - 1) // BATCH_SIZE
    print(
        f"Would: run {batches} extraction batch(es), rebuild the index, "
        "back up memory entries, and switch MEMORY.md to the INDEX.md pointer."
    )


def _committed_ids() -> dict[str, str]:
    """Committed sessions from state.json, merged with the legacy archive."""
    ids = dict(load_state().get("committed_sessions", {}))
    for session_id in legacy_processed_sessions():
        ids.setdefault(session_id, "legacy")
    return ids


# ---------------------------------------------------------------------------
# memory switchover helpers (#12)
# ---------------------------------------------------------------------------


def _builtin_memories_dir() -> Path:
    """Hermes built-in memory files (``~/.hermes/memories/``)."""
    return memory_dir().parent / "memories"


def _read_optional(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def backup_memory_entries() -> Path:
    """Archive current MEMORY.md / USER.md to ``memory/archive/pre-init-<ts>.json``."""
    memories = _builtin_memories_dir()
    archive = memory_dir() / "archive"
    archive.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = archive / f"pre-init-{timestamp}.json"
    suffix = 2
    while path.exists():
        path = archive / f"pre-init-{timestamp}-{suffix}.json"
        suffix += 1

    payload = {
        "backup_time": datetime.now().isoformat(timespec="seconds"),
        "memory_raw": _read_optional(memories / "MEMORY.md"),
        "user_raw": _read_optional(memories / "USER.md"),
    }
    _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return path


def clear_memory_file() -> Path:
    """Replace MEMORY.md entries with the INDEX.md pointer; USER.md untouched."""
    memories = _builtin_memories_dir()
    memories.mkdir(parents=True, exist_ok=True)
    target = memories / "MEMORY.md"
    target.write_text(f"{MEMORY_POINTER}\n", encoding="utf-8")
    return target


__all__ = [
    "MEMORY_POINTER",
    "TabulariusPlugin",
    "backup_memory_entries",
    "clear_memory_file",
    "cmd_init",
    "cmd_reindex",
    "cmd_setup",
    "cmd_status",
    "cmd_update",
    "register_cli",
    "tabularius_command",
]
