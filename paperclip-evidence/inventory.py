from pathlib import Path
import json, re, hashlib, subprocess, collections, zipfile
r=Path(r'E:\coding\code\Trade\paperclip');o=r.parent/'paperclip-evidence'
archive=zipfile.ZipFile(o/'paperclip-source.zip')
names=[i.filename for i in archive.infolist() if not i.is_dir()]
files=[];packages=[];routes=[];tables=[];modules=[];tests=[]
for name in filter(None,names):
 p=r/name;b=archive.read(name);rec={'path':name,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
 try:s=b.decode('utf-8');rec['lines']=len(s.splitlines())
 except UnicodeDecodeError:s=None
 files.append(rec)
 if s is None:continue
 if name.endswith('package.json'):
  try:
   x=json.loads(s)
   if isinstance(x,dict) and 'name'in x:packages.append({'path':name,**{k:x.get(k) for k in ['name','version','private','engines','scripts','dependencies','exports','bin']}})
  except Exception:pass
 if name.endswith(('.ts','.tsx','.js','.mjs','.rs')):
  if re.search(r'(?:^|[/.])(?:test|tests|__tests__)(?:[/.])|\.(?:test|spec)\.',name):tests.append(name)
  if name.startswith(('server/src/routes/','server/src/modules/')):
   for m in re.finditer(r'\b(\w+)\.(get|post|put|patch|delete|use)\s*\(\s*([\'"])([^\'"\n]*)\3',s):
    routes.append({'path':name,'line':s.count('\n',0,m.start())+1,'receiver':m[1],'method':m[2],'literal_path':m[4]})
  if name.startswith('packages/db/src/schema/'):
   for m in re.finditer(r'\b(?:pgTable|sqliteTable)\s*\(\s*[\'"]([^\'"]+)',s):tables.append({'path':name,'line':s.count('\n',0,m.start())+1,'table':m[1]})
  if name.startswith(('server/src/services/','server/src/modules/','server/src/routes/','ui/src/pages/','cli/src/commands/')) and not re.search(r'\.(?:test|spec)\.',name):modules.append({'path':name,'lines':rec['lines']})
for name,obj in [('source-inventory.json',files),('packages.json',packages),('route-literals.json',routes),('table-catalog.json',tables),('module-catalog.json',modules),('test-catalog.json',tests)]:
 (o/name).write_text(json.dumps(obj,indent=2,ensure_ascii=False),encoding='utf-8')
summary={'commit':subprocess.check_output(['git','-C',str(r),'rev-parse','HEAD']).decode().strip(),'files':len(files),'bytes':sum(x['bytes'] for x in files),'hash_scope':'pinned git archive member bytes','by_top_directory':dict(collections.Counter(x['path'].split('/')[0] for x in files)),'extensions':dict(collections.Counter(Path(x['path']).suffix for x in files)),'packages':len(packages),'lexical_route_and_mount_literals':len(routes),'table_declarations':len(tables),'module_files':len(modules),'test_files':len(tests)}
(o/'inventory-summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary))
