from pathlib import Path
import json,zipfile,hashlib,subprocess,collections,ast
b=Path(r'E:\coding\code\Trade');r=b/'TradingAgents';e=b/'tradingagent-evidence'
d=json.loads((e/'rea-artifact.json').read_text(encoding='utf-8-sig'));print('Envelope',list(d));d=d.get('data',d);n=d['normalized_result']
s={'evidence_id':d['evidence_id'],'subject':d['subject'],'provider':d['provider'],'operation':d['operation'],'confidence':d.get('confidence'),'coverage':n.get('coverage'),'limitations':d.get('limitations'),'manifest':next((x.get('value') for x in n.get('observations',[]) if x.get('kind')=='root-manifest'),None)}
a=e/'source.zip';digest=hashlib.sha256(a.read_bytes()).hexdigest();s['archive_sha256_recomputed']=digest;s['hash_matches']=digest==d['subject']['digest']['sha256']
entries=subprocess.check_output(['git','ls-tree','-r','HEAD'],cwd=r,text=True).splitlines();blobs={}
for entry in entries:
 meta,name=entry.split('\t',1);blobs[name]=meta.split()[2]
exact=0;normalized=0;errors=[]
with zipfile.ZipFile(a) as z:
 names=[i.filename for i in z.infolist() if not i.is_dir()];s['zip_comment']=z.comment.decode('utf-8','replace')
 for name in names:
  payload=z.read(name)
  def githash(data):return hashlib.sha1(('blob '+str(len(data))+'\0').encode()+data).hexdigest()
  if githash(payload)==blobs.get(name):exact+=1
  elif githash(payload.replace(b'\r\n',b'\n'))==blobs.get(name):normalized+=1
  else:errors.append(name)
 s.update({'archive_files':len(names),'tracked_files':len(blobs),'path_lists_match':sorted(names)==sorted(blobs),'byte_exact_payloads':exact,'CRLF_LF_only_payloads':normalized,'unmatched_payloads':errors})
(e/'rea-summary.json').write_text(json.dumps(s,indent=2),encoding='utf-8');print(json.dumps(s,indent=2))
assert s['hash_matches'] and s['path_lists_match'] and not errors
