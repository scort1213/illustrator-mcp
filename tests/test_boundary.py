import asyncio
import os
import subprocess
import threading
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch, AsyncMock
from illustrator import safety, server, script_files
from illustrator.guard import wrap

class BoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ai-boundary-')
        self.env=patch.dict(os.environ,{'ILLUSTRATOR_SAFETY_DIR':self.temp.name,'ILLUSTRATOR_SCRIPT_DIR':self.temp.name});self.env.start()
    async def asyncTearDown(self):
        await asyncio.sleep(.2);self.env.stop();self.temp.cleanup()
    async def test_expired_queue_never_executes_and_unknown_outcome_blocks_writes(self):
        calls=[]
        def slow():calls.append('slow');time.sleep(.15);return 'done'
        first=asyncio.create_task(safety.execute(slow,timeout=.06))
        await asyncio.sleep(.02)
        second=asyncio.create_task(safety.execute(lambda:calls.append('late'),timeout=.02))
        with self.assertRaisesRegex(TimeoutError,'queue_timeout'):await second
        with self.assertRaisesRegex(TimeoutError,'outcome_unknown'):await first
        await asyncio.sleep(.2)
        self.assertEqual(calls,['slow'])
        with self.assertRaisesRegex(RuntimeError,'outcome_unknown'):await safety.execute(lambda:'write')
        self.assertEqual(await safety.execute(lambda:'state',read_only=True),'state')
        await safety.execute(lambda:'checked',read_only=True,recover=True)
        self.assertEqual(await safety.execute(lambda:'write'),'write')
    async def test_partial_failure_requires_inspection(self):
        def partial():raise RuntimeError('partial change')
        with self.assertRaisesRegex(RuntimeError,'partial change'):await safety.execute(partial)
        with self.assertRaisesRegex(RuntimeError,'outcome_unknown'):await safety.execute(lambda:'retry')
    async def test_deadline_during_marker_publication_never_dispatches(self):
        calls=[]
        original=Path.write_text
        def slow_write(path, *args, **kwargs):
            time.sleep(.12)
            return original(path, *args, **kwargs)
        with patch.object(Path, 'write_text', slow_write):
            with self.assertRaisesRegex(TimeoutError,'queue_timeout'):
                await safety.execute(lambda:calls.append('late'), timeout=.03)
            await asyncio.sleep(.2)
        self.assertEqual(calls, [])
        self.assertFalse(safety.marker().exists())
        self.assertEqual(await safety.execute(lambda:'next'), 'next')
    async def test_mcp_failures_are_marked_as_errors(self):
        for name,args in [('run',{}),('run',{'code':''}),('recover_connection',{'acknowledge':False})]:
            result=await server.handle_call_tool(name,args);self.assertTrue(result.isError)
        with patch.object(server,'_get_backend') as backend:
            backend.return_value.capture_screenshot.side_effect=RuntimeError('capture failed')
            self.assertTrue((await server.handle_call_tool('view',{})).isError)
    async def test_empty_script_rejected_and_path_literals_escaped(self):
        with self.assertRaises(ValueError):wrap('')
        with self.assertRaises(ValueError):wrap('1','relative.ai')
        target = r'C:\测试\a"b.ai' if os.name == 'nt' else '/tmp/测试/a"b.ai'
        code=wrap('1',target)
        self.assertIn('ambiguous_document',code);self.assertIn('finally',code)
    async def test_literal_error_text_is_not_an_execution_error(self):
        with patch.object(safety,'execute',new=AsyncMock(return_value='Error: literal content')):
            result=await server.handle_call_tool('run',{'code':'"Error: literal content";'})
            self.assertFalse(result.isError)

    async def test_absolute_deadline_includes_time_spent_in_queue(self):
        def slow():time.sleep(.08)
        first = asyncio.create_task(safety.execute(slow, timeout=1, read_only=True))
        await asyncio.sleep(.02)
        observed = []
        def next_call(deadline):
            observed.append(deadline - time.monotonic())
            return 'done'
        result = await safety.execute(next_call, timeout=.8, read_only=True, pass_deadline=True)
        await first
        self.assertEqual(result, 'done')
        self.assertGreater(observed[0], 0)
        self.assertLess(observed[0], .79)

    async def test_subprocess_timeout_preserves_unknown_write_until_recovery(self):
        def timed_out():raise subprocess.TimeoutExpired('mock osascript', 120)
        with self.assertRaisesRegex(TimeoutError, 'outcome_unknown'):
            await safety.execute(timed_out)
        self.assertTrue(safety.marker().exists())
        with self.assertRaisesRegex(RuntimeError, 'outcome_unknown'):
            await safety.execute(lambda:'must not execute')
        await safety.execute(lambda:'state', read_only=True, recover=True)
        self.assertFalse(safety.marker().exists())

    async def test_read_only_subprocess_timeout_does_not_quarantine_writes(self):
        def timed_out():raise subprocess.TimeoutExpired('mock osascript', 30)
        with self.assertRaisesRegex(TimeoutError, 'execution_timeout'):
            await safety.execute(timed_out, read_only=True)
        self.assertFalse(safety.marker().exists())

    async def test_worker_late_return_without_event_loop_timeout_keeps_write_quarantined(self):
        paths = []
        # Mock only the safety-layer clock, leaving asyncio's timeout clock real.
        # The worker finishes immediately in real time, after its fake deadline.
        with patch.object(safety, 'time') as clock:
            clock.monotonic.return_value = 100
            def late(deadline):
                with script_files.script_file('late synthetic source') as path:
                    paths.append(Path(path).parent)
                    clock.monotonic.return_value = deadline + 1
                return 'must not be reported as success'
            with self.assertRaisesRegex(TimeoutError, 'outcome_unknown') as caught:
                await safety.execute(late, timeout=1, pass_deadline=True)
        self.assertEqual(Path(caught.exception.inspection_path), paths[0])
        self.assertTrue((paths[0]/'script.jsx').exists())
        self.assertTrue(safety.marker().exists())
        with self.assertRaisesRegex(RuntimeError, 'outcome_unknown'):
            await safety.execute(lambda:'must not execute')

    async def test_worker_late_read_and_recovery_fail_without_clearing_marker(self):
        for recover in (False, True):
            with self.subTest(recover=recover):
                if recover:
                    safety.marker().write_text('existing unknown write', encoding='utf-8')
                with patch.object(safety, 'time') as clock:
                    clock.monotonic.return_value = 100
                    def late(deadline):
                        clock.monotonic.return_value = deadline + 1
                        return 'must not be reported as success'
                    with self.assertRaisesRegex(TimeoutError, 'execution_timeout'):
                        await safety.execute(late, timeout=1, read_only=True,
                                             recover=recover, pass_deadline=True)
                self.assertEqual(safety.marker().exists(), recover)

    @unittest.skipIf(os.name == 'nt', 'Physical POSIX symlink fixture; Windows reparse points are mocked separately')
    async def test_dangling_marker_link_cannot_write_outside_safety_root(self):
        outside = Path(self.temp.name) / 'outside-new.txt'
        (Path(self.temp.name) / 'uncertain.txt').symlink_to(outside)
        calls = []
        with self.assertRaisesRegex(RuntimeError, 'local_path_required'):
            await safety.execute(lambda:calls.append('unexpected'))
        self.assertEqual(calls, [])
        self.assertFalse(outside.exists())

    async def retained_late_script(self, cancel=False):
        started = threading.Event()
        finished = threading.Event()
        paths = []
        def late():
            with script_files.script_file('synthetic source retained for inspection') as path:
                paths.append(Path(path).parent)
                started.set()
                time.sleep(.18)
            finished.set()
            return 'late success'
        task = asyncio.create_task(safety.execute(late, timeout=1 if cancel else .1))
        while not started.is_set():
            await asyncio.sleep(.005)
        if cancel:
            task.cancel()
        with self.assertRaisesRegex(TimeoutError, 'outcome_unknown') as caught:
            await task
        directory = Path(caught.exception.inspection_path)
        self.assertEqual(directory, paths[0])
        self.assertTrue((directory/'script.jsx').exists())
        self.assertEqual(script_files.cleanup_stale_scripts(), 0, 'active calls must not be reclaimed')
        while not finished.is_set():
            await asyncio.sleep(.01)
        self.assertTrue((directory/'script.jsx').exists(), 'late success must not delete inspection source')
        self.assertTrue(safety.marker().exists())
        with patch.object(server, '_get_backend') as backend:
            backend.return_value.run_script.return_value = '{"version":"30.8.1","documents":[]}'
            result = await server.handle_call_tool('recover_connection', {'acknowledge':True})
        self.assertFalse(result.isError)
        self.assertEqual(json.loads(result.content[0].text)['removed_stale_script_directories'], 1)
        self.assertFalse(directory.exists())
        self.assertFalse(safety.marker().exists())

    async def test_timeout_retains_script_after_late_normal_return_until_recovery(self):
        await self.retained_late_script()

    async def test_cancellation_retains_script_after_late_normal_return_until_recovery(self):
        await self.retained_late_script(cancel=True)

    async def test_mcp_uncertain_failure_includes_inspection_path(self):
        class Backend:
            def run_script(self, code, **kwargs):
                with script_files.script_file(code):
                    raise subprocess.TimeoutExpired('mock osascript', 30)
        with patch.object(server, '_get_backend', return_value=Backend()):
            result = await server.handle_call_tool('run', {'code':'42'})
        self.assertTrue(result.isError)
        response = json.loads(result.content[0].text)
        self.assertEqual(response['code'], 'outcome_unknown')
        self.assertTrue((Path(response['inspection_path'])/'script.jsx').exists())
