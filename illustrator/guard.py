"""Trusted JSX wrapper. Target checks are not a sandbox for arbitrary scripts."""
import json
import os

STATE_SCRIPT = r'''(function(){
 function q(s){return '"'+String(s).replace(/\\/g,'\\\\').replace(/"/g,'\\"').replace(/\r/g,'\\r').replace(/\n/g,'\\n').replace(/\t/g,'\\t')+'"';}
 var rows=[];
 for(var i=0;i<app.documents.length;i++){
  var d=app.documents[i],p='';try{p=d.fullName.fsName;}catch(e){}
  rows.push('{"name":'+q(d.name)+',"path":'+q(p)+',"saved":'+d.saved+',"layers":'+d.layers.length+',"text_frames":'+d.textFrames.length+',"page_items":'+d.pageItems.length+',"artboards":'+d.artboards.length+'}');
 }
 return '{"version":'+q(app.version)+',"documents":['+rows.join(',')+']}';
})();'''

def wrap(code, target_path=None):
    if not isinstance(code, str) or not code.strip():
        raise ValueError("invalid_argument: code must be a non-empty string")
    if target_path is not None and (not isinstance(target_path, str) or not target_path.strip() or not os.path.isabs(target_path)):
        raise ValueError("invalid_argument: target_path must be a non-empty absolute file path")
    return '''(function(){
var before=app.userInteractionLevel;
try {
 app.userInteractionLevel=UserInteractionLevel.DONTDISPLAYALERTS;
 var target=%s;
 if(target!==null){
  var expected=new File(target).fsName.toLowerCase(),found=null;
  for(var i=0;i<app.documents.length;i++){try{if(app.documents[i].fullName.fsName.toLowerCase()===expected){if(found)throw new Error('ambiguous_document');found=app.documents[i];}}catch(e){if(String(e).indexOf('ambiguous_document')>=0)throw e;}}
  if(!found)throw new Error('document_not_found: target_path is not open');
  app.activeDocument=found;
 }else if(app.documents.length>1)throw new Error('ambiguous_document: supply target_path');
 return eval(%s);
}finally{app.userInteractionLevel=before;}
})();''' % (json.dumps(target_path), json.dumps(code))
