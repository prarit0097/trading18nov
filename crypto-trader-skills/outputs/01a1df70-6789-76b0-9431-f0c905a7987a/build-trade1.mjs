import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath, pathToFileURL} from 'node:url';

const bundled = createRequire(path.resolve(path.dirname(process.execPath), '../package.json'));
const {Workbook, SpreadsheetFile} = await import(pathToFileURL(bundled.resolve('@oai/artifact-tool')));
const directory = path.dirname(fileURLToPath(import.meta.url));
const run = path.resolve(directory, '../../runs/trade1');
const navy = '#173249', teal = '#087B72', pale = '#E4F2EF', ink = '#203748';
const usd = '#,##0.00######;[Red](#,##0.00######);0.00';
const price = '0.00######';
const datetime = 'dd mmm yyyy hh:mm:ss';
const number = value => {
  if (value === null || value === undefined || value === '') return null;
  const result = Number(value);
  if (!Number.isFinite(result)) throw new Error('Non-finite ledger value');
  return result;
};
function instant(value, offsetHours=0) {
  if (!value) return null;
  if (!/(Z|[+-]\d\d:\d\d)$/i.test(value)) throw new Error('Timestamp missing a timezone');
  return 25569 + (number(Date.parse(value)) + offsetHours * 3600000) / 86400000;
}
function col(i) {
  let name = '';
  for (let n=i+1; n; n=Math.floor((n-1)/26)) name=String.fromCharCode(65+(n-1)%26)+name;
  return name;
}
function band(sheet, address, value, fill=navy, height=34, size=16) {
  const area = sheet.getRange(address);
  area.merge();
  area.values = [[value]];
  area.format = {fill, rowHeight:height, verticalAlignment:'center',
    font:{name:'Aptos',size,bold:true,color:'#FFFFFF'}};
}
function subtitle(sheet, address, value) {
  const area=sheet.getRange(address);
  area.merge();
  area.values=[[value]];
  area.format={fill:pale, rowHeight:24,verticalAlignment:'center',font:{name:'Aptos',size:10,color:ink}};
}
function table(sheet,title,note,headers,widths,rows,formats,name) {
  const end=col(headers.length-1), last=Math.max(6,rows.length+5);
  band(sheet,'A1:D1',title);
  subtitle(sheet,'A2:H2',note);
  sheet.getRange('A4:D4').merge();
  sheet.getRange('A4').values=[[rows.length ? rows.length.toLocaleString('en-US')+(rows.length===1?' record':' records') : 'Awaiting first campaign record']];
  sheet.getRange('A4').format.font={name:'Aptos',size:10,italic:true,color:teal};
  sheet.getRange(`A5:${end}5`).values=[headers];
  if(rows.length) sheet.getRange(`A6:${end}${last}`).values=rows;
  const obj=sheet.tables.add(`A5:${end}${last}`,true,name);
  obj.style='TableStyleLight9';
  obj.showFilterButton=true;
  sheet.getRange(`A5:${end}5`).format={fill:teal,font:{name:'Aptos',bold:true,size:10,color:'#FFFFFF'},wrapText:true,rowHeight:34,verticalAlignment:'center'};
  for(let i=0;i<widths.length;i++) sheet.getRange(`${col(i)}5`).format.columnWidth=widths[i];
  for(const [column,fmt] of Object.entries(formats)) sheet.getRange(`${column}6:${column}${last}`).setNumberFormat(fmt);
  sheet.freezePanes.freezeRows(5);
  return last;
}
function pnlColors(range) {
  range.conditionalFormats.add('cellIs',{operator:'lessThan',formula:0,format:{font:{color:'#962E32'}}});
  range.conditionalFormats.add('cellIs',{operator:'greaterThan',formula:0,format:{font:{color:'#087153'}}});
}
const textValue = v => v==null ? null : String(v);
const label = v => v==null ? null : String(v).replaceAll('_',' ');
export function makeWorkbook(data,research) {
  if(data.campaign_id!=='trade1'||data.environment!=='india_testnet'||!Array.isArray(data.trades))
    throw new Error('Expected fresh trade1 india_testnet ledger');
  const contracts=data.limits?.contracts;
  if(!Number.isInteger(contracts)||contracts<=0) throw new Error('Missing or invalid campaign contract count');
  if(research.campaign_id && research.campaign_id!=='trade1') throw new Error('Foreign review campaign');
  const reviewData=research.campaign_reviews;
  if(!reviewData || !Array.isArray(reviewData.batches) || !reviewData.manager_handoffs) throw new Error('Missing campaign review queue');
  const wb=Workbook.create();
  const [overview,trades,reviews,exits]=['Overview','Trades','Reviews','Exit research'].map(n=>wb.worksheets.add(n));
  for(const s of [overview,trades,reviews,exits]) s.showGridLines=false;
  const ids=new Set(), verified=new Set();
  const ledgerRows=data.trades.map(t=>{
    const id=textValue(t.order_id);
    if(!id||ids.has(id)||t.campaign_id!=='trade1'||typeof t.campaign_verified!=='boolean') throw new Error('Invalid campaign row or duplicated order ID');
    ids.add(id);
    if(t.campaign_verified) {
      if(t.status!=='closed'||t.filled_contracts!==contracts||t.exited_contracts!==contracts||number(t.net_pnl)===null) throw new Error('Incomplete verified trade '+id);
      verified.add(id);
    }
    return [t.symbol,label(t.position),label(t.status),number(t.net_pnl),t.campaign_verified?'Yes':'No',
      number(t.contracts),number(t.entry),number(t.exit),number(t.leverage),number(t.stop_loss),number(t.target),number(t.planned_risk),
      number(t.gross_pnl),number(t.actual_commission),number(t.funding),label(t.exit_reason),
      instant(t.first_fill_at),instant(t.deadline_at),instant(t.close_submitted_at),number(t.close_delay_seconds),instant(t.closed_at),
      number(t.filled_contracts),number(t.exited_contracts),number(t.remaining_contracts),id,(t.exit_order_ids||[]).map(String).join(', ')||null,
      textValue(t.batch_id),t.strategy_version,t.signal_status_at_entry];
  });
  if(verified.size!==data.campaign?.completed) throw new Error('Verified row count disagrees with ledger');
  const last=table(trades,'Trade ledger','Exchange fills and wallet reconciliation • USD amounts • Timestamps in UTC',
    ['Coin','Side','Status','Net P&L $','Verified','Contracts','Entry $','Exit $','Leverage','Stop $','Target $','Planned risk incl. fees $','Gross P&L $','Fees $','Funding $','Exit reason','First fill UTC','Deadline UTC','Close submitted UTC','Submission delay s','Last exit fill UTC','Filled','Exited','Remaining','Entry order ID','Exit order IDs','Batch ID','Skill version','Signal at entry'],
    [14,12,24,18,13,13,16,16,14,16,16,20,18,18,18,23,26,26,26,18,26,12,12,13,23,29,33,29,18],ledgerRows,
    {D:usd,G:price,H:price,I:'0"x"',J:price,K:price,L:usd,M:usd,N:usd,O:usd,Q:datetime,R:datetime,S:datetime,T:'0.00',U:datetime},'CampaignTrades');
  pnlColors(trades.getRange(`D6:D${last}`));
  const ordered=[...reviewData.batches].sort((a,b)=>a.sequence-b.sequence);
  const reviewRows=ordered.map(b=>{
    const item=reviewData.manager_handoffs[b.batch_id]||{}, stats=item.statistics||{}, decision=item.decision||{};
    const valid=item.settlement_verified===true && b.settlement_verified===true;
    if(valid && !(b.order_ids?.length===10 && b.order_ids.every(id=>verified.has(String(id))))) throw new Error('Review membership does not match verified trades');
    return [b.sequence,valid?label(item.status):'awaiting settlement',label(item.outcome),number(stats.net_pnl_usd),stats.wins,stats.losses,stats.breakevens,
      number(stats.mean_net_pnl_usd),number(stats.max_drawdown_usd),number(stats.largest_win_usd),number(stats.largest_loss_usd),number(stats.without_largest_win_usd),
      decision.manager?.findings,decision.manager?.recommendation,label(decision.ceo?.decision),decision.ceo?.rationale,instant(item.reviewed_at),b.order_ids?.join(', '),b.batch_id,
      decision.specialists?.market_data,decision.specialists?.entry_exit,decision.specialists?.risk_costs,decision.specialists?.execution,decision.specialists?.reconciliation_validation,
      decision.candidate?.version,decision.candidate?.hypothesis,decision.candidate?.validation_protocol].map(v=>v??null);
  });
  const lastReview=table(reviews,'Ten-trade reviews','Each group is based on ten verified trades. Scroll right for the manager, CEO and five specialist findings.',
    ['Group','Review status','Outcome','Net P&L $','Wins','Losses','Breakevens','Mean net $','Max drawdown $','Largest win $','Largest loss $','Net ex. largest win $','Manager findings','Recommendation','CEO decision','CEO rationale','Reviewed UTC','Entry order IDs','Review ID','Market data','Entry / exit','Risk and costs','Execution','Independent validation','Candidate version','Hypothesis','Validation protocol'],
    [13,24,15,18,12,12,15,17,18,18,18,20,55,50,24,55,26,42,34,50,50,50,50,50,28,55,55],reviewRows,{D:usd,H:usd,I:usd,J:usd,K:usd,L:usd,Q:datetime},'LearningReviews');
  const shadowRows=[];
  for(const trade of data.trades){
    if(!trade.first_fill_at) continue;
    const shadows=trade.shadow_exits||[];
    for(const minutes of [15,30]){
      const item=shadows.find(x=>x.minutes===minutes)||{};
      const available=['estimated','actual_early_exit'].includes(item.status);
      const net=available?number(item.net_pnl):null;
      const actual=trade.campaign_verified?number(trade.net_pnl):null;
      const paired=actual!==null&&net!==null;
      shadowRows.push([trade.symbol,String(trade.order_id),minutes,label(item.status)||'pending',actual,net,paired?net-actual:null,
        paired?'Yes':'No',number(item.exit_price),number(item.fees),number(item.funding),instant(item.observed_at),item.method??null,item.reason??null]);
    }
  }
  const lastShadow=table(exits,'Exit research','Same entries at 15 and 30 minutes • Difference = hypothetical net less actual net • Blank values await evidence',
    ['Coin','Entry order ID','Hold min','Evidence status','Actual net $','Shadow net $','Difference $','Comparable','Shadow exit $','Shadow fees $','Shadow funding $','Observation UTC','Method','Evidence notes'],
    [15,23,14,22,18,18,18,16,18,18,20,26,55,55],shadowRows,{E:usd,F:usd,G:usd,I:price,J:usd,K:usd,L:datetime},'ExitComparisons');
  for(const [colName,w] of Object.entries({A:24,B:19,C:4,D:23,E:20,F:4,G:22,H:21}))
    overview.getRange(colName+'1').format.columnWidth=w;
  band(overview,'A1:H1','Trade1  /  Delta demo campaign',navy,46,20);
  subtitle(overview,'A2:H2','Bitcoin  ·  Ethereum  ·  Solana  ·  Dogecoin  ·  XRP     |     Delta India testnet perpetuals');
  const elapsed='USD after exchange fees and funding';
  const blocks=[
    ['A4:B4','Verified trades','A5:B6',`=COUNTIF(Trades!E6:E${last},"Yes")`,'#,##0" / 10,000"'],
    ['D4:E4','Verified trades net P&L','D5:E6',`=SUMIF(Trades!E6:E${last},"Yes",Trades!D6:D${last})`,usd],
    ['G4:H4','After-cost win rate','G5:H6',`=IF(A5=0,"",COUNTIFS(Trades!E6:E${last},"Yes",Trades!D6:D${last},">0")/A5)`,'0.0%'],
    ['A8:B8','Completed reviews','A9:B10',`=COUNTIF(Reviews!B6:B${lastReview},"reviewed")`,'#,##0" / 1,000"'],
    ['D8:E8','Mean net per verified trade','D9:E10','=IF(A5=0,"",D5/A5)',usd],
    ['G8:H8','Reviews due','G9:H10','=MAX(0,INT(A5/10)-A9)','#,##0']
  ];
  for(const [title,caption,address,formula,fmt] of blocks){
    band(overview,title,caption,teal,25,11);
    const box=overview.getRange(address);box.merge();
    box.format={fill:'#F0F5F4',font:{name:'Aptos',size:19,bold:true,color:navy},verticalAlignment:'center',rowHeight:23};
    box.setNumberFormat(fmt);overview.getRange(address.split(':')[0]).formulas=[[formula]];
  }
  band(overview,'A12:H12','Campaign rules',navy,26,12);
  const notes=[
    `One batch covers four eligible coins, with ${contracts} contracts per coin. The holding clock starts at the first confirmed fill.`,
    'Exchange stop and target can close earlier. At 10 minutes the worker submits a reduce-only close for the remaining quantity.',
    'Planned risk up to $10 per trade including fees. Daily loss plus open risk up to $30 per IST day. Leverage up to 5×. Margin use up to 80%.'
  ];
  for(let i=0;i<notes.length;i++)subtitle(overview,`A${13+i}:H${13+i}`,notes[i]);
  band(overview,'A17:H17','Read the ledger',navy,26,12);
  for(const [i,guide] of [
    `Trades  /  Check each position, its two fill prices, fees, deadline and exit reason. Verified means all ${contracts} contracts settled.`,
    'Reviews  /  Every 10 verified closes, check group P&L, drawdown, manager findings and the CEO decision.',
    'Exit research  /  Compare hypothetical 15- and 30-minute exits against the actual trade on the same entry.',
    'Summary returns use '+elapsed+'. Win rate and mean appear after the first verified close.'
  ].entries()) subtitle(overview,`A${18+i}:H${18+i}`,guide);
  overview.getRange('A23').values=[['Ledger snapshot (IST)']];
  overview.getRange('B23:C23').merge();overview.getRange('B23').values=[[instant(data.as_of,5.5)]];
  overview.getRange('B23').setNumberFormat(datetime);
  overview.getRange('D23').values=[['Comparable 15m / 30m']];
  overview.getRange('E23').formulas=[[`=COUNTIFS('Exit research'!H6:H${lastShadow},"Yes",'Exit research'!C6:C${lastShadow},15)&" / "&COUNTIFS('Exit research'!H6:H${lastShadow},"Yes",'Exit research'!C6:C${lastShadow},30)`]];
  overview.getRange('A23:E23').format.font={size:10,color:ink,name:'Aptos'};
  overview.getRange('A25').values=[['Account daily loss (USD)']];
  overview.getRange('B25').values=[[number(data.campaign.daily_loss_usd)]];
  overview.getRange('B25').setNumberFormat(usd);
  overview.getRange('D25').values=[['Latest batch check']];
  overview.getRange('E25').values=[[label(data.entry_preview?.status)]];
  overview.getRange('G25').values=[['Worker snapshot']];
  overview.getRange('H25').values=[[label(data.execution?.status || data.worker_mode)]];
  subtitle(overview,'A26:H26','Account daily loss includes earlier activity on the same IST day. All settled P&L includes partial Trade1 lots.');
  overview.getRange('A28').values=[['All settled net P&L ($)']];
  overview.getRange('B28').formulas=[[`=SUMIF(Trades!C6:C${last},"closed",Trades!D6:D${last})`]];
  overview.getRange('B28').setNumberFormat(usd);
  wb.recalculate();
  return wb;
}
async function main(){
  const snapshotArg=process.argv.indexOf('--snapshot-dir');
  const input=snapshotArg<0?run:path.resolve(process.argv[snapshotArg+1]);
  const output=snapshotArg<0?directory:input;
  const load=async f=>JSON.parse(await fs.readFile(path.join(input,f),'utf8'));
  const [data,research]=await Promise.all([load('ledger.json'),load('reviews.json')]);
  const book=makeWorkbook(data,research);
  const target=path.join(output,'trade1.xlsx');
  const tmp=path.join(output,`trade1.pending-${process.pid}.xlsx`);
  try{
    const file=await SpreadsheetFile.exportXlsx(book);
    await file.save(tmp);
    await fs.rename(tmp,target);
  }finally{
    await fs.rm(tmp,{force:true});
    await fs.rm(tmp+'.inspect.ndjson',{force:true});
  }
}
if(process.argv[1] && path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) await main();

