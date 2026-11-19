from pathlib import Path
import json, re
base=Path(r'E:\coding\code\Trade'); evidence=base/'mirofish-evidence'
sha='7657031ac01184afe2cb220f5ee3545573b5e843'
files=json.loads((evidence/'source-inventory.json').read_text(encoding='utf-8'))
known={f['path']:f for f in files}
def source(path,line=1):
    return f'[{path}:{line}](https://github.com/666ghj/MiroFish/blob/{sha}/{path}#L{line})'
def refs(text):
    # Complete path:line citations are made clickable; shorthand :line
    # references remain anchored by the full source reference in that paragraph.
    pattern=r'(?<![\w/])([.\w/-]+\.(?:py|vue|js|json|toml|md|yml|txt)|Dockerfile|LICENSE|\.env\.example):(\d+)'
    def sub(m):
        path=m[1]
        return source(path,int(m[2])) if path in known else m[0]
    text=re.sub(pattern,sub,text)
    # Remove code-span wrappers around a complete generated link.
    return re.sub(r'`(\[[^\n]+?\]\(https://github\.com/666ghj/MiroFish/blob/[^\n]+?\))`',r'\1',text)
def expand_shorthand(text):
    pattern=r'(?<![\w/])([.\w/-]+\.(?:py|vue|js|json|toml|md|yml|txt)|Dockerfile|LICENSE|\.env\.example):(\d+)|(?<![\w]):(\d{2,5})(?!\d)'
    paragraphs=[]
    for paragraph in text.split('\n\n'):
        current=None
        def replace(m):
            nonlocal current
            if m[1]:
                if m[1] in known:current=m[1]
                return m[0]
            n=int(m[3])
            if current and n<=known[current].get('lines',0):return current+':'+str(n)
            return m[0]
        paragraphs.append(re.sub(pattern,replace,paragraph))
    return '\n\n'.join(paragraphs)
parts=[(evidence/'overview-notes.md').read_text(encoding='utf-8')]
for title,name in [('8. Graph, ontology, memory aur shared utilities','graph-notes.md'),('9. Simulation, agents, scheduling aur process lifecycle','simulation-notes.md'),('10. ReportAgent, frontend aur interaction','report-ui-notes.md')]:
    text=(evidence/name).read_text(encoding='utf-8')
    lines=text.splitlines(); lines=lines[1:]
    # Drop a contributor-local scope disclaimer: global verification section
    # supplies authoritative executed-test boundaries for this final report.
    while lines and not lines[0].strip(): lines.pop(0)
    if lines and lines[0].startswith('Scope:'):
        lines.pop(0)
    text='\n'.join(lines).strip()
    text=re.sub(r'^(#{2,5}) ',r'#\1 ',text,flags=re.M)
    parts.append('## '+title+'\n\n'+text)
parts.append((evidence/'verification-notes.md').read_text(encoding='utf-8'))
body='\n\n'.join(parts)
body=body.replace('Source only, no service calls/test imports.','')
body=body.replace('Existing tests: static coverage map (not executed by this subtask)','Existing tests: source coverage map (execution results in verification section)')
body=body.replace('Parent independently verified Node prerequisite discrepancy and build; use parent\'s verification logs for actual runtime results.','Node prerequisite discrepancy and build results are recorded in the verification section.')
body=body.replace('This agent did not execute tests; parent has separate validation output.','Actual execution results are recorded in the verification section.')
body=body.replace('Tests ko padha hai; test execution ka claim nahi hai.','Actual test execution results are recorded in the verification section.')
body=refs(expand_shorthand(body))
routes=json.loads((evidence/'api-catalog.json').read_text())
body+='\n\n## Appendix A. Complete HTTP route catalog\n\n'
body+='AST-derived exact route registrations; Flask implicit HEAD/OPTIONS ko separate APIs nahi count kiya. Har route exercised hone ka claim nahi. Path variables literal source notation mein hain. Prefix registrations app factory se included hain.\n\n| Methods | Full route | Handler | Source |\n|---|---|---|---|\n'
for r in routes:
    body+=f"| {', '.join(r['methods'])} | `{r['route']}` | `{r['function']}` | {source(r['path'],r['line'])} |\n"
body+='\n## Appendix B. Complete tracked-file coverage index\n\n'
body+='Every tracked file is accounted for below. Index inclusion means inventoried, not independently runtime-tested. Large lockfiles record dependencies; binary images are design/demo assets and were not treated as source evidence of execution. Python symbols are separately recorded in `mirofish-evidence/symbol-catalog.json`.\n\n| File | Lines / bytes | Role |\n|---|---|---|\n'
def role(p):
    if '/tests/' in p or p.startswith('tests/'): return 'Existing offline regression/contract tests; see verification boundaries'
    if p.startswith('backend/app/api/'): return 'HTTP boundary, validation and asynchronous orchestration'
    if p.startswith('backend/app/services/'): return 'Domain service; detailed subsystem trace above'
    if p.startswith('backend/app/models/'): return 'Project/task state contracts and persistence'
    if p.startswith('backend/app/utils/'): return 'Shared provider/parsing/schema/retry/locale/logging support'
    if p.startswith('backend/scripts/'): return 'Simulation child runtime or supplemental manual validation tool'
    if p.startswith('frontend/src/'): return 'SPA route/view/component/client/local state; detailed frontend trace above'
    if p.startswith('locales/'): return 'Language registry or translation strings'
    if p.startswith('scripts/'): return 'Repository star-history maintenance, independent of simulator'
    if p.startswith('.github/'): return 'Release/star-history automation or provenance data/notices'
    if p.endswith(('.jpeg','.jpg','.png','.svg')): return 'Static visual/demo asset; not runtime/model validation'
    if 'lock' in p: return 'Resolved dependency graph / build reproducibility'
    return 'Application entry, dependency/build/deploy configuration, license or project documentation'
for f in files:
    p=f['path']; lines=f.get('lines'); stat=f'{lines} lines' if lines is not None else f"{f['bytes']} bytes"
    body+=f"| {source(p)} | {stat} | {role(p)} |\n"
body+='\n## Appendix C. Saved evidence and reproduction\n\n'
body+='| Evidence | Purpose |\n|---|---|\n'
for path,desc in [('MiroFish-source.zip','Pinned git archive supplied to REA'),('rea-artifact.json','Full actual REA CLI evidence'),('rea-summary.json','Evidence identity, counts and limitations'),('source-inventory.json','All tracked file SHA-256/size/line inventory'),('api-catalog.json','All 60 route registrations and source locations'),('symbol-catalog.json','All Python function/class AST definitions'),('inventory-summary.json','Counts and Python syntax parsing result'),('backend-tests.txt','129 passing backend offline tests'),('root-tests-py312.txt','28 helper tests: 27 pass, 1 Windows failure'),('windows-symlink-reproduction.json','Focused Windows failure reproduction'),('frontend-build.txt','Successful isolated Vite production build and warning'),('frontend-install.txt','Isolated npm ci output'),('test-environment.txt','Installed lightweight audit/test environment'),('verification-manifest.json','Commands, results, explicit untested surfaces'),('simulation-audit.md','Independent post-write simulation review; overview clarifications incorporated'),('report-ui-audit.md','Independent post-write report/UI review; editorial clarifications incorporated'),('document-validation.json','Source citations/links/inventory/final file checks')]:
    body+=f'| [{path}](mirofish-evidence/{path}) | {desc} |\n'
body+='\nReproduce source inventories with `python mirofish-evidence/inventory.py`; compose with `python mirofish-evidence/compose-document.py`; validate with `python mirofish-evidence/validate-document.py`. Existing backend tests: run the recorded Python 3.12 environment from `MiroFish/backend` with `python -m pytest tests -q --disable-warnings -p no:cacheprovider`. Root helper tests: from `MiroFish`, `python -m unittest discover -s tests -v`. Frontend build was isolated under evidence directory; no live services or repository source changes are required for these offline checks.\n'
(base/'mirofish.md').write_text(body,encoding='utf-8')
print(json.dumps({'file':str(base/'mirofish.md'),'words':len(body.split()),'lines':len(body.splitlines()),'bytes':len(body.encode('utf-8'))}))
