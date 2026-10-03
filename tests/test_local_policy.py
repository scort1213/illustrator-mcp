"""Verify client guidance without starting or scripting an Adobe application."""
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

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
    async def test_runtime_paths_are_validated_before_stdio_and_without_adobe(self):
        events = []
        @asynccontextmanager
        async def streams():
            events.append('stdio')
            yield 'read', 'write'
        def validate(*args):
            events.append('validate')
        async def run(*args):
            events.append('run')
        with patch.object(server, 'validate_runtime_paths', side_effect=validate) as check, patch('mcp.server.stdio.stdio_server', streams), patch.object(server.server, 'run', new=AsyncMock(side_effect=run)), patch.object(server, '_get_backend') as backend, patch.object(Path, 'mkdir') as mkdir:
            await server.main()
        self.assertEqual(events, ['validate', 'stdio', 'run'])
        check.assert_called_once_with(str(Path(server.__file__).absolute().parent), sys.executable)
        backend.assert_not_called(); mkdir.assert_not_called()

    async def test_unsafe_startup_storage_fails_before_stdio_mkdir_or_adobe(self):
        with tempfile.TemporaryDirectory(prefix='ai-startup-') as directory:
            environment = {'ILLUSTRATOR_SCRIPT_DIR':'//example.invalid/share',
                           'ILLUSTRATOR_SAFETY_DIR': directory}
            with patch.dict(os.environ, environment), patch('mcp.server.stdio.stdio_server') as streams, patch.object(server, '_get_backend') as backend, patch.object(Path, 'mkdir') as mkdir:
                with self.assertRaisesRegex(RuntimeError, 'local_path_required'):
                    await server.main()
                streams.assert_not_called(); backend.assert_not_called(); mkdir.assert_not_called()

    async def test_real_stdio_handshake_delivers_policy_and_keeps_all_tools(self):
        # Fail the child if normal MCP handshake/prompt reads attempt a network connection.
        # Windows' event loop creates a loopback socket pair during construction.
        # Construct that infrastructure first, then audit all server startup/tool work.
        bootstrap = (
            'import asyncio, sys; loop = asyncio.new_event_loop(); '
            'sys.addaudithook(lambda event, args: '
            '(_ for _ in ()).throw(RuntimeError("Network connection attempted")) '
            'if event in ("socket.connect", "socket.getaddrinfo") else None); '
            'from illustrator.server import main; loop.run_until_complete(main()); loop.close()'
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

    async def test_requested_long_timeout_flows_through_real_server_and_mac_backend(self):
        from illustrator.platform_backend import MacBackend
        backend = MacBackend.__new__(MacBackend)
        backend._APP_NAME = 'Adobe Illustrator'
        with tempfile.TemporaryDirectory(prefix='ai-full-deadline-') as directory:
            environment = {'ILLUSTRATOR_SAFETY_DIR': directory, 'ILLUSTRATOR_SCRIPT_DIR': directory}
            with patch.dict(os.environ, environment), patch.object(server, '_get_backend', return_value=backend), patch('illustrator.local_paths._assert_mounted_locally'), patch('illustrator.platform_backend.subprocess.run') as child:
                child.return_value = Mock(returncode=0, stdout='42', stderr='')
                result = await server.handle_call_tool('run', {'code':'42', 'timeout_seconds':120})
                self.assertFalse(result.isError)
                self.assertEqual(result.content[0].text, '42')
                self.assertEqual(child.call_count, 1)
                self.assertGreater(child.call_args.kwargs['timeout'], 100)
                self.assertLessEqual(child.call_args.kwargs['timeout'], 120)

    @unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "POSIX Bash is required for launcher stdio verification")
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
