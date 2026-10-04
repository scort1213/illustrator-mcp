r"""Real Windows Illustrator acceptance through the repository's MCP stdio server.

Run with an installed project Python, with Illustrator open and NO documents open:
  .venv\Scripts\python.exe scripts\windows_acceptance.py ^
    --server-python .venv\Scripts\python.exe --workspace D:\acceptance\new-run

The workspace must not exist. All artwork is synthetic. Nothing is deleted; a
failure leaves its report, scripts, server log and artwork for inspection. This
is an opt-in real-Adobe runner, deliberately outside the unit-test suite.
Image decoding does not verify the visible artwork. Manual visual review is
required: exit code 2 means NEEDS_VISUAL_REVIEW; a failed check returns 1.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import traceback
import uuid
import xml.etree.ElementTree as ET


ENCODE_JS = r'''
function enc(v) {
 if(v===null)return 'null';
 if(typeof v==='string')return '"'+v.replace(/[\x00-\x1f"\\]/g,function(c){var h=c.charCodeAt(0).toString(16);return '\\u'+('0000'+h).slice(-4);})+'"';
 if(typeof v==='number'||typeof v==='boolean')return String(v);
 var out=[],i;
 if(v instanceof Array){for(i=0;i<v.length;i++)out.push(enc(v[i]));return '['+out.join(',')+']';}
 for(i in v){if(v.hasOwnProperty(i))out.push(enc(i)+':'+enc(v[i]));}
 return '{'+out.join(',')+'}';
}
'''


def js(value):
    return json.dumps(value, ensure_ascii=True)


def jsx(body):
    return '(function(){\n' + ENCODE_JS + '\n' + body + '\n})();'


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def same_path(first, second):
    return os.path.normcase(os.path.normpath(first)) == os.path.normcase(os.path.normpath(second))


class Acceptance:
    def __init__(self, workspace, server_python, repository):
        self.workspace = workspace
        self.python = server_python
        self.repository = repository
        self.token = 'MCP-acceptance-' + uuid.uuid4().hex
        self.main_path = workspace / 'editable-main.ai'
        self.sentinel_path = workspace / 'sentinel.ai'
        self.png_path = workspace / 'edited.png'
        self.svg_path = workspace / 'edited.svg'
        self.asset_path = workspace / 'synthetic-link.png'
        self.session = None
        self.creation_attempted = False
        self.sentinel_hash = None
        self.sentinel_snapshot = None
        self.report = {
            'schema_version': 1, 'run_id': self.token, 'started_utc': utc_now(),
            'status': 'RUNNING', 'real_adobe': True, 'transport': 'MCP stdio',
            'visual_review': 'not_performed',
            'visual_review_note': 'Manually inspect illustrator-view.jpg and the exported artwork. '
                                  'Image decoding does not verify the expected document or artwork is visible.',
            'workspace': str(workspace), 'repository': str(repository),
            'server_python': str(server_python), 'runner_python': sys.version,
            'platform': platform.platform(), 'steps': [],
            'not_tested': ['Native Codex tool reload/reconnect',
                           'Cross-client queue expiration', 'Long-running soak',
                           'Other Illustrator versions, DPI and monitor combinations',
                           'macOS execution'],
        }
        self.flush()

    def flush(self):
        (self.workspace / 'report.json').write_text(
            json.dumps(self.report, indent=2, ensure_ascii=False), encoding='utf-8')

    def record(self, name, status, **details):
        row = {'name': name, 'status': status, 'time_utc': utc_now(), **details}
        self.report['steps'].append(row)
        self.flush()
        print(f'[{status}] {name}', flush=True)
        return row

    def check(self, name, condition, **details):
        self.record(name, 'PASS' if condition else 'FAIL', **details)
        if not condition:
            raise AssertionError(name)

    async def call(self, name, tool, arguments=None, expected_error=None):
        arguments = arguments or {}
        evidence_args = dict(arguments)
        if 'code' in evidence_args:
            filename = f'{len(self.report["steps"]):03d}-{name}.jsx'
            (self.workspace / filename).write_text(evidence_args.pop('code'), encoding='utf-8')
            evidence_args['code_file'] = filename
        started = time.monotonic()
        try:
            result = await self.session.call_tool(
                tool, arguments, read_timeout_seconds=timedelta(seconds=150))
            content = []
            for item in result.content:
                if item.type == 'image':
                    content.append({'type': item.type, 'mimeType': item.mimeType,
                                    'base64_length': len(item.data)})
                else:
                    content.append(item.model_dump(mode='json', exclude_none=True))
            texts = [item.text for item in result.content if item.type == 'text']
            text = '\n'.join(texts)
            try:
                decoded = json.loads(text)
            except (ValueError, TypeError):
                decoded = text
            error_code = decoded.get('code') if isinstance(decoded, dict) else None
            good = (bool(result.isError) and error_code == expected_error
                    if expected_error else not result.isError)
            self.record(name, 'PASS' if good else 'FAIL', tool=tool,
                        arguments=evidence_args, expected_error=expected_error,
                        is_error=bool(result.isError), result=content,
                        elapsed_seconds=round(time.monotonic() - started, 3))
            if not good:
                raise AssertionError(f'{name}: unexpected MCP response: {text[:1500]}')
            return result, decoded
        except AssertionError:
            raise
        except Exception as error:
            self.record(name, 'FAIL', tool=tool, arguments=evidence_args,
                        exception=repr(error), elapsed_seconds=round(time.monotonic() - started, 3))
            raise

    async def run_js(self, name, body, target=None, timeout=30, expected_error=None):
        arguments = {'code': jsx(body), 'timeout_seconds': timeout}
        if target is not None:
            arguments['target_path'] = str(target)
        return (await self.call(name, 'run', arguments, expected_error))[1]

    async def state(self, name):
        state = (await self.call(name, 'get_state'))[1]
        if not isinstance(state, dict) or not isinstance(state.get('documents'), list):
            raise AssertionError(f'{name}: invalid state JSON')
        return state

    def main_row(self, state):
        rows = [doc for doc in state['documents'] if same_path(doc.get('path', ''), str(self.main_path))]
        if len(rows) != 1:
            raise AssertionError('Expected exactly one owned main document')
        return rows[0]

    def owned_state(self, state):
        return all(any(same_path(doc.get('path', ''), str(path))
                       for path in (self.main_path, self.sentinel_path, self.svg_path))
                   for doc in state['documents'])

    async def recover_after_inspection(self, name):
        state = await self.state(name + '-inspect')
        self.check(name + '-only-owned-documents', self.owned_state(state),
                   document_count=len(state['documents']))
        await self.call(name + '-recover', 'recover_connection', {'acknowledge': True})
        return state

    def snapshot_js(self):
        return r'''
var d=app.activeDocument, box=d.pathItems.getByName('editable-box'),
    text=d.textFrames.getByName('editable-text'), color=box.fillColor;
return enc({path:d.fullName.fsName,artboards:d.artboards.length,
 groups:d.groupItems.length,groupName:d.groupItems.getByName('editable-group').name,
 textFrames:d.textFrames.length,text:text.contents,font:text.textRange.characterAttributes.textFont.name,
 placed:d.placedItems.length,linkName:d.placedItems[0].name,
 paths:d.pathItems.length,pageItems:d.pageItems.length,
 color:[color.red,color.green,color.blue]});
'''

    async def sentinel_state(self, name):
        return await self.run_js(name, "var d=app.activeDocument;return enc({saved:d.saved,layers:d.layers.length,pageItems:d.pageItems.length,textFrames:d.textFrames.length,text:d.textFrames.getByName('sentinel-text').contents});", self.sentinel_path)

    async def workflow(self):
        from PIL import Image, ImageDraw

        initial = await self.state('initial-state')
        self.report['illustrator_version'] = initial.get('version')
        self.check('initial-no-open-documents', len(initial['documents']) == 0,
                   document_count=len(initial['documents']))
        image = Image.new('RGB', (120, 80), (30, 140, 230))
        draw = ImageDraw.Draw(image)
        draw.rectangle((12, 12, 107, 67), outline=(250, 220, 40), width=6)
        image.save(self.asset_path)
        self.record('synthetic-local-png', 'PASS', file=self.asset_path.name,
                    sha256=digest(self.asset_path), size=[120, 80])

        self.creation_attempted = True
        created = await self.run_js('create-owned-documents', f'''
var font=null,candidates=['MicrosoftYaHei','MicrosoftYaHeiUI','SimHei','SimSun'];
for(var f=0;f<candidates.length;f++){{try{{font=app.textFonts.getByName(candidates[f]);break;}}catch(e){{}}}}
if(!font)throw new Error('Required installed local Chinese font unavailable');
function save(d,path){{var o=new IllustratorSaveOptions();o.pdfCompatible=true;o.compressed=true;d.saveAs(new File(path),o);}}
var d=app.documents.add(DocumentColorSpace.RGB,640,360,1);
d.layers[0].name={js(self.token)};
d.artboards.add([700,360,1340,0]);d.artboards.setActiveArtboardIndex(0);
var group=d.groupItems.add();group.name='editable-group';
var box=group.pathItems.rectangle(320,40,260,120);box.name='editable-box';
box.stroked=false;var c=new RGBColor();c.red=40;c.green=160;c.blue=100;box.fillColor=c;
var text=d.textFrames.add();text.name='editable-text';text.contents={js('本地验收 Initial 123')};
text.position=[40,170];text.textRange.characterAttributes.size=23;
text.textRange.characterAttributes.textFont=font;
var link=d.placedItems.add();link.file=new File({js(str(self.asset_path))});
link.name='acceptance-link';link.position=[360,310];link.width=120;link.height=80;
save(d,{js(str(self.main_path))});
var sentinel=app.documents.add(DocumentColorSpace.RGB,320,180,1);
sentinel.layers[0].name={js(self.token)};
var st=sentinel.textFrames.add();st.name='sentinel-text';st.contents={js('SENTINEL / 请勿修改')};
st.position=[20,140];st.textRange.characterAttributes.textFont=font;
save(sentinel,{js(str(self.sentinel_path))});
return enc({{main:d.fullName.fsName,sentinel:sentinel.fullName.fsName,font:font.name}});
''', timeout=60)
        self.check('two-local-ai-files-created', self.main_path.is_file() and self.sentinel_path.is_file(),
                   observed=created)
        self.sentinel_hash = digest(self.sentinel_path)
        self.report['sentinel_initial_sha256'] = self.sentinel_hash
        self.sentinel_snapshot = await self.sentinel_state('sentinel-initial-memory-state')
        before = await self.run_js('snapshot-before-edit', self.snapshot_js(), self.main_path)
        edited = await self.run_js('edit-save-export', f'''
var d=app.activeDocument,box=d.pathItems.getByName('editable-box'),c=new RGBColor();
c.red=220;c.green=50;c.blue=70;box.fillColor=c;
d.textFrames.getByName('editable-text').contents={js('本地矢量编辑验收通过 Editable ABC 123')};
d.save();d.artboards.setActiveArtboardIndex(0);
var png=new ExportOptionsPNG24();png.artBoardClipping=true;png.transparency=false;
png.antiAliasing=true;png.horizontalScale=100;png.verticalScale=100;
d.exportFile(new File({js(str(self.png_path))}),ExportType.PNG24,png);
{self.snapshot_js()}
''', self.main_path, timeout=60)
        self.check('editable-artwork-structure', edited['artboards'] == 2 and edited['groups'] == 1
                   and edited['textFrames'] == 1 and edited['placed'] == 1
                   and edited['groupName'] == 'editable-group'
                   and edited['text'] == '本地矢量编辑验收通过 Editable ABC 123'
                   and all(abs(a-b) < 0.02 for a,b in zip(edited['color'], [220,50,70])),
                   before=before, after=edited)
        self.check('sentinel-file-unchanged-after-edit', digest(self.sentinel_path) == self.sentinel_hash,
                   sha256=digest(self.sentinel_path))
        self.check('png-export-exists', self.png_path.is_file())
        with Image.open(self.png_path) as exported:
            pixel = exported.convert('RGB').getpixel((80, 80))
            self.check('exported-png-dimensions-and-color', exported.size == (640,360)
                       and all(abs(a-b) <= 3 for a,b in zip(pixel, (220,50,70))),
                       dimensions=list(exported.size), sampled_rgb=list(pixel))
        await self.run_js('close-main', "app.activeDocument.close(SaveOptions.DONOTSAVECHANGES);return 'closed';", self.main_path)
        await self.run_js('reopen-main', f'app.open(new File({js(str(self.main_path))}));return "opened";', self.sentinel_path)
        reopened = await self.run_js('snapshot-after-reopen', self.snapshot_js(), self.main_path)
        self.check('saved-edit-survives-reopen', reopened == edited, observed=reopened)
        linked_state = await self.state('state-linked-item')
        links = self.main_row(linked_state).get('linked_items', [])
        self.check('linked-item-not-probed', len(links) == 1
                   and links[0].get('status') == 'not_checked' and links[0].get('path') == '',
                   observed=links)

        # Keep a failed screenshot as a real failure, while continuing the other
        # independent checks and closing only this runner's documents at the end.
        try:
            await self.run_js('redraw-before-view', "app.redraw();return 'redrawn';", self.main_path)
            await asyncio.sleep(0.5)
            viewed, _ = await self.call('view-illustrator', 'view')
            pictures = [item for item in viewed.content if item.type == 'image']
            self.check('view-returns-image', len(pictures) == 1)
            data = base64.b64decode(pictures[0].data, validate=True)
            with Image.open(io.BytesIO(data)) as screenshot:
                dimensions = list(screenshot.size)
                screenshot.verify()
            (self.workspace / 'illustrator-view.jpg').write_bytes(data)
            self.record('view-image-saved', 'PASS', file='illustrator-view.jpg', dimensions=dimensions,
                        visual_review='not_performed',
                        reason='Image decoding and saving passed; manual visual review is required.')
        except Exception as error:
            self.report['view_failure'] = repr(error)
            self.record('view-incomplete', 'FAIL', exception=repr(error))

        for name, target, expected in (
            ('invalid-target-rejected', self.workspace / 'not-open.ai', 'document_not_found'),
            ('ambiguous-target-rejected', None, 'ambiguous_document'),
        ):
            await self.run_js(name,
                "app.activeDocument.textFrames.getByName('editable-text').contents='MUST NOT EXECUTE';return 'unexpected';",
                target, expected_error=expected)
            await self.recover_after_inspection(name)
            verified = await self.run_js(name + '-verify-no-edit', self.snapshot_js(), self.main_path)
            self.check(name + '-content-preserved', verified == edited, observed=verified)

        before_timeout = self.main_row(await self.state('before-timeout-state'))
        await self.run_js('execution-timeout', r'''
var mark=app.activeDocument.pathItems.rectangle(50,40,20,20);
mark.name='timeout-observable';mark.note='started';
$.sleep(1200);mark.note='completed';return 'late-result';
''', self.main_path, timeout=0.2, expected_error='outcome_unknown')
        await self.run_js('quarantine-blocks-followup',
            "app.activeDocument.pathItems.add().name='MUST-NOT-RUN';return 'unexpected';",
            self.main_path, expected_error='outcome_unknown')
        inspected = await self.state('timeout-inspect-state')
        after_timeout = self.main_row(inspected)
        self.check('partial-timeout-write-observed-once',
                   after_timeout['page_items'] == before_timeout['page_items'] + 1,
                   before=before_timeout['page_items'], after=after_timeout['page_items'])
        self.check('timeout-inspection-only-owned-documents', self.owned_state(inspected))
        await self.call('timeout-explicit-recovery', 'recover_connection', {'acknowledge': True})
        timeout_details = await self.run_js('timeout-post-recovery-inspection', r'''
var d=app.activeDocument,count=0,blocked=0,note='';
for(var i=0;i<d.pathItems.length;i++){
 if(d.pathItems[i].name==='timeout-observable'){count++;note=d.pathItems[i].note;}
 if(d.pathItems[i].name==='MUST-NOT-RUN')blocked++;
}
return enc({count:count,note:note,blocked:blocked});
''', self.main_path)
        self.check('timeout-never-replayed-and-blocked-write-absent',
                   timeout_details == {'count':1, 'note':'completed', 'blocked':0}, observed=timeout_details)
        self.check('sentinel-file-final-hash-unchanged', digest(self.sentinel_path) == self.sentinel_hash,
                   sha256=digest(self.sentinel_path))
        sentinel_final = await self.sentinel_state('sentinel-final-memory-state')
        self.check('sentinel-memory-state-unchanged', sentinel_final == self.sentinel_snapshot,
                   before=self.sentinel_snapshot, after=sentinel_final)

        # Illustrator 28.6 may replace the active document with the outlined
        # SVG representation. Keep the native AI saved, close that export, and
        # reopen the saved AI before verifying editability again.
        await self.run_js('export-svg-outline-fonts', f'''
var d=app.activeDocument,svg=new ExportOptionsSVG();svg.embedRasterImages=true;
svg.fontType=SVGFontType.OUTLINEFONT;
d.exportFile(new File({js(str(self.svg_path))}),ExportType.SVG,svg);
return 'exported';
''', self.main_path, timeout=60)
        svg_root = ET.parse(self.svg_path).getroot()
        self.check('exported-svg-valid', svg_root.tag.endswith('svg'), bytes=self.svg_path.stat().st_size)
        svg_state = await self.state('state-after-svg-export')
        self.check('svg-export-only-owned-documents', self.owned_state(svg_state))
        export_path = self.svg_path if any(same_path(d.get('path', ''), str(self.svg_path)) for d in svg_state['documents']) else self.main_path
        await self.run_js('close-svg-export-state', "app.activeDocument.close(SaveOptions.DONOTSAVECHANGES);return 'closed';", export_path)
        await self.run_js('reopen-native-after-svg', f'app.open(new File({js(str(self.main_path))}));return "opened";', self.sentinel_path)
        native_after_svg = await self.run_js('native-snapshot-after-svg', self.snapshot_js(), self.main_path)
        self.check('native-ai-remains-editable-after-svg', native_after_svg == edited, observed=native_after_svg)
        self.report['workflow_completed'] = True

    async def cleanup_documents(self):
        if not self.creation_attempted:
            return
        try:
            # This serialized read waits for a late JSX invocation to finish.
            state = await self.state('cleanup-inspect-state')
            owned = [doc for doc in state['documents'] if any(
                same_path(doc.get('path', ''), str(path)) for path in (self.main_path, self.sentinel_path, self.svg_path))]
            if state['documents']:
                # Recovery only acknowledges the observed synthetic run. If a
                # user opened a document concurrently, leave everything alone.
                if not self.owned_state(state):
                    self.record('cleanup-stopped-unexpected-document', 'FAIL',
                                reason='A document outside this run appeared; no documents closed.')
                    return
                await self.call('cleanup-recover', 'recover_connection', {'acknowledge':True})
                target = owned[0]['path'] if owned else None
                await self.run_js('close-only-owned-documents', f'''
var paths={js([str(self.main_path), str(self.sentinel_path), str(self.svg_path)])},closed=[];
for(var i=app.documents.length-1;i>=0;i--){{
 var d=app.documents[i],p='';try{{p=d.fullName.fsName.toLowerCase();}}catch(e){{}}
 var own=false;for(var j=0;j<paths.length;j++){{if(p===new File(paths[j]).fsName.toLowerCase())own=true;}}
 if(own){{closed.push(p);d.close(SaveOptions.DONOTSAVECHANGES);}}
}}
return enc(closed);
''', target)
            final = await self.state('final-state')
            self.report['final_document_count'] = len(final['documents'])
            self.check('final-no-open-documents', len(final['documents']) == 0)
            if self.sentinel_hash and self.sentinel_path.is_file():
                self.check('sentinel-file-unchanged-after-cleanup', digest(self.sentinel_path) == self.sentinel_hash)
        except Exception as error:
            self.record('cleanup-incomplete', 'FAIL', exception=repr(error),
                        reason='Workspace retained. Inspect Illustrator and report before continuing.')

    async def execute(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        # Explicit environment additions only; the SDK provides the normal
        # platform environment without copying arbitrary credential variables.
        parameters = StdioServerParameters(
            command=str(self.python), args=['-B', '-m', 'illustrator'], cwd=str(self.repository),
            env={'ILLUSTRATOR_SAFETY_DIR': str(self.workspace / 'safety'),
                 'ILLUSTRATOR_SCRIPT_DIR': str(self.workspace / 'scripts'),
                 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUTF8': '1'})
        probe = subprocess.run([str(self.python), '-B', '-c',
            'import sys,importlib.metadata as m;print(sys.version);'
            'print("mcp="+m.version("mcp"));print("pillow="+m.version("pillow"));'
            'print("pywin32="+m.version("pywin32"))'],
            capture_output=True, text=True, timeout=15, cwd=self.repository)
        self.check('installed-server-runtime', probe.returncode == 0,
                   stdout=probe.stdout.strip(), stderr=probe.stderr.strip())
        with (self.workspace / 'server-stderr.log').open('w', encoding='utf-8') as errlog:
            async with stdio_client(parameters, errlog=errlog) as (reader, writer):
                async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=150)) as session:
                    self.session = session
                    initialized = await session.initialize()
                    self.report['server_info'] = initialized.serverInfo.model_dump(mode='json')
                    self.report['protocol_version'] = initialized.protocolVersion
                    self.report['instructions'] = initialized.instructions
                    tools = await session.list_tools()
                    self.report['tools'] = [tool.name for tool in tools.tools]
                    self.check('mcp-initialize-and-tools',
                               {'run','get_state','view','recover_connection'}.issubset(self.report['tools']),
                               tools=self.report['tools'])
                    try:
                        await self.workflow()
                    finally:
                        await self.cleanup_documents()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--workspace', required=True, type=Path, help='New dedicated directory; must not exist')
    parser.add_argument('--server-python', required=True, type=Path, help='Installed project Python executable')
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('This runner is for Windows Illustrator only')
    repository = Path(__file__).resolve().parents[1]
    python = args.server_python.resolve(strict=True)
    from illustrator.local_paths import validate_internal_path
    workspace = validate_internal_path(args.workspace.absolute())
    if workspace.exists() or workspace.is_symlink():
        parser.error('--workspace must not already exist; use a new dedicated directory')
    # Resolve only an existing parent. Do not create a hierarchy at an accidental
    # path or reuse a previous run containing artwork or an uncertainty marker.
    parent = workspace.parent.resolve(strict=True)
    workspace = parent / workspace.name
    if not python.is_file():
        parser.error('--server-python must be an installed Python executable')
    workspace.mkdir()
    acceptance = Acceptance(workspace, python, repository)
    try:
        asyncio.run(acceptance.execute())
    except Exception as error:
        acceptance.record('runner-failed', 'FAIL', exception=repr(error), traceback=traceback.format_exc())
    finally:
        failed = (not acceptance.report.get('workflow_completed', False)
                  or any(step['status'] == 'FAIL' for step in acceptance.report['steps']))
        acceptance.report['status'] = 'FAIL' if failed else 'NEEDS_VISUAL_REVIEW'
        acceptance.report['finished_utc'] = utc_now()
        acceptance.flush()
    print(f'{acceptance.report["status"]}: {workspace / "report.json"}', flush=True)
    return 1 if failed else 2


if __name__ == '__main__':
    raise SystemExit(main())
