from pathlib import Path
import ast,json,re,urllib.parse
b=Path(r'E:\coding\code\Trade');r=b/'TradingAgents';e=b/'tradingagent-evidence';s=(e/'document-template.md').read_text(encoding='utf-8-sig');sha='9fa1196fffbcfd9de5146d2dd2869df84ab99838'
def table(head,rows):return '| '+' | '.join(head)+' |\n| '+' | '.join('---' for x in head)+' |\n'+'\n'.join('| '+' | '.join(str(x).replace('|','\\|').replace('\n',' ') for x in row)+' |' for row in rows)
a=json.loads((e/'rea-summary.json').read_text());iv=json.loads((e/'inventory.json').read_text());meta=json.loads((e/'project-metadata.json').read_text())
s=s.replace('__REA__',table(['REA field','Observed result'],[['Evidence ID','`'+a['evidence_id']+'`'],['SHA256','`'+a['archive_sha256_recomputed']+'`'],['Provider',a['provider']['id']],['Graph nodes/occurrences/edges',str(a['manifest']['node_count'])+'/'+str(a['manifest']['occurrence_count'])+'/'+str(a['manifest']['edge_count'])],['Scope',a['coverage']['status']+'; static ZIP inventory only']]))
s=s.replace('__ROOTS__',table(['Tracked root item','Files'],[['`'+k+'`',v] for k,v in iv['top_level_counts'].items()]))
for token,name in [('__GRAPH__','graph-notes.md'),('__DATA_LLM__','data-llm-notes.md')]:
 note=(e/name).read_text(encoding='utf-8-sig').splitlines();note='\n'.join(note[1:]).strip();note=re.sub(r'^## ', '### ',note,flags=re.M);s=s.replace(token,note)
t=ast.parse((r/'tradingagents/default_config.py').read_text());defaults=[];env={}
for node in t.body:
 if isinstance(node,ast.Assign) and any(isinstance(x,ast.Name) and x.id=='_ENV_OVERRIDES' for x in node.targets):env=ast.literal_eval(node.value)
 if isinstance(node,ast.FunctionDef) and node.name=='build_default_config':
  expr=next(x for x in ast.walk(node) if isinstance(x,ast.Return)).value.args[0]
  for k,v in zip(expr.keys,expr.values):defaults.append({'key':ast.literal_eval(k),'expression':ast.unparse(v),'line':v.lineno})
(e/'default-config-catalog.json').write_text(json.dumps({'defaults':defaults,'env_mapping':env},indent=2),encoding='utf-8')
s=s.replace('__DEFAULTS__',table(['Config key','Built-in source expression','Source'],[['`'+x['key']+'`','`'+x['expression']+'`','[[tradingagents/default_config.py:'+str(x['line'])+']]'] for x in defaults]))
s=s.replace('__ENV_KEYS__',', '.join('`'+k+'` -> `'+v+'`' for k,v in env.items())).replace('__DEPENDENCIES__',', '.join('`'+x+'`' for x in meta['project']['dependencies']))
t=ast.parse((r/'cli/main.py').read_text());rows=[]
for fn in t.body:
 if not isinstance(fn,ast.FunctionDef):continue
 args=fn.args.args[-len(fn.args.defaults):] if fn.args.defaults else []
 for arg,value in zip(args,fn.args.defaults):
  if isinstance(value,ast.Call) and isinstance(value.func,ast.Attribute) and value.func.attr in {'Option','Argument'}:
   opts=[x.value for x in value.args if isinstance(x,ast.Constant) and isinstance(x.value,str) and x.value.startswith('--')];default=ast.unparse(value.args[0]) if value.args else ''
   rows.append([fn.name,'`'+arg.arg+'`',', '.join('`'+x+'`' for x in opts) or 'positional', '`'+default+'`','[[cli/main.py:'+str(value.lineno)+']]'])
s=s.replace('__CLI__',table(['Entry function','Parameter','Declared flags','Default/required expression','Source'],rows))
t=ast.parse((r/'tradingagents/agents/tools.py').read_text());tools=[]
for fn in t.body:
 if isinstance(fn,(ast.FunctionDef,ast.AsyncFunctionDef)) and fn.decorator_list:tools.append({'name':fn.name,'line':fn.lineno,'doc':ast.get_docstring(fn)})
(e/'tool-catalog.json').write_text(json.dumps(tools,indent=2),encoding='utf-8')
s=s.replace('## 6. Configuration:', '### All agent tool wrapper definitions\n\n'+table(['Tool function','Source'],[['`'+x['name']+'`','[[tradingagents/agents/tools.py:'+str(x['line'])+']]'] for x in tools])+'\n\n## 6. Configuration:')
s=s.replace('__FILES__','```text\n'+'\n'.join(json.loads((e/'tracked-files.json').read_text()))+'\n```')
refs=[];issues=[]
def link(m):
 path=m[1];a=int(m[2]);z=int(m[3] or a);p=r/path
 if not p.exists():issues.append({'missing':path})
 else:
  n=len(p.read_text(encoding='utf-8-sig').splitlines())
  if a<1 or z>n or z<a:issues.append({'path':path,'start':a,'end':z,'length':n})
 refs.append({'path':path,'first':a,'last':z})
 return '['+path+':'+str(a)+(('-'+str(z)) if m[3] else '')+'](https://github.com/TauricResearch/TradingAgents/blob/'+sha+'/'+urllib.parse.quote(path,safe='/')+'#L'+str(a)+(('-L'+str(z)) if m[3] else '')+')'
s=re.sub(r'\[\[([^\]:]+):(\d+)(?:-(\d+))?\]\]',link,s)
heads=re.findall(r'^## (.+)$',s,re.M)
def slug(x):return re.sub(r'\s+','-',re.sub(r'[^\w\s-]','',x.lower()))
toc='## Contents\n\n'+'\n'.join('- ['+x+'](#'+slug(x)+')' for x in heads)+'\n\n';i=s.index('## 1. ');s=s[:i]+toc+s[i:]
(b/'tradingagent.md').write_text(s,encoding='utf-8');(e/'source-reference-check.json').write_text(json.dumps({'count':len(refs),'issues':issues,'references':refs},indent=2),encoding='utf-8');print(json.dumps({'words':len(s.split()),'lines':len(s.splitlines()),'references':len(refs),'issues':issues},indent=2))
