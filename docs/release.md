# Release Process

Pushing a `v<version>` tag triggers `.github/workflows/release.yml`, which
tests, publishes to PyPI, and creates the GitHub Release. No manual uploads —
PyPI publishing uses **trusted publishing** (OIDC), so no API tokens live in
the repo or in GitHub secrets.

## Pipeline (per tag push)

| Job | What it does | Gates |
|---|---|---|
| `test` | `uv sync --dev` + ruff check/format + mypy + `uv run pytest tests/` (Docker e2e skips without docker) | must pass |
| `publish` | Verifies `pyproject.toml` version == tag version, `uv build`, uploads sdist+wheel to PyPI via `pypa/gh-action-pypi-publish@release/v1` (trusted publishing, `id-token: write`) | needs `test` |
| `release` | Extracts the `## [<version>]` section from `CHANGELOG.md` and creates the GitHub Release (`gh release create ... --verify-tag`) | needs `publish` |

## One-time setup: PyPI trusted publisher

PyPI → Account settings → Publishing → **Add a new publisher**:

- Project name: `tabularius`
- Workflow name: `release.yml` — the file name, **not** the display name
- Environment: *(leave blank)*

Until the publisher is registered, the `publish` job fails with an OIDC
error.

## How to release

1. Bump `version` in `pyproject.toml` and prepend a
   `## [<version>] — YYYY-MM-DD` entry to `CHANGELOG.md` (Keep a Changelog
   format; headers carry **no** `v` prefix).
2. Commit: `chore(release): bump version to vX.Y.Z` (or fold the bump into
   the release commit — v0.5.9 precedent).
3. Tag: `git tag -a vX.Y.Z -m "vX.Y.Z: <summary>"`.
4. Push the tag **individually** — never `git push --tags` (GitHub silently
   drops webhook events when more than 3 tags are pushed at once):

   ```bash
   git push origin main
   git push origin vX.Y.Z
   ```

5. Verify within ~30 s:

   ```bash
   gh run list --workflow=release.yml --limit 3
   gh release view vX.Y.Z
   ```

## Manual re-trigger (recovery)

If a tag push did not trigger CI (webhook drop, tag created before the
workflow existed), re-run without deleting and re-pushing the tag:

```bash
gh workflow run release.yml --ref main -f tag=vX.Y.Z
```

Use `--ref main` (the tag commit may predate the `workflow_dispatch`
addition); the `tag` input makes checkout and version extraction target the
tag even though `github.ref` points at `main`.

## Notes

- Release notes are generated from `CHANGELOG.md`; if the tag has no matching
  `## [<version>]` section, the release body falls back to `Release vX.Y.Z`.
- The `publish` job fails unless `pyproject.toml` version == tag version —
  bump the manifest before tagging.
