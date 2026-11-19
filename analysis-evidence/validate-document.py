from pathlib import Path
import re,json,subprocess,hashlib
base=Path(r'E:\coding\code\Trade'); p=base/'daytrade.md'; s=p.read_text(encoding='utf-8')
if '## Contents\n' not in s:
 heads=re.findall(r'^## (.+)$',s,re.M)
 def slug(t):return re.sub(r'\s+','-',re.sub(r'[^\w\s-]','',t.lower()))
 toc='## Contents\n\n'+'\n'.join('- ['+h+'](#'+slug(h)+')' for h in heads)+'\n\n'
 pos=s.index('## 1. ');s=s[:pos]+toc+s[pos:];p.write_text(s,encoding='utf-8')
local=[];source=[]
for label,dest in re.findall(r'\[([^\]\n]*)\]\(([^)\n]+)\)',s):
 if dest.startswith('analysis-evidence/') and not (base/dest).is_file():local.append(dest)
 if '/blob/3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd/' in dest:
  path,anchor=dest.split('/blob/3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd/')[1].split('#')
  f=base/'day-trader-skill'/path
  if not f.exists():source.append(dest);continue
  nums=[int(x) for x in re.findall(r'L(\d+)',anchor)]
  if any(n<1 or n>len(f.read_text(encoding='utf-8').splitlines()) for n in nums):source.append(dest)
required=['trader-scanner','trader-news','trader-entry','trader-exit','trader-timemachine','trader-budget','trader-risk','trader-broker','trader-alerts','trader-analyst','trader-pelosi']
check={'path':str(p),'bytes':p.stat().st_size,'words':len(s.split()),'lines':len(s.splitlines()),'module_sections':len(re.findall(r'^### 7\.\d+ trader-',s,re.M)),'missing_modules':[x for x in required if not re.search(r'^### 7\.\d+ '+x+':',s,re.M)],'missing_local_links':local,'bad_source_links':source,'unexpanded_placeholders':re.findall(r'__[A-Z_]+__',s),'balanced_code_fences':sum(x.startswith('```') for x in s.splitlines())%2==0,'source_diff':subprocess.check_output(['git','diff','--stat','HEAD'],cwd=base/'day-trader-skill',text=True),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
(base/'analysis-evidence/document-validation.json').write_text(json.dumps(check,indent=2),encoding='utf-8')
print(json.dumps(check,indent=2));assert not local and not source and not check['missing_modules'] and not check['unexpanded_placeholders'] and check['balanced_code_fences'] and not check['source_diff']
