from pathlib import Path
import ast, hashlib, json, subprocess, collections
repo=Path(r'E:\coding\code\Trade\MiroFish'); out=repo.parent/'mirofish-evidence'
paths=subprocess.check_output(['git','-C',str(repo),'ls-files','-z']).decode().split('\0')
files=[];routes=[];symbols=[];errors=[]
prefix={'graph.py':'/api/graph','simulation.py':'/api/simulation','report.py':'/api/report'}
for name in filter(None,paths):
    p=repo/name; b=p.read_bytes()
    rec={'path':name,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
    try: text=b.decode('utf-8');rec['lines']=len(text.splitlines())
    except UnicodeDecodeError: text=None
    if name.endswith('.py'):
        try:
            tree=ast.parse(text,filename=name)
            for node in ast.walk(tree):
                if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                    symbols.append({'path':name,'line':node.lineno,'end_line':node.end_lineno,'kind':type(node).__name__,'name':node.name})
                if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                    for d in node.decorator_list:
                        if isinstance(d,ast.Call) and isinstance(d.func,ast.Attribute) and d.func.attr=='route' and d.args:
                            route=ast.literal_eval(d.args[0]); methods=['GET']
                            for kw in d.keywords:
                                if kw.arg=='methods': methods=ast.literal_eval(kw.value)
                            routes.append({'path':name,'line':node.lineno,'function':node.name,'route':prefix.get(p.name,'')+route,'methods':methods})
        except Exception as e: errors.append({'path':name,'error':str(e)})
    files.append(rec)
raw=json.loads((out/'rea-artifact.json').read_text(encoding='utf-8-sig'))
ev=raw.get('data',raw.get('result',raw))
summary={'envelope_keys':list(raw),'zip_sha256':hashlib.sha256((out/'MiroFish-source.zip').read_bytes()).hexdigest()}
def scan(obj):
    if isinstance(obj,dict):
        if obj.get('kind')=='root-manifest': summary['root_manifest']=obj.get('value');summary['root_evidence_id']=obj.get('evidence_id')
        if 'limitations' in obj and isinstance(obj['limitations'],list): summary.setdefault('limitations',[]).extend(x for x in obj['limitations'] if isinstance(x,str))
        for v in obj.values():scan(v)
    elif isinstance(obj,list):
        for v in obj:scan(v)
scan(raw);summary['limitations']=list(dict.fromkeys(summary.get('limitations',[])))
for name,data in [('source-inventory.json',files),('api-catalog.json',routes),('symbol-catalog.json',symbols),('rea-summary.json',summary)]:
    (out/name).write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8')
counts={'commit':subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD']).decode().strip(),'files':len(files),'python_files':sum(x['path'].endswith('.py') for x in files),'vue_files':sum(x['path'].endswith('.vue') for x in files),'routes':len(routes),'python_symbols':len(symbols),'ast_errors':errors,'extensions':dict(collections.Counter(Path(x['path']).suffix for x in files))}
(out/'inventory-summary.json').write_text(json.dumps(counts,indent=2),encoding='utf-8')
print(json.dumps(counts));print(json.dumps(summary))
