from pathlib import Path
import json,re,subprocess,urllib.parse
base=Path(r'E:\coding\code\Trade'); repo=base/'day-trader-skill'; ev=base/'analysis-evidence'
template=(ev/'document-template.md').read_text(encoding='utf-8-sig')
template=template.replace('`trader/universe.json`','`trader/universe.txt`').replace('`trader/pelosi/`','`trader/state/ptr-pdfs/`')
inputs=['market-data-notes.md','entry-simulation-notes.md','money-path-notes.md']
sections={}
for filename in inputs:
 text=(ev/filename).read_text(encoding='utf-8-sig')
 for m in re.finditer(r'^## (trader-[^:\n]+):([^\n]*)\n(.*?)(?=^## |\Z)',text,re.M|re.S):
  sections[m.group(1)]=(m.group(2),m.group(3).strip())
order=['trader-scanner','trader-news','trader-entry','trader-exit','trader-timemachine','trader-budget','trader-risk','trader-broker','trader-alerts','trader-analyst','trader-pelosi']
assert set(sections)==set(order),(set(sections),set(order))
module_text='\n\n'.join(f'### 7.{i} {name}:{sections[name][0]}\n\n{sections[name][1]}' for i,name in enumerate(order,1))
# Wording correction: EPS subtraction isn't a valid general accounting derivation.
module_text=module_text.replace('derived EPS approximate.','EPS par bhi wahi subtraction apply hoti hai; changing weighted-average shares ke case mein isse valid quarter EPS establish nahi hoti (section 10 dekhein).')
# This is reviewer-internal execution bookkeeping, not a repo capability.
module_text=module_text.replace('default3','default 3').replace('default6','default 6').replace('defaultP','default P').replace('default15','default 15')
template=template.replace('__MODULE_NOTES__',module_text)
template=template.replace('__CONFIG_JSON__',(repo/'trader-budget/config.example.json').read_text().strip())
counts=json.loads((ev/'test-counts.json').read_text())
table='| Test module | Discovered tests |\n| --- | ---: |\n'+'\n'.join(f'| `{n}.py` | {v} |' for n,v in counts.items())+'\n| **Total** | **'+str(sum(counts.values()))+'** |'
template=template.replace('__TEST_TABLE__',table)
files=subprocess.check_output(['git','ls-files'],cwd=repo,text=True).strip()
template=template.replace('__TRACKED_FILES__',files)
url='https://github.com/Jakeschincariol/day-trader-skill/blob/3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd/'
refs=[]; issues=[]
def link(path,first,last=None):
 p=repo/path
 if not p.exists():issues.append({'missing_path':path});return f'`{path}:{first}`'
 n=len(p.read_text().splitlines()); a=int(first); b=int(last or first)
 if a>n or b>n or b<a:issues.append({'range':path,'first':a,'last':b,'lines':n})
 refs.append((path,a,b))
 label=path+':'+str(a)+(('-'+str(b)) if last else '')
 return '['+label+']('+url+urllib.parse.quote(path,safe='/')+'#L'+str(a)+(('-L'+str(b)) if last else '')+')'
# Expand source anchors in parent-authored sections.
template=re.sub(r'\[\[([^\]:]+):(\d+)(?:-(\d+))?\]\]',lambda m:link(m[1],m[2],m[3]),template)
# Expand reviewer note anchors, including shorthand references, while tracking module/file context.
by_basename={p.name:str(p.relative_to(repo)).replace('\\','/') for p in repo.glob('trader-*/*.py')}
module='trader-scanner'; lastpath=None
out=[]
for line in template.splitlines():
 heading=re.match(r'^### 7\.\d+ (trader-[^:]+):',line)
 if heading:
  module=heading[1]; lastpath=None
 def replace_token(m):
  global lastpath
  token=m[1]
  full=re.fullmatch(r'([\w./-]+\.(?:py|md|json)):(\d+)(?:-(\d+))?',token)
  short=re.fullmatch(r':(\d+)(?:-(\d+))?',token)
  if full:
   path=full[1]
   if '/' not in path:
    path=module+'/'+path if path=='SKILL.md' else by_basename.get(path,path)
   lastpath=path
   return link(path,full[2],full[3])
  if short and lastpath:return link(lastpath,short[1],short[2])
  return m[0]
 line=re.sub(r'`([^`\n]+)`',replace_token,line)
 out.append(line)
final='\n'.join(out)+'\n'
# Parent-provided example links point to entire small fixtures; clamp only known end bounds after inspecting sizes.
(base/'daytrade.md').write_text(final,encoding='utf-8')
(ev/'document-reference-check.json').write_text(json.dumps({'reference_count':len(refs),'issues':issues},indent=2),encoding='utf-8')
print(json.dumps({'output':str(base/'daytrade.md'),'words':len(final.split()),'lines':len(final.splitlines()),'characters':len(final),'references':len(refs),'issues':issues},indent=2))
