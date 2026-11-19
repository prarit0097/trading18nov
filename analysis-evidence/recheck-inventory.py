from pathlib import Path
import ast,subprocess,sys,json,hashlib,zipfile
base=Path(r'E:\coding\code\Trade');repo=base/'day-trader-skill';ev=base/'analysis-evidence'
allhelp=[];inventory=[]
for p in sorted(repo.glob('trader-*/*.py')):
 tree=ast.parse(p.read_text(encoding='utf-8'))
 cmds=[n.args[0].value for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='add_parser' and n.args and isinstance(n.args[0],ast.Constant)]
 flags=sorted({a.value for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='add_argument' for a in n.args if isinstance(a,ast.Constant) and isinstance(a.value,str) and a.value.startswith('--')})
 row={'script':p.relative_to(repo).as_posix(),'subcommands':cmds,'flags':flags,'help_commands':[]}
 for cmd in [None]+cmds:
  args=[sys.executable,str(p)]+([cmd] if cmd else [])+['--help']
  r=subprocess.run(args,cwd=repo,capture_output=True,text=True,encoding='utf-8')
  assert r.returncode==0,(args,r.stderr)
  label='python '+row['script']+(' '+cmd if cmd else '')+' --help'
  allhelp.extend([label,r.stdout,''])
  row['help_commands'].append(label)
 inventory.append(row)
(ev/'cli-help-complete.txt').write_text('\n'.join(allhelp),encoding='utf-8')
(ev/'cli-inventory.json').write_text(json.dumps(inventory,indent=2),encoding='utf-8')
archive=ev/'day-trader-skill-source.zip';meta=json.loads((ev/'rea-summary.json').read_text())
sha=hashlib.sha256(archive.read_bytes()).hexdigest();assert sha==meta['subject']['digest']['sha256']
with zipfile.ZipFile(archive) as z:
 files=[n for n in z.namelist() if not n.endswith('/')]
 tracked=subprocess.check_output(['git','ls-files'],cwd=repo,text=True).splitlines();assert sorted(files)==sorted(tracked)
 exact=0; eol_only=[]
 for name in files:
  archived=z.read(name); blob=subprocess.check_output(['git','show','HEAD:'+name],cwd=repo)
  if archived==blob:exact+=1;continue
  assert name=='LICENSE' or Path(name).suffix in {'.md','.py','.json','.csv','.txt','.xml'},name
  assert archived.replace(b'\r\n',b'\n')==blob.replace(b'\r\n',b'\n'),name
  eol_only.append(name)
result={'scripts':len(inventory),'help_invocations':sum(len(x['help_commands']) for x in inventory),'all_help_exit_zero':True,'archive_sha256':sha,'git_archive_payloads_verified':len(files),'byte_exact_files':exact,'text_files_with_only_CRLF_LF_difference':len(eol_only)}
(ev/'archive-cli-recheck.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))
