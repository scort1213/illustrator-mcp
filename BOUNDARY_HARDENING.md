# Boundary hardening contract

Branch: `codex/boundary-hardening`. The tested host is Windows, Illustrator
28.6.0, Python 3.12.14. The `codex/local-only` branch also has one macOS local
workflow smoke test on Illustrator 30.8.1; it does not replace the full historical
Windows acceptance or certify macOS screenshot/multi-window behavior.

The `codex/local-only` branch adds client guidance to use only local operations.
The policy is delivered in the MCP initialization response, the `run` tool
description and design prompts. It forbids requesting Adobe cloud/Firefly/
generative features, cloud documents, online assets/font activation, browser
login and network commands; unavailable local capabilities must be reported
without a cloud fallback. It preserves all tools and arbitrary trusted JSX.
It is not a sandbox, script filter or network firewall. Adobe's own licensing
and background networking, and the AI client's services, are outside the policy.
Normal startup does not download or install dependencies; installation is an
explicit separate step. See `ACCEPTANCE_ZH.md` for verified and pending checks.

- `run` executes trusted JSX in a dedicated worker. Windows COM is initialized
  on that thread. An application mutex serializes different MCP clients.
  All clients must use this hardened build and the same safety directory.
  Old clients, direct scripts and manual edits do not participate in that mutex.
- `target_path` identifies an open saved document by absolute path. Multiple
  open documents without a target are rejected. The wrapper restores the
  previous interaction level even after an exception. It is not a sandbox:
  trusted JSX can explicitly switch documents or access arbitrary files.
  macOS compares the exact path returned by `get_state`, without a File
  constructor or filesystem probe; Windows preserves its case-insensitive
  normalization. An incorrect case on macOS is rejected rather than guessed.
- `timeout_seconds` is in (0,120], including queue wait. Expired queued work is
  not dispatched. Executing writes may finish after a timeout; subsequent writes
  remain blocked rather than being silently retried.
  The same absolute deadline is passed into the backend. macOS subprocesses
  receive the remaining budget, not a separate fixed 30-second limit. Backend
  construction no longer dispatches a version probe. Killing osascript does not
  prove the JSX stopped inside Adobe; a timed-out write remains `outcome_unknown`.
- `get_state` reports version, open document paths, saved flags and object counts.
  It reports each placed item's index and name, with `path:""` and
  `status:"not_checked"`. It does not read `PlacedItem.file` or `File.exists`:
  even a state query must not probe a linked network resource. `not_checked`
  makes no claim that a resource is healthy or missing. String serialization
  escapes all C0 controls, quotes and backslashes without requiring a JSX JSON
  library.
  After inspecting partial changes, use
  `recover_connection({"acknowledge":true})`. Recovery reads state while holding
  the application mutex and does not undo or replay a command.
- All script/capture failures use MCP `isError:true`. Normal script text that
  happens to begin with `Error:` is not itself treated as an execution exception.
- Windows and macOS JSX files live in unique owned directories. Normal successful
  calls remove their directory; exceptions, cancellation and timeout retain the
  source for inspection. A late successful worker return after its deadline also
  retains the source. Errors report `inspection_path` when one was created.
  Forced MCP termination can likewise leave a directory behind. Explicit recovery
  first verifies a fresh Adobe snapshot under the application mutex, then removes
  only owned directories whose owner exited or whose call completed with a recorded
  inspection requirement. The latter permits recovery in the same live MCP process;
  an actively running call has no completed marker and is not reclaimed. Malformed,
  unrelated and linked directories are retained. Recovery reports
  `removed_stale_script_directories`.
  The default root is `~/.illustrator-mcp/scripts`; an explicit
  `ILLUSTRATOR_SCRIPT_DIR` overrides it. Legacy unmarked temporary files are
  not automatically removed because their ownership cannot be established.
- Internal safety and screenshot storage use `~/.illustrator-mcp/safety` and
  `~/.illustrator-mcp/preview`, independent of TEMP/TMPDIR. The existing
  `ILLUSTRATOR_SAFETY_DIR` override remains available. An absolute local path,
  known local drive/filesystem and each link component are checked before mkdir.
  Before establishing stdio, startup validates the package installation directory,
  Python executable and all three configured storage roots without creating them
  or contacting Adobe. A Python executable symlink is permitted only after its
  resolved destination passes the local filesystem checks.
  Link destinations are classified before being inspected; network/unknown
  destinations and final-component links are rejected. Recovery also retains
  owned trees containing links or unverified mounts. Mount information is cached
  for one tool operation only. These checks do not sandbox user JSX paths.
  Reload every client together and inspect state before upgrading writes; legacy
  TEMP roots are not migrated automatically and do not share the new default lock.
- `view` captures the application window. Minimized/unavailable windows report
  an error instead of falling back to the desktop. Arbitrary duplicate-window
  configurations and alternate DPI/monitor configurations are not certified.
  The Windows audit branch also rejects the observed near-uniform dark-gray
  unrendered capture. This is a conservative heuristic, not proof of correct
  rendering; deliberately uniform gray artwork may be rejected. Explicit local
  artboard PNG export is the verified preview path on the current audited host.

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
