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

- `BATCH_REVIEW_ENABLED` (`true`/`false`)  
  Enables post-batch refinement review after batch processing completes
  (default `true`).

- `BATCH_REVIEW_MODEL`  
  Reviewer model name, default `kimi-k2.6`.

- `BATCH_REVIEW_QUIET_SECONDS`  
  In watch mode, minimum quiet window with no new stable events before a
  batch is considered complete and reviewed.

- `BATCH_REVIEW_MAX_ACTIONS`  
  Maximum number of reviewer tool actions allowed per batch.

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

## Post-batch reviewer behavior

- After a batch completes, reviewer input includes:
  - upload batch tree,
  - full updated destination tree tagged with newly inserted files/folders,
  - move history for that batch.

- Reviewer tools:
  - read move history,
  - create folder,
  - retry item (move back to dropzone),
  - move item to existing folder.

- Reviewer tool actions are tracked in SQLite move history and included in
  batch summaries.

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
