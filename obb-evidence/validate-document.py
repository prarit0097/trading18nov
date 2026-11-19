from pathlib import Path
import json,re,hashlib,subprocess,tomllib
b=Path(r'E:\coding\code\Trade');r=b/'OpenBB';e=b/'obb-evidence';p=b/'obb.md';s=p.read_text(encoding='utf-8');refs=json.loads((e/'source-reference-check.json').read_text());packages=json.loads((e/'packages.json').read_text())
(e/'document-validation.json').write_text('{}',encoding='utf-8')
missing=[];bad=[];links=0
for label,dest in re.findall(r'\[([^]\n]+)\]\(([^)\n]+)\)',s):
 if dest.startswith('obb-evidence/'):
  links+=1
  if not(b/dest).is_file():missing.append(dest)
 if '/blob/e43353a82815ff9ba56ad1b7ad47c32729dcf314/' in dest:
  path,anchor=dest.split('/blob/e43353a82815ff9ba56ad1b7ad47c32729dcf314/')[1].split('#');f=r/path
  if not f.exists():bad.append(dest);continue
  ns=[int(x) for x in re.findall(r'L(\d+)',anchor)];length=len(f.read_text(encoding='utf-8-sig').splitlines())
  if any(x<1 or x>length for x in ns):bad.append(dest)
manifest_errors=[]
for pkg in packages:
 original=tomllib.loads((r/pkg['path']).read_text(encoding='utf-8'))['project']
 if original!=pkg['project']:manifest_errors.append(pkg['path'])
current_files=subprocess.check_output(['git','ls-files'],cwd=r,text=True).splitlines();stored_files=json.loads((e/'tracked-files.json').read_text());head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=r,text=True).strip();diff=subprocess.check_output(['git','diff','--stat','HEAD'],cwd=r,text=True)
subset=json.loads((e/'offline-test-manifest.json').read_text());copy_errors=[x['source'] for x in subset['files'] if hashlib.sha256((r/x['source']).read_bytes()).hexdigest()!=x['sha256']]
checks={'status':'verified within stated source-documentation scope','commit':head,'document':str(p),'bytes':p.stat().st_size,'words':len(s.split()),'source_reference_count':refs['count'],'source_reference_errors':refs['issues']+bad,'local_evidence_links_checked':links,'missing_evidence_links':missing,'package_manifests_checked':len(packages),'manifest_changes':manifest_errors,'packages_missing_from_document':[x['project']['name'] for x in packages if x['project']['name'] not in s],'tracked_file_inventory_matches':current_files==stored_files,'tracked_source_diff':diff,'remaining_template_tokens':re.findall(r'__[A-Z_]+__',s),'balanced_code_fences':sum(x.startswith('```') for x in s.splitlines())%2==0,'offline_test_exit':subset['exit_code'],'offline_test_copy_hash_errors':copy_errors,'offline_test_log_has_22_passed':'22 passed' in (e/'offline-tests.txt').read_text(encoding='utf-8'),'initial_collection_failure_preserved':(e/'first-attempt-offline-tests.txt').exists(),'verification_scope_exclusions':'Full installed SDK/API/MCP/desktop/provider integration and hosted services not executed; test/environment limitations explicitly documented.','sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
assert head=='e43353a82815ff9ba56ad1b7ad47c32729dcf314' and not refs['issues'] and not bad and not missing and not diff and not manifest_errors and not copy_errors and not checks['remaining_template_tokens'] and checks['balanced_code_fences'] and checks['tracked_file_inventory_matches'] and not checks['packages_missing_from_document'] and checks['offline_test_exit']==0 and checks['offline_test_log_has_22_passed']
(e/'document-validation.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
(e/'CHECKPOINT.md').write_text('Historical pause: prior five-hour usage90%used10%remaining. Resumed16November2026 with99%remaining. Source documentation integrated and independently reviewed; E:/coding/code/Trade/obb.md supersedes partialdraft. Final validation saved in document-validation.json. No tracked source changes. Full runtime/integration tests and hosted internals remain explicitly unverified, not hidden pending work.\n',encoding='utf-8')
print(json.dumps(checks,indent=2))
