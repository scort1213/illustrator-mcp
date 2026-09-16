# Boundary hardening contract

Branch: `codex/boundary-hardening`. The tested host is Windows, Illustrator
28.6.0, Python 3.12.14. macOS retains its backend path but is not live-verified.

- `run` executes trusted JSX in a dedicated worker. Windows COM is initialized
  on that thread. An application mutex serializes different MCP clients.
  All clients must use this hardened build and the same safety directory.
  Old clients, direct scripts and manual edits do not participate in that mutex.
- `target_path` identifies an open saved document by absolute path. Multiple
  open documents without a target are rejected. The wrapper restores the
  previous interaction level even after an exception. It is not a sandbox:
  trusted JSX can explicitly switch documents or access arbitrary files.
- `timeout_seconds` is in (0,120], including queue wait. Expired queued work is
  not dispatched. Executing writes may finish after a timeout; subsequent writes
  remain blocked rather than being silently retried.
- `get_state` reports version, open document paths, saved flags and object counts.
  It also reports each placed image's path and resource status. A missing file
  can make Illustrator throw while reading `PlacedItem.file`; the snapshot
  preserves this as `missing_or_unavailable` plus the error detail instead of
  failing the entire document snapshot or claiming the link is healthy.
  After inspecting partial changes, use
  `recover_connection({"acknowledge":true})`. Recovery reads state while holding
  the application mutex and does not undo or replay a command.
- All script/capture failures use MCP `isError:true`. Normal script text that
  happens to begin with `Error:` is not itself treated as an execution exception.
- Windows JSX files live in unique owned directories and are removed on both
  normal and exceptional COM returns. Forced MCP termination can leave a
  directory behind. Explicit recovery first verifies a fresh Adobe snapshot
  under the application mutex, then removes only directories whose recorded
  owner process has exited. Live, malformed, unrelated and linked directories
  are retained. Recovery reports `removed_stale_script_directories`.
  The default root is `%TEMP%/illustrator-mcp-scripts`; an explicit
  `ILLUSTRATOR_SCRIPT_DIR` overrides it. Legacy unmarked temporary files are
  not automatically removed because their ownership cannot be established.
- `view` captures the application window. Minimized/unavailable windows report
  an error instead of falling back to the desktop. Arbitrary duplicate-window
  configurations and alternate DPI/monitor configurations are not certified.

## Reproduce the Windows environment

The direct dependency versions and `uv.lock` are pinned. `requirements.txt` is a
hash-locked export of the same dependency graph, not the former stale SDK 1.1.1
list. Do not upgrade to SDK 2 without adapting the server API and rerunning tests.

```powershell
uv sync --frozen --no-dev --python 3.12
.venv\Scripts\python.exe -m unittest discover -s tests
```

The state-script regression test executes mock Adobe objects with Node.js.
Put Node on PATH (or set ADOBE_BOUNDARY_NODE) to include it; otherwise unittest
explicitly reports that test skipped. No Node runtime is needed by the server.

Alternatively create a Python 3.12 venv, install dependencies with
`pip install --require-hashes -r requirements.txt`, then install the local project
with `pip install --no-deps -e .`. Keep Codex pointed at that venv's Python and
`-m illustrator`. Restart/reload Codex before claiming host-level acceptance.

The companion Photoshop fork contains a parameterized real-application runner
under `scripts/boundary/`. Test only dedicated copies; never run lifecycle/fault
tests while business documents are open. Unit, stdio, application and Codex-host
acceptance are separate results. A stopped stress run is not a completed pass.
