from pathlib import Path
import ast,json,subprocess,collections,tomllib
b=Path(r'E:\coding\code\Trade');r=b/'TradingAgents';e=b/'tradingagent-evidence';files=subprocess.check_output(['git','ls-files'],cwd=r,text=True).splitlines();funcs=[];imports=collections.Counter();testcount=0;errs=[];options=[];classes=[]
for name in files:
 if not name.endswith('.py'):continue
 try:t=ast.parse((r/name).read_text(encoding='utf-8-sig'))
 except SyntaxError as x:errs.append({'file':name,'error':str(x)});continue
 for n in ast.walk(t):
  if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):
   funcs.append({'file':name,'line':n.lineno,'name':n.name,'async':isinstance(n,ast.AsyncFunctionDef)});testcount+=int(n.name.startswith('test_'))
  elif isinstance(n,ast.ClassDef):classes.append({'file':name,'line':n.lineno,'name':n.name})
  elif isinstance(n,ast.Import):imports.update(a.name.split('.')[0] for a in n.names)
  elif isinstance(n,ast.ImportFrom) and n.module:imports.update([n.module.split('.')[0]])
  elif isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in {'Option','Argument'}:
   options.append({'file':name,'line':n.lineno,'kind':n.func.attr,'args':[ast.unparse(x) for x in n.args],'kwargs':{x.arg:ast.unparse(x.value) for x in n.keywords}})
summary={'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=r,text=True).strip(),'tracked_files':len(files),'python_files':sum(x.endswith('.py') for x in files),'test_files':sum(x.startswith('tests/test_') and x.endswith('.py') for x in files),'declared_test_functions':testcount,'ast_syntax_errors':errs,'production_python_lines':sum(len((r/x).read_text(encoding='utf-8-sig').splitlines()) for x in files if x.endswith('.py') and not x.startswith('tests/')),'top_level_counts':dict(collections.Counter(x.split('/')[0] for x in files))}
for n,d in [('inventory',summary),('tracked-files',files),('function-catalog',funcs),('class-catalog',classes),('cli-option-catalog',options),('import-catalog',dict(imports)),('project-metadata',tomllib.loads((r/'pyproject.toml').read_text()))]:(e/(n+'.json')).write_text(json.dumps(d,indent=2),encoding='utf-8')
print(json.dumps(summary,indent=2))
