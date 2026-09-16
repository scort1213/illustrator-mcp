import asyncio
import json
import os
from pathlib import Path
import tempfile
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

    def test_success_and_exception_both_remove_the_owned_directory(self):
        for fail in (False,True):
            with self.subTest(fail=fail):
                try:
                    with script_files.script_file('Chinese 中文 "quotes"') as path:
                        self.assertTrue(Path(path).exists())
                        if fail:raise RuntimeError('simulated COM failure')
                except RuntimeError:
                    pass
                self.assertEqual(list(Path(self.temp.name).iterdir()),[])

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
        with patch.object(Path,'is_symlink',return_value=True):
            with self.assertRaisesRegex(RuntimeError,'unsafe_script_directory'):
                script_files.script_root()

    def test_recovery_cleanup_requires_a_valid_adobe_snapshot(self):
        async def execute(function,**kwargs):return function()
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
