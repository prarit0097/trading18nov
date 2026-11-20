process.env.TZ='UTC';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {gunzipSync}=require('node:zlib');
const {createHash}=require('node:crypto');
const fmz=require('./fmz-wasm-engine.cjs');
const read=f=>fs.readFileSync(path.join(__dirname,f));
const write=(f,v)=>fs.writeFileSync(path.join(__dirname,f),JSON.stringify(v));
const sha=b=>createHash('sha256').update(b).digest('hex');
(async()=>{
    await new Promise(resolve=>setTimeout(resolve,450));
    const data=read('round33-4899-input.json.gz');
    assert.equal(sha(data),'648652411370c83bfaa64e038ae3b360d0d66139aecde8d6f328b61b607720fe');
    const scope=JSON.parse(gunzipSync(data)).scope['2021-05-01'];
    const requests=[];
    global.__offlineProbe=url=>{
        const u=new URL(url),q=u.searchParams;
        assert.equal(u.origin+u.pathname,'https://q.fmz.com/data/history');
        const [currency,kind]=q.get('symbol').split('.');
        assert.equal(currency,'ETH_USDT');
        assert.equal(q.get('eid'),'Futures_Binance');
        assert.equal(Number(q.get('period')),900000);
        const m=scope.market[kind],from=1000*Number(q.get('from')),to=1000*Number(q.get('to'));
        const rows=m.data.filter(x=>from<=x[0]&&x[0]<=to);
        requests.push([kind,from,to,rows.length]);
        return JSON.stringify({detail:m.detail,schema:m.schema,data:rows});
    };
    function run(first){
        const context=fmz.VCtx({start:'2021-05-01 00:00:00',end:'2021-05-01 01:00:00',period:'30m',basePeriod:'15m',
            exchanges:[{eid:'Futures_Binance',currency:'ETH_USDT'}]});
        const s=context.scope,E=s.exchange;
        const clock=()=>s.Date.now();
        const c=[];
        function call(k,args=[]){
            const before=clock();const got=E[k](...args);
            c.push({call:k,args,start:before,end:clock(),got});
            return got;
        }
        function trade(direction){
            call('SetDirection',[direction]);
            const action=direction==='buy'||direction==='closesell'?'Buy':'Sell';
            assert.ok(call(action,[-1,.5]));
            return call('GetPosition');
        }
        try{
            call('SetContractType',['swap']);call('SetMarginLevel',[20]);
            const start=call('GetAccount');assert.equal(start.Balance,10000);
            assert.deepEqual(call('GetPosition'),[]);
            const one=trade(first);
            const both=trade(first==='sell'?'buy':'sell');
            const increased=trade('sell');
            const shortOnly=trade('closebuy');
            const reopened=trade('buy');
            assert.deepEqual([one.length,both.length,increased.length,shortOnly.length,reopened.length],[1,2,2,1,2]);
            return {first,one,both,increased,shortOnly,reopened,trace:c};
        }finally{context.Join();}
    }
    const results=[run('sell'),run('buy')];
    write('round37-5774-native-position-order.json',{engine_sha256:sha(read('fmz-wasm-engine.cjs')), market_sha256:sha(data),requests,results});
})().catch(e=>{write('round37-5774-native-position-error.json',String(e.stack||e));process.exit(1);});
