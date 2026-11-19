from pathlib import Path
from urllib.parse import unquote, urlparse
import hashlib, json, re, subprocess, collections, ast, datetime
base=Path(r'E:\coding\code\Trade'); root=base/'MiroFish'; ev=base/'mirofish-evidence'; doc=base/'mirofish.md'
text=doc.read_text(encoding='utf-8'); sha='7657031ac01184afe2cb220f5ee3545573b5e843'
files=json.loads((ev/'source-inventory.json').read_text(encoding='utf-8'))
routes=json.loads((ev/'api-catalog.json').read_text(encoding='utf-8'))
errors=[]; sources=0; locals_=0
for label,url in re.findall(r'\[([^\]]*)\]\(([^)]+)\)',text):
    if url.startswith('https://github.com/666ghj/MiroFish/blob/'):
        tail=url.split('/blob/',1)[1]; revision,rest=tail.split('/',1)
        if revision!=sha: errors.append('Unpinned source '+url)
        p,_,fragment=rest.partition('#');p=unquote(p)
        if not (root/p).is_file():errors.append('Missing source '+p);continue
        if fragment.startswith('L'):
            n=int(fragment[1:])
            if n<1 or n>len((root/p).read_text(encoding='utf-8',errors='replace').splitlines()):errors.append('Out of bounds '+url)
        sources+=1
    elif not urlparse(url).scheme and not url.startswith('#'):
        p=base/unquote(url)
        if not p.is_file():errors.append('Missing evidence '+url)
        locals_+=1
for f in files:
    p=root/f['path']
    if hashlib.sha256(p.read_bytes()).hexdigest()!=f['sha256']:errors.append('Source changed '+f['path'])
    if f['path'] not in text:errors.append('Uncatalogued file '+f['path'])
    if p.suffix=='.py':ast.parse(p.read_text(encoding='utf-8'),filename=f['path'])
for r in routes:
    if '`'+r['route']+'`' not in text:errors.append('Missing API '+r['route'])
head=text.split('## Appendix A.')[0]
for f in files:
    p=f['path']
    if p.startswith('backend/app/') and p.endswith('.py') and not p.endswith('/__init__.py') and p not in head:errors.append('No narrative coverage '+p)
if text.count('```')%2:errors.append('Unbalanced fenced block')
if re.search(r'\b(?:TODO|TBD|FIXME)\b',text):errors.append('Unresolved placeholder')
if '`[' in text:errors.append('Markdown link incorrectly code-wrapped')
actualsha=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD']).decode().strip()
status=subprocess.check_output(['git','-C',str(root),'status','--porcelain']).decode().strip()
if actualsha!=sha:errors.append('Commit changed')
if status:errors.append('Repository not clean '+status)
if '129 passed' not in (ev/'backend-tests.txt').read_text(encoding='utf-8-sig'):errors.append('Backend test result mismatch')
if 'Ran 28 tests' not in (ev/'root-tests-py312.txt').read_text(encoding='utf-8-sig') or 'FAILED (failures=1)' not in (ev/'root-tests-py312.txt').read_text(encoding='utf-8-sig'):errors.append('Root test result mismatch')
if 'built in' not in (ev/'frontend-build.txt').read_text(encoding='utf-8-sig'):errors.append('Build result mismatch')
result={'checked_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'document':str(doc),'document_sha256':hashlib.sha256(doc.read_bytes()).hexdigest(),'words':len(text.split()),'source_links_checked':sources,'local_evidence_links_checked':locals_,'tracked_files_checked':len(files),'route_registrations_checked':len(routes),'python_ast_files_checked':sum(f['path'].endswith('.py') for f in files),'commit':actualsha,'repository_clean':not bool(status),'errors':errors,'status':'PASS' if not errors else 'FAIL','limits':'Mechanical completeness/citation checks plus separate independent semantic audits; not all runtime paths or external providers verified.'}
(ev/'document-validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
raise SystemExit(bool(errors))
