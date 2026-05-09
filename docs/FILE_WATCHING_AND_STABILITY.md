# File Watching and Stability Logic

This document explains how `files-ai` detects new dropzone content and waits
for writes to settle before processing.

## High-level flow

`src/files_ai/__main__.py` creates a `StableFileWatcher` and runs:

1. A startup pass over direct children in `DROPZONE`.
2. Continuous watch mode (unless `--once`) using event batches separated by a
   quiet window.

Both paths route refs through `_process_ref(...)`, which skips ignored names,
handles directories separately, and only processes files after a stability
check.

## Backend watch source

`LocalFiles.watch(...)` (in `src/files_ai/storage/local.py`) uses
`watchdog.observers.polling.PollingObserver` with `poll_interval_seconds` from
 settings. Raw watchdog callbacks are normalized into `FileEvent` records and
queued.

Event kinds emitted by the backend include `created`, `modified`, `deleted`,
and `moved`.

## StableFileWatcher behavior

`StableFileWatcher` (in `src/files_ai/watcher.py`) adds filtering and
debouncing on top of backend events.

### 1) Event filtering

`iter_stable_events(...)` keeps only:

- `created`
- `modified`
- `moved`

`deleted` is ignored because the target no longer exists to process.

### 2) Skip rules

`should_skip(...)` ignores names with:

- prefixes: `"."`, `"~$"`
- suffixes: `".tmp"`, `".crdownload"`

Special case: `.git` is explicitly **not** skipped.

### 3) Existence/type gate

For each candidate event ref:

- skip if it no longer exists,
- if it is a directory and `include_directories=True`, yield immediately,
- otherwise require file stability.

### 4) Stability check

`is_stable(ref)` does:

1. `stat` and read size (must exist and be a file),
2. sleep `stabilize_seconds` (default `1.0`),
3. `stat` again (must still exist and be a file),
4. treat as stable only if size is unchanged.

This prevents processing partially written files.

## Batch splitting in watch mode

`iter_stable_event_batches(...)` runs `iter_stable_events(...)` in a producer
thread and groups stable refs into batches.

- If no batch is active, it polls the queue quickly (`0.25s`).
- Once a batch has items, it waits up to `quiet_seconds` for the next stable
  item.
- If that timeout expires, the batch is yielded.

`quiet_seconds` comes from `WATCH_QUIET_SECONDS` and defines the "batch is
done" quiet window.

Before yielding, refs are deduped by path (`_dedupe_refs`) while preserving the
first-seen order and keeping the latest ref object per path.

## How startup differs from watch mode

- Startup uses `iterdir(dropzone)` (direct children only), then directory
  recursion is handled by folder logic if needed.
- Watch mode is recursive from the backend observer and event-driven.
- File stability checks are applied in both paths before file processing.

## Shutdown behavior

Signal handlers call `watcher.stop()`, which delegates to
`Files.stop_watch()` (`LocalFiles.stop_watch()` stops and joins the observer
thread). A final stop also runs in `finally` during shutdown.
