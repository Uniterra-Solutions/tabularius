"""Docker E2E fixtures for tabularius (docs/testing.md).

Levels (see hermes-plugin-testing skill):

1. Plugin installation smoke — provider discovered by Hermes
2. CLI offline — status / setup / init dry-run (no LLM key needed)
3. Provider lifecycle — plugin loads without breaking Hermes, availability
4. Full extraction pipeline — `init --force` with a real relay key
   (skipped when TABULARIUS_API_KEY is unset)

The whole suite is skipped when docker or the base image is unavailable so
`uv run pytest tests/ -q` keeps passing on machines without Docker.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "Dockerfile.test"
IMAGE_TAG = "tabularius-e2e:test"
BASE_IMAGE = "nousresearch/hermes-agent:latest"

PLUGIN_INIT = (
    "from tabularius import register\nfrom tabularius.provider import TabulariusMemoryProvider\n"
)
PLUGIN_CLI = "from tabularius.cli import register_cli, tabularius_command\n"
CONFIG_YAML = "memory:\n  provider: tabularius\n"

# Reuse the project's state.db builder (tests/fakes.py). pytest inserts
# tests/ on sys.path because tests/ has no __init__.py — importing here
# makes the module importable from e2e test files too.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _docker_ready() -> bool:
    """True when docker exists and the base hermes image is present."""
    if shutil.which("docker") is None:
        return False
    try:
        subprocess.run(["docker", "version"], capture_output=True, check=True, timeout=30)
        images = subprocess.run(
            ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return BASE_IMAGE in images.stdout
    except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
        return False


@pytest.fixture(scope="session")
def e2e_image() -> str:
    """Build (or reuse) the derived test image once per session."""
    if not _docker_ready():
        pytest.skip("docker or the hermes-agent base image unavailable")
    build = subprocess.run(
        ["docker", "build", "-f", str(DOCKERFILE), "-t", IMAGE_TAG, str(REPO_ROOT)],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if build.returncode != 0:
        pytest.fail(f"docker build failed:\n{build.stdout}\n{build.stderr}")
    return IMAGE_TAG


@pytest.fixture()
def hermes_home(tmp_path: Path) -> Path:
    """Fresh HERMES_HOME with the tabularius plugin shim + config.yaml."""
    home = tmp_path / "hermes_home"
    plugin_dir = home / "plugins" / "tabularius"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "__init__.py").write_text(PLUGIN_INIT, encoding="utf-8")
    (plugin_dir / "cli.py").write_text(PLUGIN_CLI, encoding="utf-8")
    (home / "config.yaml").write_text(CONFIG_YAML, encoding="utf-8")
    return home


@pytest.fixture()
def run_hermes(e2e_image: str):
    """Run a hermes command inside the container; return (exit_code, output)."""

    def _run(
        home: Path,
        *args: str,
        env: dict[str, str] | None = None,
        timeout: int = 300,
    ) -> tuple[int, str]:
        cmd = [
            "docker",
            "run",
            "--rm",
            "-e",
            "HERMES_HOME=/opt/data",
            "-v",
            f"{home}:/opt/data",
        ]
        for key, value in (env or {}).items():
            cmd += ["-e", f"{key}={value}"]
        cmd += [e2e_image, *args]
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", timeout=timeout
        )
        return proc.returncode, proc.stdout + proc.stderr

    return _run
