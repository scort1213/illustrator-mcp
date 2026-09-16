# Windows and Codex setup

This fork's `codex/windows-setup` branch was verified on Illustrator 2024
(28.6.0), Python 3.12, MCP SDK 1.30.0, Pillow 12.3.0 and pywin32 312.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
codex mcp add illustrator --env PYTHONIOENCODING=utf-8 --env PYTHONUTF8=1 -- C:\absolute\path\illustrator-mcp\.venv\Scripts\python.exe -m illustrator
```

Restart Codex after adding the server. The server starts automatically with
its MCP client; no separate terminal needs to remain open.

Local fixes:

- Keep the MCP SDK below version 2 because this server uses the 1.x handler API.
- Capture the Illustrator window by handle instead of the whole desktop, so
  overlapping application windows do not hide the artwork in `view` results.
- Require Pillow 11.2.1+ for window-targeted Windows capture.

Verified over the real MCP stdio transport: tool discovery (7 tools), host
version query, editable paths and Chinese text, AI save/reopen, PNG export,
and window screenshot with an overlapping client window. The 19 unit tests
also pass. A minimized Illustrator window must be restored before `view`.
