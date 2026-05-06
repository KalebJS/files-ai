# Repository Guidelines

## Project Structure & Module Organization
- Core application code lives in `src/files_ai/`.
  - `storage/` contains the `Files` protocol and backend implementations (currently `LocalFiles`).
  - `__main__.py` is the service entrypoint (`python -m files_ai`).
  - Other modules handle extraction, routing, moving, persistence, and watcher behavior.
- Tests are in `tests/` with storage-focused tests under `tests/storage/`.
- Runtime/deploy files are at repo root: `compose.yaml`, `Dockerfile`, `.env.example`.

## Build, Test, and Development Commands
- `uv sync --extra dev` — install runtime + dev dependencies.
- `uv run pytest` — run all tests.
- `prek run -a` — run all pre-commit hooks (Ruff + Bandit).
- `uv run files-ai --once` — process current dropzone files once and exit.
- `docker compose up --build` — run service in container with host-mounted data.

## Coding Style & Naming Conventions
- Python 3.13+ codebase, 4-space indentation, type hints required for public functions.
- Ruff is the source of truth for lint/format rules.
  - Max line length: **88**
  - Import sorting via Ruff isort with **one import per line**.
- Naming:
  - Modules/functions: `snake_case`
  - Classes/dataclasses: `PascalCase`
  - Constants: `UPPER_SNAKE_CASE`

## Testing Guidelines
- Test framework: `pytest`.
- Place tests near feature domain (`tests/storage/test_local.py`, etc.).
- Name files `test_*.py` and test functions `test_*`.
- For behavior changes, add/adjust tests in same PR before merge.

## Commit & Pull Request Guidelines
- Follow Conventional Commits style seen in history (example: `feat: bootstrap files-ai organizer service`).
- Keep commit messages focused on intent and scope.
- PRs should include:
  - concise summary of change,
  - test evidence (`uv run pytest`, `prek run -a`),
  - config/env impacts (if `.env.example` changed).

## Security & Configuration Tips
- Never commit secrets; keep API keys in local `.env`.
- Validate file operations through the `Files` abstraction instead of direct ad-hoc path handling.
- Run `bandit` via pre-commit before pushing security-sensitive changes.
