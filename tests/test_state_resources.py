import json
import os
import shutil
import subprocess
import unittest
from illustrator.guard import STATE_SCRIPT


class StateResourceTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node') or os.environ.get('ADOBE_BOUNDARY_NODE'), 'Node is required to execute the JSX state mock')
    def test_available_missing_and_unreadable_links_are_distinguished(self):
        script = r'''
const vm = require('node:vm');
const document = {name:'Chinese document', fullName:{fsName:'D:/copy.ai'}, saved:true,
 layers:[], textFrames:[], pageItems:[], artboards:[{}], placedItems:[
 {name:'available', file:{fsName:'D:/available.png',exists:true}},
 {name:'missing', file:{fsName:'D:/missing.png',exists:false}},
 {name:'unreadable', get file(){throw new Error('There is no file associated with this item.');}}
]};
const result=vm.runInNewContext(SOURCE,{app:{version:'28.6',documents:[document]}});
process.stdout.write(result);
'''.replace('SOURCE', json.dumps(STATE_SCRIPT))
        result = subprocess.run([os.environ.get('ADOBE_BOUNDARY_NODE') or shutil.which('node'), '-e', script], capture_output=True, text=True, check=True)
        state = json.loads(result.stdout)
        links = state['documents'][0]['linked_items']
        self.assertEqual([x['status'] for x in links], ['available', 'missing', 'missing_or_unavailable'])
        self.assertIn('no file associated', links[2]['detail'])
        self.assertEqual(links[2]['path'], '')


if __name__ == '__main__':
    unittest.main()
