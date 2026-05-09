# files-ai

AI-powered file organizer service that watches a dropzone, extracts file content, and routes files into an organized folder tree using LangChain + Ollama Cloud.

## Features

- Single-backend `Files` protocol abstraction (phase 1 uses local filesystem backend).
- Dropzone watcher with stabilization delay to avoid processing incomplete writes.
- Tiered extraction pipeline:
  - filename + MIME sniff,
  - text extraction for `txt`, `pdf`, `docx`,
  - optional OCR for images.
- LLM-based routing decisions with fallback heuristics.
- User-maintained `CONTEXT.md` support (read from the directory adjacent to
  `DROPZONE`) and injected into agent prompts.
- Johnny.Decimal destination enforcement with automatic area/category/ID
  allocation in `Area/Category/ID` shape.
- Agent/reviewer tree context rendered as JSON object structures.
- SQLite persistence for file metadata and routing decisions.
- Post-batch refinement reviewer (Kimi K2.6 by default) that can suggest and
  apply follow-up moves/folder creation after each batch.
- Docker Compose deployment with host-mounted data.

## Project layout

- `src/files_ai/` — application code
  - `storage/` protocol + backend implementations
  - `__main__.py` process orchestration entrypoint
  - `extract.py`, `agent.py`, `mover.py`, `store.py`, `watcher.py`
- `tests/` — pytest suite
- `compose.yaml`, `Dockerfile`, `.env.example` — deployment/configuration

## Quickstart (local)

1. Install deps:

```bash
uv sync --extra dev
```

2. Create env file:

```bash
cp .env.example .env
```

3. Run once (process existing files and exit):

```bash
uv run files-ai --once
```

4. Run watcher mode:

```bash
uv run files-ai
```

## Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

Host data defaults to `./data` (override with `HOST_DATA`).

Expected directories under mounted root:

- `dropzone/` — incoming files
- `organized/` — routed files
- `quarantine/` — low-confidence/problem files
- `state.db` — SQLite state

## Configuration

Primary environment variables:

- `BACKEND` (default `local`)
- `BACKEND_OPTS__ROOT` (default `/data`)
- `DROPZONE`, `ORGANIZED`, `QUARANTINE`
- `OLLAMA_API_KEY`, `OLLAMA_BASE_URL`, `MODEL`
- `BATCH_REVIEW_ENABLED`, `BATCH_REVIEW_MODEL`
- `BATCH_REVIEW_QUIET_SECONDS`, `BATCH_REVIEW_MAX_ACTIONS`
- `DRY_RUN`, `OCR_ENABLED`, `MAX_DEPTH`, `EXTRACT_MAX_BYTES`
- `CONTEXT_MAX_BYTES`

See `docs/CONFIGURATION.md` for details.

## Context file

- Optional context file path is derived from `DROPZONE`:
  - `DROPZONE=/dropzone` -> `CONTEXT.md` read from `/CONTEXT.md`
  - `DROPZONE=/data/dropzone` -> `CONTEXT.md` read from `/data/CONTEXT.md`
- This file is user-maintained and used as additional prompt context for
  routing and post-batch review.

## Johnny.Decimal routing shape

- Destinations are normalized to `Area/Category/ID` folder paths:
  - `10-19 Life Admin/13 Money/13.02 W-2s`
- If a matching location does not already exist, files-ai allocates the next
  available Johnny.Decimal area/category/ID slot.

## Development

- Lint/format/security checks:

```bash
prek run -a
```

- Tests:

```bash
uv run pytest
```

Ruff is configured for:

- max line length `88`
- pydocstyle (`D`)
- single-line imports via isort rules
