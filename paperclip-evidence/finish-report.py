from pathlib import Path
import json,re,hashlib,subprocess,zipfile,collections,datetime
b=Path(r'E:\coding\code\Trade');e=b/'paperclip-evidence';r=b/'paperclip';sha='9de343b3fe2e2d4dc84fc8386d9ce04d553f39d6'
def read(p):return p.read_text(encoding='utf-8-sig')
inv=json.loads(read(e/'source-inventory.json'));known={x['path']:x for x in inv};summary=json.loads(read(e/'inventory-summary.json'))
def link(p,n=1):return f'[{p}:{n}](https://github.com/paperclipai/paperclip/blob/{sha}/{p}#L{n})'
parts=[read(e/'overview.md')]
for title,name in [('Backend, data model aur governance','backend-notes.md'),('Agent execution, adapters aur runtime','runtime-notes.md'),('UI, CLI, onboarding aur app connections','surfaces-notes.md')]:
 s=read(e/name); start=s.find('\n## ');s=s[start:] if start>=0 else s
 s=re.sub(r'^(#{2,5}) ',r'#\1 ',s,flags=re.M)
 parts.append('## '+title+'\n'+s)
text='\n\n'.join(parts).replace('E:/coding/code/Trade/paperclip/','').replace('E:\\coding\\code\\Trade\\paperclip\\','')
pattern=r'(?<![\w/])([.\w/@-]+\.(?:tsx?|m?js|json|md|ya?ml|toml|rs)|Dockerfile):(\d+)'
def cite(m):return link(m[1],int(m[2])) if m[1]in known else m[0]
text=re.sub(pattern,cite,text)
text=re.sub(r'`(\[[^\n]+?\]\(https://github\.com/paperclipai/paperclip/blob/[^\n]+?\))`',r'\1',text)
raw=json.loads(read(e/'rea-artifact.json'));records=[]
def scan(v):
 if isinstance(v,dict):
  if v.get('kind')=='root-manifest':records.append({k:v.get(k)for k in ['kind','value','evidence_id']})
  for x in v.values():scan(x)
 elif isinstance(v,list):
  for x in v:scan(x)
scan(raw)
rea={'archive_sha256':hashlib.sha256((e/'paperclip-source.zip').read_bytes()).hexdigest(),'ok':raw.get('ok'),'manifests':records,'scope':'Local pinned source ZIP member inventory, not TypeScript semantic/runtime verification'}
(e/'rea-summary.json').write_text(json.dumps(rea,indent=2),encoding='utf-8')
text+='\n\n## Verification, coverage aur evidence boundaries\n\n'
text+=f"Source inventory: **{summary['files']} tracked files**, {summary['bytes']:,} archive-member bytes, **{summary['packages']} named package manifests**, **{summary['table_declarations']} lexical table declarations**, **{summary['lexical_route_and_mount_literals']} lexical route/mount literals**, {summary['test_files']} test-classified source paths. These counts include fixtures/vendored/generated areas; they do not imply independently executing every feature or reading every test assertion. Hashes describe pinned git archive bytes; checkout line endings can differ.\n\n"
text+='REA archive SHA-256: `'+rea['archive_sha256']+'`. Actual REA root-manifest evidence is retained in rea-summary.json and full output. Inventory scope is static ZIP contents.\n\n'
text+='Selected verification command: `node --test scripts/check-no-git-push.test.mjs scripts/release-package-map.test.mjs` on Windows Node24.18.1. **26 tests:19 pass,7 fail**, exit1. These are script/release-helper tests, not application acceptance. Failures cluster in release manifest lookup: discovery uses Windows backslash paths while manifest keys use forward slashes. Focused reproduction:35 public packages discovered,32 raw lookup misses,0 after path normalization. No fix was applied. Saved raw test output and reproduction JSON establish this limited finding; Linux/CI behavior was not inferred from the Windows failure.\n\n'
text+='No workspace dependency installation, full Vitest/typecheck/build, browser acceptance, PostgreSQL startup/migrations, provider execution, live OAuth/MCP, Docker build, remote deployment or paid agent run was performed. Repository-wide test presence and documented CI workflows are not passing results. Source analysis and final document checks are the deliverable. Structural citations cannot prove absence of concurrency/security defects. Model/provider internals, hosted-only behavior, full Git history and future versions remain outside evidence.\n\n'
text+='Catalog coverage is complete for tracked files in source-inventory.json. Detailed semantic inspection focused the architecture and domains documented above; the large repository has more fixtures, optional plugins and integration combinations than this static review exercises. No speculative missing feature was added.\n\n'
text+='### Directory coverage\n\n| Top-level area | Tracked files |\n|---|---|\n'
for p,n in summary['by_top_directory'].items():text+=f'| `{p}` | {n} |\n'
text+='\n### Package manifest catalog\n\nAll named package manifests, including fixture/private packages; not a list of51 independently published applications.\n\n| Package | Version | Manifest |\n|---|---|---|\n'
for p in json.loads(read(e/'packages.json')):text+=f"| `{p['name']}` | {p.get('version') or 'private/unspecified'} | {link(p['path'])} |\n"
text+='\n### Database table declaration catalog\n\nLexically extracted literal pgTable/sqliteTable declarations in schema sources; relational behavior is explained above.\n\n| Table | Source |\n|---|---|\n'
for t in json.loads(read(e/'table-catalog.json')):text+=f"| `{t['table']}` | {link(t['path'],t['line'])} |\n"
text+='\n### Route and mount literal catalog\n\nSource lexical extraction, **not** an Express runtime router expansion. Includes .use mounts and literal calls; nested mounts, generated/dynamic routes, indirect registration and method overloads need owning source interpretation. Relative paths below must not be called final externally accessible URLs without their parent mount/auth layer.\n\n| Method | Literal | Source |\n|---|---|---|\n'
for x in json.loads(read(e/'route-literals.json')):text+=f"| {x['method'].upper()} | `{x['literal_path'].replace('|',chr(92)+'|')}` | {link(x['path'],x['line'])} |\n"
text+='\n### Saved evidence\n\n'
for name in ['rea-artifact.json','rea-summary.json','source-inventory.json','inventory-summary.json','packages.json','module-catalog.json','table-catalog.json','route-literals.json','test-catalog.json','selected-node-tests.txt','windows-release-path-reproduction.json','document-validation.json']:
 text+=f'- [{name}](paperclip-evidence/{name})\n'
target=b/'mirofish.md';backup=e/'mirofish-original-report.md'
if not backup.exists() or backup.stat().st_size==0:
 backup.write_bytes(target.read_bytes())
if not read(backup).startswith('# MiroFish'):raise RuntimeError('Expected original MiroFish backup')
target.write_text(text,encoding='utf-8')
errors=[];count=0
for p,n in re.findall(r'https://github\.com/paperclipai/paperclip/blob/'+sha+r'/([^\s)]+)#L(\d+)',text):
 count+=1
 if p not in known or not 1<=int(n)<=known[p].get('lines',0):errors.append([p,n])
for p in ['overview.md','backend-notes.md','runtime-notes.md','surfaces-notes.md']:
 if not (e/p).stat().st_size:errors.append('Empty '+p)
if len(inv)!=len([x for x in zipfile.ZipFile(e/'paperclip-source.zip').infolist()if not x.is_dir()]):errors.append('Inventory coverage mismatch')
if subprocess.check_output(['git','-C',str(r),'rev-parse','HEAD']).decode().strip()!=sha:errors.append('HEAD changed')
if subprocess.check_output(['git','-C',str(r),'diff','--name-only']).strip():errors.append('Tracked source changed')
if text.count('```')%2:errors.append('Fence mismatch')
result={'status':'PASS'if not errors else'FAIL','document':str(target),'document_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'words':len(text.split()),'source_links_checked':count,'tracked_file_inventory':len(inv),'errors':errors,'backup':str(backup),'backup_sha256':hashlib.sha256(backup.read_bytes()).hexdigest(),'limits':'Static/source/document verification; selected tests failed as explicitly recorded; no full runtime qualification'}
(e/'document-validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result));raise SystemExit(bool(errors))
