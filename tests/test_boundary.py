import asyncio
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch, AsyncMock
from illustrator import safety, server
from illustrator.guard import wrap

class BoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ai-boundary-')
        self.env=patch.dict(os.environ,{'ILLUSTRATOR_SAFETY_DIR':self.temp.name});self.env.start()
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
        code=wrap('1',r'C:\测试\a"b.ai')
        self.assertIn('ambiguous_document',code);self.assertIn('finally',code)
    async def test_literal_error_text_is_not_an_execution_error(self):
        with patch.object(safety,'execute',new=AsyncMock(return_value='Error: literal content')):
            result=await server.handle_call_tool('run',{'code':'"Error: literal content";'})
            self.assertFalse(result.isError)
