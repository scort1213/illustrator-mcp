import json
import os
import shutil
import subprocess
import unittest
from unittest.mock import patch
from illustrator.guard import STATE_SCRIPT, wrap


@unittest.skipUnless(shutil.which('node') or os.environ.get('ADOBE_BOUNDARY_NODE'), 'Node is required to execute the JSX state mock')
class StateResourceTests(unittest.TestCase):
    def node(self, source):
        result = subprocess.run([os.environ.get('ADOBE_BOUNDARY_NODE') or shutil.which('node'), '-e', source], capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    def test_state_reports_metadata_without_reading_any_link_file(self):
        script = r'''
const vm = require('node:vm');
const document = {name:'Chinese document', fullName:{fsName:'/local/copy.ai'}, saved:true,
 layers:[], textFrames:[], pageItems:[], artboards:[{}], placedItems:[
 {name:'local',get file(){throw new Error('must not read local file');}},
 {name:'UNC network',get file(){throw new Error('must not read network file');}},
 {name:'unavailable',get file(){throw new Error('must not inspect missing resource');}}
]};
const result=vm.runInNewContext(SOURCE,{app:{version:'30.8',documents:[document]}});
process.stdout.write(result);
'''.replace('SOURCE', json.dumps(STATE_SCRIPT))
        links = self.node(script)['documents'][0]['linked_items']
        self.assertEqual([x['name'] for x in links], ['local', 'UNC network', 'unavailable'])
        self.assertEqual([x['index'] for x in links], [0, 1, 2])
        self.assertEqual([x['status'] for x in links], ['not_checked'] * 3)
        self.assertEqual([x['path'] for x in links], [''] * 3)
        self.assertTrue(all('not probed' in x['detail'] for x in links))

    def test_all_c0_controls_quotes_backslashes_chinese_and_emoji_are_valid_json(self):
        label = ''.join(chr(i) for i in range(32)) + '"\\中文🧪'
        script = r'''
const vm=require('node:vm');
const label=LABEL;
const document={name:label,fullName:{fsName:'/local/'+label},saved:true,
 layers:[],textFrames:[],pageItems:[],artboards:[],placedItems:[{name:label}]};
process.stdout.write(vm.runInNewContext(SOURCE,{app:{version:'30.8',documents:[document]}}));
'''.replace('LABEL', json.dumps(label)).replace('SOURCE', json.dumps(STATE_SCRIPT))
        document = self.node(script)['documents'][0]
        self.assertEqual(document['name'], label)
        self.assertEqual(document['path'], '/local/' + label)
        self.assertEqual(document['linked_items'][0]['name'], label)

    def target(self, documents, target, windows=False):
        with patch('illustrator.guard.os.name', 'nt' if windows else 'posix'), patch('illustrator.guard.os.path.isabs', return_value=True):
            source = wrap('app.activeDocument.name', target)
        script = r'''
const vm=require('node:vm');
const documents=DOCUMENTS.map(row=>({name:row.name,fullName:{fsName:row.path}}));
const app={documents,userInteractionLevel:'visible',activeDocument:documents[0]};
let fileCalls=0;
const context={app,UserInteractionLevel:{DONTDISPLAYALERTS:'off'},
 File:function(path){fileCalls++;this.fsName=path}};
let result=null,error=null;
try{result=vm.runInNewContext(SOURCE,context)}catch(e){error=String(e)}
process.stdout.write(JSON.stringify({result,error,fileCalls,active:app.activeDocument.name,interaction:app.userInteractionLevel}));
'''.replace('DOCUMENTS', json.dumps(documents)).replace('SOURCE', json.dumps(source))
        return self.node(script)

    def test_mac_exact_case_selects_the_intended_document_without_file_constructor(self):
        docs = [{'name':'upper','path':'/local/A.ai'},{'name':'lower','path':'/local/a.ai'}]
        result = self.target(docs, '/local/a.ai')
        self.assertEqual(result['result'], 'lower')
        self.assertEqual(result['fileCalls'], 0)
        self.assertEqual(result['interaction'], 'visible')

    def test_mac_wrong_case_is_rejected_instead_of_editing_another_document(self):
        result = self.target([{'name':'upper','path':'/local/A.ai'}], '/local/a.ai')
        self.assertIn('document_not_found', result['error'])
        self.assertEqual(result['active'], 'upper')
        self.assertEqual(result['fileCalls'], 0)
        self.assertEqual(result['interaction'], 'visible')

    def test_windows_case_insensitive_compatibility_is_preserved(self):
        result = self.target([{'name':'upper','path':'/local/A.ai'}], '/local/a.ai', windows=True)
        self.assertEqual(result['result'], 'upper')
        self.assertEqual(result['fileCalls'], 1)


if __name__ == '__main__':
    unittest.main()
