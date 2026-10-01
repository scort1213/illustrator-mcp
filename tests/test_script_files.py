import asyncio
import json
import os
import stat
from types import SimpleNamespace
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch, AsyncMock
from illustrator import script_files, server, safety


class ScriptFileTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ai-script-test-')
        self.env=patch.dict(os.environ,{'ILLUSTRATOR_SCRIPT_DIR':self.temp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop();self.temp.cleanup()

    def test_success_removes_the_owned_directory(self):
        with script_files.script_file('Chinese 中文 "quotes"') as path:
            self.assertTrue(Path(path).exists())
        self.assertEqual(list(Path(self.temp.name).iterdir()),[])

    def test_uncertain_exception_retains_source_and_reports_inspection_path(self):
        with self.assertRaisesRegex(RuntimeError, 'simulated COM failure') as caught:
            with script_files.script_file('Chinese 中文 "quotes"') as path:
                raise RuntimeError('simulated COM failure')
        directory = Path(caught.exception.inspection_path)
        self.assertEqual((directory/'script.jsx').read_text(encoding='utf-8'), 'Chinese 中文 "quotes"')
        owner = json.loads((directory/'owner.json').read_text())
        self.assertTrue(owner['inspection_required'])
        self.assertTrue(owner['completed'])
        # Explicit recovery may clean a completed retained call, while the
        # process is still alive; active call directories remain protected.
        self.assertEqual(script_files.cleanup_stale_scripts(), 1)
        self.assertFalse(directory.exists())

    def test_unique_paths_preserve_literal_source(self):
        text='Chinese 中文 U0001f9ea "quotes"\nnext'
        with script_files.script_file(text) as first, script_files.script_file(text) as second:
            self.assertNotEqual(Path(first).parent,Path(second).parent)
            self.assertEqual(Path(first).read_text(encoding='utf-8'),text)

    def test_only_owned_dead_process_directories_are_reclaimed(self):
        root=Path(self.temp.name)
        for name,owner in [('call-123-dead',{'kind':'illustrator-mcp-script','pid':123}),
                           ('call-456-live',{'kind':'illustrator-mcp-script','pid':456}),
                           ('call-123-unknown',{'kind':'other','pid':123}),
                           ('call-999-mismatch',{'kind':'illustrator-mcp-script','pid':123})]:
            path=root/name;path.mkdir();(path/'owner.json').write_text(json.dumps(owner))
        malformed=root/'call-123-malformed';malformed.mkdir();(malformed/'owner.json').write_text('{')
        with patch.object(script_files,'owner_alive',side_effect=lambda pid:pid==456):
            self.assertEqual(script_files.cleanup_stale_scripts(),1)
        self.assertEqual(len(list(root.iterdir())),4)
        self.assertFalse((root/'call-123-dead').exists())

    def test_linked_root_is_rejected(self):
        link = Path(self.temp.name) / 'linked-root'
        link.mkdir()
        canonical_link = link.resolve()
        original = os.lstat
        def lstat(path, *args, **kwargs):
            if Path(path) == canonical_link:
                return SimpleNamespace(st_mode=stat.S_IFLNK)
            return original(path, *args, **kwargs)
        with patch.dict(os.environ, {'ILLUSTRATOR_SCRIPT_DIR': str(link)}), patch('illustrator.local_paths.os.lstat', side_effect=lstat):
            with self.assertRaisesRegex(RuntimeError,'local_path_required'):
                script_files.script_root()

    def test_recovery_cleanup_requires_a_valid_adobe_snapshot(self):
        async def execute(function,**kwargs):return function(time.monotonic()+30) if kwargs.get('pass_deadline') else function()
        async def check():
            with patch.object(server,'_get_backend') as backend, patch.object(server,'cleanup_stale_scripts',return_value=2) as cleanup, patch.object(safety,'execute',new=AsyncMock(side_effect=execute)):
                backend.return_value.run_script.return_value='invalid JSON'
                result=await server.handle_call_tool('recover_connection',{'acknowledge':True})
                self.assertTrue(result.isError);cleanup.assert_not_called()
                backend.return_value.run_script.return_value='{"version":"28.6","documents":[]}'
                result=await server.handle_call_tool('get_state',{})
                self.assertFalse(result.isError);cleanup.assert_not_called()
                result=await server.handle_call_tool('recover_connection',{'acknowledge':True})
                self.assertFalse(result.isError)
                self.assertEqual(json.loads(result.content[0].text)['removed_stale_script_directories'],2)
                cleanup.assert_called_once()
        asyncio.run(check())


if __name__=='__main__':unittest.main()
