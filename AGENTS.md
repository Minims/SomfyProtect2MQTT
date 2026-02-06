# AGENTS

This file is guidance for coding agents working in this repo.
Keep changes small, follow existing patterns, and update docs if behavior changes.

## Project Basics

- Language: Python 3.12+.
- Packaging: Poetry (pyproject.toml) and requirements files for runtime/dev.
- Entry point: `somfyProtect2Mqtt/main.py`.
- Configuration: `somfyProtect2Mqtt/config/config.yaml` (copy from example).
- No Cursor/Copilot rules found in `.cursor/rules/`, `.cursorrules`, or `.github/copilot-instructions.md`.

## Common Commands

### Setup (choose one)

- Poetry: `poetry install`.
- Pip: `pip3 install -r somfyProtect2Mqtt/requirements/common.txt`.
- Dev tools: `pip3 install -r somfyProtect2Mqtt/requirements/dev.txt`.

### Run (local)

- From `somfyProtect2Mqtt/`: `python3 main.py -c config/config.yaml`.
- Verbose logs: `python3 main.py -c config/config.yaml -v`.

### Format

- Black: `python -m black somfyProtect2Mqtt`.
- Isort: `python -m isort somfyProtect2Mqtt`.

### Lint

- Pylint: `python -m pylint somfyProtect2Mqtt`.

### Build

- Packaging is Poetry-based; build artifacts are uncommon for this repo.
- If needed: `poetry build`.

### Tests

- No automated tests are configured or present in this repo.
- If you add tests, prefer pytest and document it here.

### Single Test (if pytest is added)

- Run a file: `python -m pytest tests/test_name.py`.
- Run a single test: `python -m pytest tests/test_name.py::test_case_name`.

## Code Style Overview

- Match existing code style in `somfyProtect2Mqtt/` and avoid sweeping refactors.
- Keep modules focused; avoid large, cross-cutting changes unless necessary.
- Use logging instead of print.

## Formatting Rules

- Black is configured with `line-length = 120` (see `pyproject.toml`).
- Isort uses `profile = black` and `line_length = 120`.
- Avoid manual alignment; let Black handle wrapping.

## Imports

- Order: standard library, third-party, local application imports.
- Keep imports absolute within the package (e.g., `from somfy_protect.api import SomfyProtectApi`).
- Avoid wildcard imports.
- Local modules are typically imported by module name (e.g., `from exceptions import SomfyProtectInitError`).
- Group related imports and remove unused ones.

## Types

- Type hints exist in some modules; add hints for new public functions and classes.
- Use built-in `dict`, `list`, etc. unless a more specific type is needed.
- Prefer explicit `Optional[...]`/`| None` when values can be missing.
- Avoid introducing mypy-only patterns unless the repo adopts mypy.

## Naming Conventions

- Modules and packages: `snake_case`.
- Functions and variables: `snake_case`.
- Classes: `CapWords`.
- Constants: `UPPER_SNAKE_CASE`.
- Boolean fields use `is_`/`has_` prefixes where it reads well.

## Error Handling

- Raise specific exceptions (e.g., `SomfyProtectInitError`) for expected failures.
- Log context with `LOGGER.error(...)` and re-raise or exit cleanly.
- Avoid swallowing exceptions silently; if you must, log the reason.
- Prefer guard clauses for missing config values.

## Logging

- Use module-level loggers: `LOGGER = logging.getLogger(__name__)`.
- Prefer f-strings for log messages.
- Respect the debug flag and configured log level.

## Configuration

- Config is read from YAML via `read_config_file`.
- Access settings with `config.get(...)` and provide defaults where appropriate.
- Validate required sections early (e.g., `config.get("mqtt")`).
- Keep configuration keys stable to avoid breaking users.

## Concurrency

- The main loop uses threads for API and WebSocket loops.
- Keep thread targets small and robust; handle exceptions and clean shutdown.
- Avoid long blocking operations without timeouts.

## MQTT and API Usage

- Use existing helper functions in `somfyProtect2Mqtt/business/` for status updates.
- Keep API calls in the SomfyProtect API layer; avoid duplicating HTTP logic.
- When publishing to MQTT, follow the existing topic and payload patterns.

## Data Models

- Models under `somfyProtect2Mqtt/somfy_protect/api/model.py` use `__slots__`.
- Keep field names aligned to API responses, even if they are not ideal (e.g., `geoFence`).
- Pylint ignores some naming rules for API IDs; follow existing patterns.

## Pylint Conventions

- Pylint is used as the linter; keep warnings low in touched files.
- Existing code sometimes disables checks with `# pylint: disable=...` for API-driven names.
- Do not add blanket disables; keep them narrow and justified.

## File Organization

- Core runtime code lives under `somfyProtect2Mqtt/`.
- Somfy API logic is under `somfyProtect2Mqtt/somfy_protect/`.
- Home Assistant discovery code is under `somfyProtect2Mqtt/homeassistant/`.
- Streaming helpers live in `somfyProtect2Mqtt/business/streaming/`.

## Docs and Comments

- Docstrings are used for public classes and functions; keep them concise.
- Add comments only when the logic is non-obvious.
- Update README if you change user-facing behavior or commands.

## Tooling Notes

- Python version target is 3.12+ (see `pyproject.toml`).
- Dev dependencies include black, isort, pylint (see `somfyProtect2Mqtt/requirements/dev.txt`).

## Safe Changes Checklist

- Run formatters (Black/Isort) for modified Python files.
- Run pylint on touched modules if practical.
- Keep behavioral changes minimal unless requested.
- Avoid changing log output without a reason.

## When Adding Tests

- Use pytest with `tests/` at repo root or `somfyProtect2Mqtt/tests/`.
- Name files `test_*.py` and tests `test_*`.
- Add test requirements to `somfyProtect2Mqtt/requirements/dev.txt`.
- Document the test commands in this file.

## Commit Hygiene for Agents

- Do not commit unless explicitly requested.
- Do not use destructive git commands.
- Keep commits focused and well-described.

## Commit Message Guidelines (Conventional Commits)

- Format: `type(scope): summary` (scope is mandatory, but free-form).
- Use the imperative mood in the summary (e.g., "Add", "Fix", "Refactor").
- Keep the summary concise (50-72 characters), no trailing period.
- Use `!` to mark breaking changes, or add a footer:
  `BREAKING CHANGE: <description>`.
- Recommended types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `build`, `ci`.

Examples:
- `fix(mqtt): handle reconnect backoff`
- `docs(readme): clarify setup steps`
- `feat(config)!: rename mqtt host setting`
  `BREAKING CHANGE: mqtt.host replaced by mqtt.broker`

## Notes on External Rules

- No additional Cursor/Copilot instruction files were found.
