from pathlib import Path
import json,re,ast,urllib.parse,collections
b=Path(r'E:\coding\code\Trade');e=b/'obb-evidence';r=b/'OpenBB';s=(e/'document-template.md').read_text(encoding='utf-8-sig');sha='e43353a82815ff9ba56ad1b7ad47c32729dcf314'
inv=json.loads((e/'inventory.json').read_text());ps=json.loads((e/'packages.json').read_text());rea=json.loads((e/'rea-summary.json').read_text());cmds=json.loads((e/'command-catalog.json').read_text());providers=json.loads((e/'provider-catalog.json').read_text())
def table(headers,rows):return '| '+' | '.join(headers)+' |\n| '+' | '.join('---' for _ in headers)+' |\n'+'\n'.join('| '+' | '.join(str(x).replace('|','\\|').replace('\n',' ') for x in row)+' |' for row in rows)
def ref(path,line=1):return f'[[{path}:{line}]]'
def prod(path):return not any(x in {'tests','integration','examples'} for x in Path(path).parts) and not Path(path).name.startswith('test_')
s=s.replace('__REA_TABLE__',table(['REA field','Saved observation'],[['Evidence ID','`'+rea['evidence_id']+'`'],['Operation/provider',rea['operation']+' / '+rea['provider']['id']],['Source ZIP SHA256','`'+rea['archive_sha256_recomputed']+'`'],['Graph nodes/occurrences/edges',str(rea['manifest']['node_count'])+' / '+str(rea['manifest']['occurrence_count'])+' / '+str(rea['manifest']['edge_count'])],['Scope','ZIP central-directory inventory; no program execution']]))
roles={'.github':'CI/release workflows, development automation, issue/PR templates','assets':'Repository/support assets','cli':'Python terminal client, dispatcher/codegen/output/test modules','cookiecutter':'Reusable extension-project template generator','desktop':'React/TypeScript UI and Tauri/Rust native backend manager','examples':'Notebooks/community integrations/sample applications','images':'Repository/documentation visual assets','openbb_platform':'Core, domain/analytics extensions, providers, charting, tests, dev install, Docker and lockfile'}
s=s.replace('__TOP_TABLE__',table(['Root item','Tracked files','Role'],[[f'`{k}`',v,roles.get(k,'Root metadata/configuration/maintenance document; source filename states purpose')] for k,v in inv['top_level_counts'].items()]))
rows=[];entries=[]
for p in ps:
 pr=p['project'];name=pr.get('name');eps=pr.get('entry-points',{});rows.append([name,pr.get('version'),ref(p['path']),', '.join(eps) or 'No plugin entry-point group'])
 for name,target in pr.get('scripts',{}).items():entries.append(['`'+name+'`','`'+target+'`',pr.get('name'),ref(p['path'])])
s=s.replace('__PACKAGES_TABLE__',table(['Distribution','Declared version','Manifest','Entry-point groups'],rows)).replace('__ENTRYPOINT_TABLE__',table(['Command','Python target','Distribution','Source'],entries))
for token,file in [('__CORE_NOTES__','core-notes.md'),('__DATA_NOTES__','data-notes.md'),('__SURFACE_NOTES__','surfaces-notes.md')]:
 note=(e/file).read_text(encoding='utf-8-sig');lines=note.splitlines();note='\n'.join(lines[1:]).strip();note=re.sub(r'^## ', '### ',note,flags=re.M);s=s.replace(token,note)
rows=[]
for p in providers:
 if not prod(p['file']):continue
 d=p['definition'];name=ast.literal_eval(d['name']);cred=d.get('credentials','omitted (defaults to None)');rows.append([name,cred,ref(p['file'],p['line'])])
s=s.replace('__PROVIDERS_TABLE__',table(['Declared provider name','Credentials argument/default','Registration source'],rows))
rows=[]
for p in ps:
 if not p['path'].startswith('openbb_platform/extensions/'):continue
 pr=p['project'];groups=pr.get('entry-points',{});routes=groups.get('openbb_core_extension',{});chart=groups.get('openbb_charting_extension',{});rows.append([p['path'].split('/')[2],', '.join(routes) or 'Service/developer utility, not financial router',', '.join(chart) or 'No declared chart view entry',ref(p['path'])])
s=s.replace('__DOMAIN_TABLE__',table(['Extension folder','Core route entry name','Chart-view entry','Source'],rows))
groups=collections.defaultdict(list)
for c in cmds:
 if not prod(c['file']):continue
 parts=c['file'].split('/');group='/'.join(parts[:3]) if parts[0]=='openbb_platform' else parts[0];groups[group].append(c)
parts=[]
for group,cs in sorted(groups.items()):
 parts.append('#### '+group+' ('+str(len(cs))+' declarations)\n\n'+', '.join('`'+n+'`' for n in sorted({x['function'] for x in cs})))
s=s.replace('__COMMAND_INDEX__','\n\n'.join(parts))
coverage=[('Pinned snapshot/version/license','1,2,5'),('REA identity/hash/coverage boundaries','2'),('All root areas/file inventory','4'),('Every Python package manifest','5'),('SDK build/discovery/container/router/query pipeline','6'),('Settings/defaults/credentials/persistence/errors','6,8,11'),('Every production provider object','7'),('Concrete Nasdaq and Cboe adapter traces','6,7'),('Standard models, normalization, caching/paging','7'),('All domain/analytics extensions','7'),('OBBject/conversion/charting','6,7'),('RESTAPI/Workspace metadata/auth','8'),('MCP/transports/discovery/auth/skills','8'),('CLI/spec/dispatch/output/developer generation','8'),('Desktop/Tauri/process management/update boundaries','8'),('Cookiecutter/scaffolding','8'),('Dependency/build/install/Docker/CI/security files','5,8,9'),('Examples and maintenance conventions','9'),('Actual tests/failures vs source-declared tests','10'),('Unverified/external/runtime areas','11')]
s=s.replace('__COVERAGE_TABLE__',table(['Requested area','Document sections','Status'],[[x,y,'Documented with evidence; runtime scope stated separately'] for x,y in coverage]))
evidence=[('rea-artifact.json','Full retained REA envelope'),('rea-summary.json','Digest/manifest/archive Git-payload verification'),('OpenBB-source.zip','Pinned source archive input'),('inventory.json','Original broad source counters'),('refined-counts.json','Production/test partition and refined counters'),('packages.json','Full package dependencies/entry points'),('provider-catalog.json','Raw Provider constructor expressions/locations'),('command-catalog.json','All router.command declarations/locations'),('standard-model-catalog.json','Standard classes/bases/locations'),('tracked-files.json','All4,143source file paths'),('remote-tree.json','Saved remote recursive tree'),('core-notes.md','Verified reviewer core source notes'),('data-notes.md','Verified reviewer data/analytics source notes'),('surfaces-notes.md','Verified reviewer surfaces/build source notes'),('first-attempt-offline-tests.txt','Missing-aiohttp collection failure'),('offline-tests.txt','22passed offline tests'),('offline-test-manifest.json','Test copy hashes/command/scope'),('inventory.py','Static inventory utility'),('verify-archive.py','Git/archive digest verification utility'),('run-offline-tests.py','Isolated subset test runner'),('document-template.md','Report assembly source'),('CHECKPOINT.md','Historical quota stop; superseded'),('document-validation.json','Final completeness/citation/link checks (generated after assembly)')]
s=s.replace('__EVIDENCE_TABLE__',table(['Artifact','Purpose'],[[f'[{n}](obb-evidence/{n})',d] for n,d in evidence]))
issues=[];refs=[]
def source(m):
 path=m[1];a=int(m[2]);z=int(m[3] or a);p=r/path
 if not p.is_file():issues.append({'missing':path})
 else:
  length=len(p.read_text(encoding='utf-8-sig').splitlines())
  if a<1 or z>length or z<a:issues.append({'path':path,'first':a,'last':z,'length':length})
 refs.append({'path':path,'first':a,'last':z})
 return '['+path+':'+str(a)+(('-'+str(z)) if m[3] else '')+'](https://github.com/openbq-org/OpenBB/blob/'+sha+'/'+urllib.parse.quote(path,safe='/')+'#L'+str(a)+(('-L'+str(z)) if m[3] else '')+')'
s=re.sub(r'\[\[([^\]:]+):(\d+)(?:-(\d+))?\]\]',source,s)
heads=re.findall(r'^## (.+)$',s,re.M)
def slug(t):return re.sub(r'\s+','-',re.sub(r'[^\w\s-]','',t.lower()))
toc='## Contents\n\n'+'\n'.join('- ['+x+'](#'+slug(x)+')' for x in heads)+'\n\n';p=s.index('## 1. ');s=s[:p]+toc+s[p:]
s=s.replace('task ke no-server constraint mein unhe execute nahi kiya gaya','is source review mein server fixtures start nahi kiye gaye, isliye unhe execute nahi kiya gaya')
(b/'obb.md').write_text(s,encoding='utf-8')
(e/'source-reference-check.json').write_text(json.dumps({'count':len(refs),'issues':issues,'references':refs},indent=2),encoding='utf-8')
print(json.dumps({'words':len(s.split()),'lines':len(s.splitlines()),'source_refs':len(refs),'issues':issues},indent=2))
