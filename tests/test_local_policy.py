"""Verify client guidance without starting or scripting an Adobe application."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from illustrator import prompt, server
from illustrator.local_policy import LOCAL_ONLY_INSTRUCTIONS


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TOOLS = {
    "get_state", "recover_connection", "view", "run", "get_prompt_suggestions",
    "get_system_prompt", "get_prompting_tips", "get_advanced_template", "help",
}


class LocalPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_stdio_handshake_delivers_policy_and_keeps_all_tools(self):
        # Fail the child if normal MCP handshake/prompt reads attempt a network connection.
        bootstrap = (
            'import asyncio, sys; '
            'sys.addaudithook(lambda event, args: '
            '(_ for _ in ()).throw(RuntimeError("Network connection attempted")) '
            'if event in ("socket.connect", "socket.getaddrinfo") else None); '
            'from illustrator.server import main; asyncio.run(main())'
        )
        params = StdioServerParameters(
            command=sys.executable, args=["-c", bootstrap], cwd=PROJECT_ROOT,
        )
        async with asyncio.timeout(15):
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    initialized = await session.initialize()
                    self.assertEqual(initialized.instructions, LOCAL_ONLY_INSTRUCTIONS)
                    tools = (await session.list_tools()).tools
                    self.assertEqual({tool.name for tool in tools}, EXPECTED_TOOLS)
                    run = next(tool for tool in tools if tool.name == "run")
                    self.assertIn("not sandboxed", run.description)
                    self.assertIn("never fall back to cloud", run.description)
                    self.assertEqual(set(run.inputSchema["properties"]), {
                        "code", "target_path", "timeout_seconds",
                    })
                    result = await session.call_tool("get_system_prompt", {})
                    self.assertFalse(result.isError)
                    self.assertIn(LOCAL_ONLY_INSTRUCTIONS, result.content[0].text)
                    template = await session.call_tool("get_advanced_template", {
                        "template_type": "illustration",
                    })
                    self.assertIn(LOCAL_ONLY_INSTRUCTIONS, template.content[0].text)

    async def test_run_preserves_arbitrary_trusted_jsx_without_an_adobe_backend(self):
        # The mock receives the script; no JSX, network request or Adobe call runs.
        code = 'function f(){return eval("2 + 3");} var label="Firefly"; f();'
        backend = Mock()
        backend.run_script.return_value = "5"
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"ILLUSTRATOR_SAFETY_DIR": directory}):
                with patch.object(server, "_get_backend", return_value=backend):
                    result = await server.handle_call_tool("run", {"code": code})
        self.assertFalse(result.isError)
        self.assertEqual(result.content[0].text, "5")
        backend.run_script.assert_called_once()
        self.assertIn(json.dumps(code), backend.run_script.call_args.args[0])

    async def test_prompt_surfaces_repeat_local_guidance(self):
        self.assertIn(LOCAL_ONLY_INSTRUCTIONS, prompt.get_system_prompt())
        self.assertIn(LOCAL_ONLY_INSTRUCTIONS, prompt.display_help())
        for template in prompt.get_advanced_templates().values():
            self.assertIn(LOCAL_ONLY_INSTRUCTIONS, template)
        for name, arguments in (
            ("get_prompt_suggestions", {}),
            ("get_prompt_suggestions", {"category": "logos"}),
        ):
            result = await server.handle_call_tool(name, arguments)
            self.assertIn(LOCAL_ONLY_INSTRUCTIONS, result.content[0].text)

    @unittest.skipUnless(shutil.which("bash"), "Bash is required for launcher stdio verification")
    async def test_real_launcher_stdio_handshake(self):
        params = StdioServerParameters(
            command=shutil.which("bash"), args=[str(PROJECT_ROOT / "run_server.sh")], cwd=PROJECT_ROOT,
        )
        async with asyncio.timeout(15):
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    initialized = await session.initialize()
                    self.assertEqual(initialized.instructions, LOCAL_ONLY_INSTRUCTIONS)
                    self.assertEqual({tool.name for tool in (await session.list_tools()).tools}, EXPECTED_TOOLS)


@unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "Bash launcher checks require POSIX bash")
class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="illustrator-launcher-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.launcher = self.root / "run_server.sh"
        shutil.copyfile(PROJECT_ROOT / "run_server.sh", self.launcher)

    def launch(self):
        return subprocess.run(
            [shutil.which("bash"), str(self.launcher)], cwd=self.root,
            capture_output=True, text=True, timeout=10,
        )

    def fake_python(self, check_status):
        interpreter = self.root / ".venv" / "bin" / "python3"
        interpreter.parent.mkdir(parents=True)
        log = self.root / "calls.txt"
        interpreter.write_text(
            '#!/usr/bin/env bash\n'
            f'printf "%s\\n" "$*" >> "{log}"\n'
            'if [[ "$1" == "-" ]]; then\n'
            '  cat >/dev/null\n'
            f'  exit {check_status}\n'
            'fi\n'
            'printf "server-output\\n"\n',
            encoding="utf-8",
        )
        interpreter.chmod(0o755)
        return log

    def test_missing_environment_stops_without_creating_or_downloading(self):
        result = self.launch()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("will not download", result.stderr)
        self.assertFalse((self.root / ".venv").exists())

    def test_failed_dependency_check_does_not_install_or_start(self):
        log = self.fake_python(1)
        result = self.launch()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(log.read_text().splitlines(), ["-"])
        self.assertEqual(result.stdout, "")
        self.assertIn("Nothing was installed or upgraded", result.stderr)

    def test_valid_environment_starts_with_clean_protocol_stdout(self):
        log = self.fake_python(0)
        result = self.launch()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(log.read_text().splitlines(), ["-", str(self.root / "illustrator" / "server.py")])
        self.assertEqual(result.stdout, "server-output\n")
        self.assertIn("Starting Illustrator MCP", result.stderr)


if __name__ == "__main__":
    unittest.main()
