import pathlib,subprocess,json,ast,tomllib,collections,importlib.util
b=pathlib.Path(r'E:\coding\code\Trade');r=b/'OpenBB';e=b/'obb-evidence'
files=subprocess.check_output(['git','ls-files'],cwd=r,text=True).splitlines()
packages=[];syntax=[];commands=[];models=[];providers=[];testfunctions=0;parsed=0
for name in files:
 p=r/name
 if p.name=='pyproject.toml' and '{{' not in name:
  d=tomllib.loads(p.read_text(encoding='utf-8'));pr=d.get('project',d.get('tool',{}).get('poetry',{}));packages.append({'path':name,'project':pr,'build_system':d.get('build-system',{}),'entry_points':pr.get('entry-points',{})})
 if not name.endswith('.py') or '{{' in name:continue
 try:t=ast.parse(p.read_text(encoding='utf-8-sig'));parsed+=1
 except (SyntaxError,UnicodeError) as x:syntax.append({'path':name,'error':str(x)});continue
 for n in ast.walk(t):
  if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):
   if n.name.startswith('test_'):testfunctions+=1
   for dec in n.decorator_list:
    if isinstance(dec,ast.Call) and isinstance(dec.func,ast.Attribute) and dec.func.attr=='command':
     commands.append({'file':name,'line':n.lineno,'function':n.name,'decorator':ast.unparse(dec),'async':isinstance(n,ast.AsyncFunctionDef)})
  if isinstance(n,ast.ClassDef) and '/standard_models/' in name:models.append({'file':name,'line':n.lineno,'class':n.name,'bases':[ast.unparse(x) for x in n.bases]})
  if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='Provider':
   kw={x.arg:ast.unparse(x.value) for x in n.keywords}
   providers.append({'file':name,'line':n.lineno,'definition':kw})
summary={'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=r,text=True).strip(),'tracked_files':len(files),'python_files':sum(x.endswith('.py') for x in files),'ast_parsed_files':parsed,'syntax_failures':syntax,'declared_test_functions':testfunctions,'package_manifests':len(packages),'provider_declarations':len(providers),'router_command_declarations':len(commands),'standard_model_classes':len(models),'top_level_counts':dict(collections.Counter(x.split('/')[0] for x in files)),'python_dependencies_available':{x:importlib.util.find_spec(x) is not None for x in ['pytest','pydantic','fastapi','openbb','aiohttp','pandas']}}
for n,d in [('inventory',summary),('packages',packages),('provider-catalog',providers),('command-catalog',commands),('standard-model-catalog',models),('tracked-files',files)]:
 (e/(n+'.json')).write_text(json.dumps(d,indent=2),encoding='utf-8')
print(json.dumps(summary,indent=2))
