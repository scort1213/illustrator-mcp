"""Local-operation guidance for MCP clients; this is not a script sandbox."""

LOCAL_ONLY_INSTRUCTIONS = """LOCAL OPERATION POLICY:
Use this MCP server only for local Illustrator work, using documents, files,
assets and fonts already available on the computer. Keep normal local editing,
local file open/save/export and trusted ExtendScript workflows available.
Do not invoke Adobe cloud services: Firefly, generative AI features, cloud
documents, online asset searches/downloads, or online font activation/downloads.
Do not open a browser for sign-in, start OAuth or online account verification,
or make network requests from ExtendScript, sockets or external commands.
If a local feature, file, asset or font is unavailable, report the limitation;
do not switch to a cloud service or start a login flow as a fallback.
Adobe's own licensing and background networking, and the AI client's accounts
and services, are outside this MCP task policy.
These instructions guide the calling assistant. Trusted JSX is still executed
without a sandbox; the server does not filter or block arbitrary scripts.
"""
