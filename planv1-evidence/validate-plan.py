from pathlib import Path
from decimal import Decimal, ROUND_FLOOR
from urllib.parse import urlparse,unquote
import json,re,hashlib,subprocess,datetime
b=Path(r'E:\coding\code\Trade');e=b/'planv1-evidence';p=b/'planv1.md';s=p.read_text(encoding='utf-8')
repos={'Jakeschincariol/day-trader-skill':('day-trader-skill','3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd'),'openbq-org/OpenBB':('OpenBB','e43353a82815ff9ba56ad1b7ad47c32729dcf314'),'TauricResearch/TradingAgents':('TradingAgents','9fa1196fffbcfd9de5146d2dd2869df84ab99838'),'666ghj/MiroFish':('MiroFish','7657031ac01184afe2cb220f5ee3545573b5e843'),'paperclipai/paperclip':('paperclip','9de343b3fe2e2d4dc84fc8386d9ce04d553f39d6')}
errors=[];nrefs=0;nlocal=0;urls=set()
for label,url in re.findall(r'\[([^\]\n]*)\]\(([^)\n]+)\)',s):
 u=urlparse(url);urls.add(url)
 if u.netloc.lower()=='github.com' and '/blob/'in u.path:
  owner,tail=u.path.lstrip('/').split('/blob/',1);rev,rel=tail.split('/',1)
  if owner in repos:
   folder,expected=repos[owner]
   if rev!=expected:errors.append('Unpinned source '+url)
   f=b/folder/unquote(rel)
   if not f.is_file():errors.append('Missing source '+url);continue
   lines=len(f.read_text(encoding='utf-8-sig').splitlines())
   for number in re.findall(r'L(\d+)',u.fragment):
    if not 1<=int(number)<=lines:errors.append('Source line range '+url)
   nrefs+=1
 elif not u.scheme and not url.startswith('#'):
  f=b/unquote(url)
  if not f.is_file() and f!=e/'validation.json':errors.append('Missing local evidence '+url)
  nlocal+=1
for i in range(1,9):
 if not re.search(r'^## '+str(i)+r'\. ',s,re.M):errors.append('Missing requirement '+str(i))
for tag in ['P0','P1','P2','P3','P4','P5','P6','P7']:
 if not re.search(r'^### Task '+tag+r' ',s,re.M):errors.append('Missing task '+tag)
if not re.search(r'^- \[ \]',s,re.M):errors.append('No proposed unchecked tasks')
if s.count('```')%2:errors.append('Unbalanced code fences')
if '`['in s:errors.append('Code-wrapped Markdown link')
for term in ['TODO','TBD','FIXME']:
 if re.search(r'\b'+term+r'\b',s):errors.append('Unresolved placeholder '+term)
expectedcols=None
for n,line in enumerate(s.splitlines(),1):
 if line.startswith('|'):
  cols=len(re.findall(r'(?<!\\)\|',line))
  if expectedcols is None:expectedcols=cols
  elif cols!=expectedcols:errors.append('Table row width '+str(n))
 else:expectedcols=None
for name in ['news-sources.json','sources-data.json','sources-sim-risk.json','method-sources.json','md-review-inventory.json']:
 json.loads((e/name).read_text(encoding='utf-8'))
# Decimal-only fictional arithmetic; these checks do not run a strategy.
q=(Decimal(25)/Decimal(1700)/Decimal('0.00001')).to_integral_value(rounding=ROUND_FLOOR)*Decimal('0.00001')
loss=q*Decimal(1700);win=q*Decimal(3800);be=loss/(loss+win)*100
assert q==Decimal('0.01470') and loss==Decimal('24.99000') and win==Decimal('55.86000')
assert abs(be-Decimal('30.9091'))<Decimal('0.00001')
assert Decimal(3)*Decimal(60)/Decimal(5)==36
for expected in ['0.01470','24.99','55.86','30.9091']:
 if expected not in s:errors.append('Arithmetic display '+expected)
git=[]
for folder,sha in repos.values():
 head=subprocess.check_output(['git','-C',str(b/folder),'rev-parse','HEAD'],text=True).strip()
 diff=subprocess.check_output(['git','-C',str(b/folder),'diff','--name-only','HEAD'],text=True).strip()
 git.append({'repo':folder,'head':head,'tracked_diff_empty':not bool(diff)})
 if head!=sha or diff:errors.append('Source identity/diff '+folder)
for audit in ['audit-data.md','audit-risk.md','cross-review.md']:
 if not (e/audit).is_file():errors.append('Missing final review '+audit)
notional=Decimal('0.01')*Decimal('100000')
gross=notional*Decimal('0.01');margin=notional/Decimal(2);funding=notional*Decimal('0.0001')
assert notional==1000 and gross==10 and margin==500 and funding==Decimal('0.10')
for required in ['## I. User-confirmed scope: Spot vs Perpetual Futures comparison','equal notional','equal pre-specified stress-loss budget','Perpetual gate','fundingInfo']:
 if required not in s:errors.append('Missing comparison requirement '+required)
if 'Perpetual futures appendix-level future scope' in s:errors.append('Obsolete spot-only scope')
# Regressions discovered in the detailed recheck.
flat_ev=Decimal('0.40')*Decimal('55.86')-Decimal('0.50')*Decimal('24.99')
assert flat_ev==Decimal('9.849')
assert abs(Decimal('0.90')*((Decimal(4)/Decimal(9))*Decimal('55.86')-(Decimal(5)/Decimal(9))*Decimal('24.99'))-flat_ev)<Decimal('1e-24')
if 'p95≤2s' in s:errors.append('Conflicting latency percentile')
for required in ['p95≤250ms and p99≤2s','p_win+p_loss+p_zero=1','## F. Proposed implementation map','paired BTC/ETH spot','Explicit short-side sizing','only qualified local inference']:
 if required not in s:errors.append('Missing recheck requirement '+required)
if re.search(r'^\+(?:$|##|[A-Za-z])',s,re.M):errors.append('Stray patch marker')
for anchor in re.findall(r'\]\(#([^)]*)\)',s):
 if 'id="'+anchor+'"'not in s:errors.append('Missing navigation anchor '+anchor)
result={'status':'PASS'if not errors else'FAIL','checked_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'file':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'words':len(s.split()),'requirements_covered':8,'proposed_tasks':8,'pinned_source_links_checked':nrefs,'local_links_checked':nlocal,'unique_link_targets':len(urls),'decimal_checks':{'quantity':str(q),'modeled_loss':str(loss),'modeled_win':str(win),'break_even_pct':str(be),'github_requests_per_hour':36},'spot_perpetual_comparison':{'scope':'user confirmed both; paper only','notional':str(notional),'gross_one_pct_move':str(gross),'two_x_simplified_margin':str(margin),'hypothetical_funding':str(funding)},'recheck_regressions':{'flat_net_expectancy':str(flat_ev),'latency_budget':'p95<=250ms,p99<=2s;unmeasured','dual_product_capture':True,'short_sizing':True,'patch_marker_scan':True},'repo_checks':git,'errors':errors,'limits':'Document consistency/arithmetic/source ranges and independent review only; no new crypto system execution, performance benchmark, or profit estimate validated.'}
(e/'validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result));raise SystemExit(bool(errors))
