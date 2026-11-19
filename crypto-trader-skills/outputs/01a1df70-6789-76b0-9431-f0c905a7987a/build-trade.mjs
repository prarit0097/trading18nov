import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {Workbook, SpreadsheetFile} from '@oai/artifact-tool';
const dir=path.dirname(fileURLToPath(import.meta.url));
const root=path.resolve(dir,'../..');
const data=JSON.parse(await fs.readFile(path.join(root,'runs/delta-demo-loop/ledger.json'),'utf8'));
const lastTradeRow=Math.max(6,5+data.trades.length);
const wb=Workbook.create();
const summary=wb.worksheets.add('Summary');
const trades=wb.worksheets.add('Trades');
for(const s of [summary,trades]){
  s.showGridLines=false;
  s.getRange('A1:R30').format.font={name:'Arial',size:10,color:'#1F2937'};
  s.getRange('A1:R30').format.columnWidth=17;
}
summary.getRange('A2').values=[['Delta demo trade tracker']];
summary.getRange('A2').format.font={name:'Arial',size:15,bold:true};
summary.getRange('A4:B13').values=[
 ['Snapshot (IST)',new Date(data.as_of)],['Closed trades in ledger',null],['Campaign goal',data.limits?.target_closed ?? 10000],
 ['Ledger realized net P&L (USD)',null],['Next campaign review at',null],['Strategy closed trades',data.review.strategy_sample],
 ['Strategy win rate',data.review.strategy_win_rate],['Daily loss limit (USD)',30],
 ['Maximum lots per batch',data.limits?.max_positions ?? 1],['Last refresh mode',data.execution?.status === 'entry_hold' ? 'Entry hold' : data.worker_mode === 'demo_execution' ? 'Delta demo execution' : 'Read-only']
];
summary.getRange('B4').setNumberFormat('dd-mmm-yyyy hh:mm');
// Store local IST serial explicitly; UTC source remains on the trade row.
summary.getRange('B4').values=[[new Date(Date.parse(data.as_of)+19800000)]];
summary.getRange('B5').formulas=[[`=COUNTIFS(Trades!C6:C${lastTradeRow},"closed")`]];
summary.getRange('B7').formulas=[[`=SUM(Trades!M6:M${lastTradeRow})`]];
summary.getRange('B8').formulas=[['=MIN(B6,10*(INT(B14/10)+1))']];
summary.getRange('B7').setNumberFormat('$0.00');
summary.getRange('B10').setNumberFormat('0.0%');
const validation=data.forward_research?.validation;
summary.getRange('A14:B15').values=[
 ['Verified eligible campaign trades',data.campaign?.completed ?? 0],
 ['Forward validation',validation ? `${validation.status.replaceAll('_',' ')} (${validation.observations}/30)` : 'Awaiting first batch'],
];
summary.getRange('A16:B16').values=[['Distinct coins in normal batch',data.limits?.minimum_distinct_coins ?? 1]];
summary.getRange('A17').values=[['Manual BTC test is excluded from strategy win rate.']];
summary.getRange('A18').values=[['SL/TP run at the exchange. This workbook shows the last refresh.']];
summary.getRange('A19').values=[['Stop slippage, funding and gaps may exceed planned loss.']];
summary.getRange('A20:B21').values=[
 ['Campaign reviews recorded',data.campaign_reviews?.reviewed ?? 0],
 ['Campaign reviews awaiting team',data.campaign_reviews?.awaiting_manager.length ?? 0],
];
summary.getRange('A4:A15').format.columnWidth=38;
summary.getRange('B4:B15').format.columnWidth=36;
trades.getRange('A2').values=[['Trades — USD, Delta india_testnet']];
trades.getRange('A2').format.font={name:'Arial',size:15,bold:true};
trades.getRange('A3').values=[['Source: Delta demo MCP fills, positions and wallet transactions; https://demo.delta.exchange']];
const headers=['Order ID','Position','Status','Requested contracts','Entry','Leverage','Stop-loss','Target','Planned risk incl. fees','Entry fee','Actual fees to date','UPNL (gross)','Final net P&L','Exit','Opened (UTC)','Classification','Version','Filled contracts','Remaining contracts','Batch ID','Batch slot','Signal at entry','Funding (USD)','Market turnover (USD)'];
trades.getRange('A5:X5').values=[headers];
trades.getRange('A5:X5').format={fill:'#26384A',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},wrapText:true,rowHeight:34,verticalAlignment:'center',horizontalAlignment:'center'};
const rows=data.trades.map(t=>[String(t.order_id),`${t.symbol} ${t.position}`,t.status,t.contracts,Number(t.entry),t.leverage,Number(t.stop_loss),Number(t.target),Number(t.planned_risk),Number(t.entry_commission),Number(t.actual_commission),t.unrealized_pnl===null?null:Number(t.unrealized_pnl),t.net_pnl===null?null:Number(t.net_pnl),t.exit===null?null:Number(t.exit),new Date(t.opened_at),t.classification,t.strategy_version]);
const extended=data.trades.map((t,i)=>[...rows[i],t.filled_contracts ?? null,t.remaining_contracts ?? (t.status==='closed'?0:null),t.batch_id ?? null,t.batch_slot ?? null,t.signal_status_at_entry ?? null,t.funding==null?null:Number(t.funding),t.turnover_usd_at_entry==null?null:Number(t.turnover_usd_at_entry)]);
trades.getRange(`A6:X${5+rows.length}`).values=extended;
trades.getRange(`E6:N${5+rows.length}`).setNumberFormat('0.00');
for(const col of ['E','G','H','N']) trades.getRange(`${col}6:${col}${lastTradeRow}`).setNumberFormat('0.00######');
trades.getRange(`W6:W${lastTradeRow}`).setNumberFormat('0.00######');
trades.getRange('R5:X10').format.columnWidth=19;
trades.getRange(`X6:X${lastTradeRow}`).setNumberFormat('#,##0.00');
trades.getRange('T5:T10').format.columnWidth=32;
trades.getRange(`F6:F${5+rows.length}`).setNumberFormat('0"x"');
trades.getRange(`O6:O${5+rows.length}`).setNumberFormat('dd-mmm-yyyy hh:mm:ss');
trades.getRange('A5:A10').format.columnWidth=19;
trades.getRange('B5:B10').format.columnWidth=20;
trades.getRange('O5:O10').format.columnWidth=25;
trades.getRange('P5:P10').format.columnWidth=34;
trades.getRange('Q5:Q10').format.columnWidth=18;
trades.freezePanes.freezeRows(5); trades.freezePanes.freezeColumns(2);
trades.getRange(`L6:M${lastTradeRow}`).conditionalFormats.add('cellIs',{operator:'lessThan',formula:0,format:{font:{color:'#B91C1C'}}});
trades.getRange(`L6:M${lastTradeRow}`).conditionalFormats.add('cellIs',{operator:'greaterThan',formula:0,format:{font:{color:'#15803D'}}});
wb.recalculate();
// Verify the summary responds to a real closed-trade result, then restore inputs.
if(rows.length===1 && rows[0][2]!=='closed'){
  trades.getRange('C6').values=[['closed']];trades.getRange('M6').values=[[-4]];
  wb.recalculate();
  if(summary.getRange('B5').values[0][0]!==1 || summary.getRange('B7').values[0][0]!==-4) throw new Error('Summary recalculation failed');
  trades.getRange('C6').values=[[rows[0][2]]];trades.getRange('M6').values=[[rows[0][12]]];
  wb.recalculate();
}
console.log((await wb.inspect({kind:'table',range:'Summary!A4:B21',tableMaxRows:18,tableMaxCols:2,maxChars:2000})).ndjson);
console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#NULL!',options:{useRegex:true,maxResults:20},maxChars:1000})).ndjson);
for(const [sheet,range,name] of (process.argv.includes('--no-preview') ? [] : [['Summary','A1:F22','summary'],['Trades','A1:I8','trade-entry'],['Trades','J5:Q8','trade-pnl']])){
  const png=await wb.render({sheetName:sheet,range,scale:1.5,format:'png'});
  await fs.writeFile(path.join(dir,`${name}.png`),new Uint8Array(await png.arrayBuffer()));
}
const xlsx=await SpreadsheetFile.exportXlsx(wb);
const pending=path.join(dir,`trade.pending-${process.pid}.xlsx`);
try {
  await xlsx.save(pending);
  const destination=path.join(dir,'trade.xlsx');
  for (const delay of [200,400,800,0]) {
    try {
      await fs.rename(pending,destination);
      break;
    } catch (error) {
      if (!delay || !['EPERM','EBUSY','EACCES'].includes(error.code)) throw error;
      await new Promise(resolve=>setTimeout(resolve,delay));
    }
  }
} finally {
  await fs.rm(pending,{force:true});
  await fs.rm(`${pending}.inspect.ndjson`,{force:true});
}
console.log('Exported trade.xlsx');
