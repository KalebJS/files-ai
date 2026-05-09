# Configuration Reference

This document describes runtime configuration for `files-ai`.

## Backend and paths

- `BACKEND`  
  Storage backend name. Phase 1 supports `local`.

- `BACKEND_OPTS__ROOT`  
  Root directory for backend path resolution (default `/data` in container).

- `DROPZONE`  
  Dropzone path within backend (default `/dropzone`).

- `ORGANIZED`  
  Organized output path within backend (default `/organized`).

- `QUARANTINE`  
  Quarantine path within backend (default `/quarantine`).

- `STATE_DB`  
  SQLite database file path (default `/data/state.db`).

## Model settings

- `OLLAMA_API_KEY`  
  API key for Ollama Cloud.

- `OLLAMA_BASE_URL`  
  Ollama endpoint, default `https://ollama.com`.

- `MODEL`  
  Chat model name, default `gpt-oss:120b-cloud`.

- `WATCH_QUIET_SECONDS`  
  In watch mode, minimum quiet window with no new stable events before a
  batch is considered complete and processed.

- `CONTEXT_MAX_BYTES`  
  Maximum bytes read from adjacent `CONTEXT.md` and inserted into agent prompts
  (default `16384`).

## Processing behavior

- `DRY_RUN` (`true`/`false`)  
  If true, decisions are logged without moving files.

- `MAX_DEPTH`  
  Maximum folder depth generated/used by routing logic.

- `EXTRACT_MAX_BYTES`  
  Byte limit for bounded text extraction reads.

- `OCR_ENABLED` (`true`/`false`)  
  Enables OCR fallback for image-like files.

- `LOG_LEVEL`  
  Logging verbosity (e.g. `INFO`, `DEBUG`).

## Context file behavior

- files-ai looks for a user-maintained `CONTEXT.md` adjacent to `DROPZONE` and
  includes its content in file-routing and folder-routing prompts.
- Example path resolution:
  - `DROPZONE=/dropzone` -> context at `/CONTEXT.md`
  - `DROPZONE=/data/dropzone` -> context at `/data/CONTEXT.md`
- Missing context file is treated as empty context.

## Folder crawling and dependency behavior

- The crawler is directory-aware:
  - files are routed with the file agent,
  - folders are first evaluated by a folder-level decision step.

- Folder decision outcomes:
  - **move as module**: entire folder is moved together when children are
    dependency-bound (for example software projects with `pyproject.toml`,
    `package.json`, `go.mod`, etc.).
  - **recurse**: folder is traversed and child files/folders are evaluated
    independently when contents are mostly unrelated documents/media.

- `.git` directories are never recursed. They are treated as dependency-bound
  folder units.

- Folder moves use directory-level dedupe hashing so duplicate folder trees can
  be skipped similarly to duplicate files.

## Johnny.Decimal destination behavior

- Final destination folders are enforced to Johnny.Decimal `Area/Category/ID`
  shape, for example:
  - `10-19 Life Admin/13 Money/13.02 W-2s`
- If an agent output is partial or non-conforming, files-ai validates/repairs
  the path and allocates the next available area/category/ID when needed.

## Docker notes

With Compose, set `HOST_DATA` to map host files into container `/data`:

```bash
HOST_DATA=/absolute/path/to/data
```

The mounted root should contain (or allow creation of):

- `dropzone/`
- `organized/`
- `quarantine/`
- `state.db`
