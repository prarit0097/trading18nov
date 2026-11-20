const fs = require('node:fs');
const acorn = require('acorn');
const walk = require('acorn-walk');
const {analyze} = require('eslint-scope');

const [candidates, metadata, output] = process.argv.slice(2);
const read = filename => JSON.parse(fs.readFileSync(filename, 'utf8'));
const APIs = read(metadata);
const globals = new Set([...APIs.global, ...Object.getOwnPropertyNames(globalThis), 'undefined', 'NaN', 'Infinity', '_']);
const unsupportedGlobals = /^(?:\$|_G|GetCommand|GetChannelData|SetChannelData|HttpQuery(?:_Go)?|Dial|Mail(?:_Go)?|DBExec|GetMeta|EventLoop|fetch|process|os|require|module|Buffer|globalThis|global|Function|eval|setTimeout|setInterval|__\w+)$/;
const external = /^(?:GetDepth|GetTrades|GetIndex|GetTickers|GetRawJSON|GetMeta|GetMarkets|GetData|SetData|SetCurrency|SetProxy|IO|Go)$/;
const orders = /^(?:Buy|Sell|CreateOrder|CreateConditionOrder)$/;
const futureAPIs = /^(?:SetContractType|SetDirection|SetMarginLevel|GetContractType|GetPositions?)$/;

function screen(item) {
  let ast;
  try { ast = acorn.parse(item.code, {ecmaVersion: 2022, ranges: true}); }
  catch (error) { return {reason: `Source has JavaScript syntax error at line ${error.loc.line}`}; }
  const unresolved = analyze(ast, {ecmaVersion: 2022, ignoreEval: true, optimistic: true}).globalScope.through;
  const assigned = new Set(unresolved.filter(ref => ref.isWrite()).map(ref => ref.identifier.name));
  const used = new Set(unresolved.map(ref => ref.identifier.name));
  const plottingRefs = new Set();
  let localPersistence = false;
  const implicit = [...used].filter(name => !globals.has(name) && !assigned.has(name) && !Object.hasOwn(item.args, name));
  const methods = new Set();
  const contracts = new Set();
  let random = false;
  let network = false;
  let hasFiniteExit = false;
  walk.simple(ast, {
    ImportExpression() { network = true; },
    CallExpression(node) {
      if (node.callee.name === '_G' && (node.arguments.length === 2 || node.arguments[0]?.value === null)) localPersistence = true;
      if (node.callee.type !== 'MemberExpression') return;
      const {object, property, computed} = node.callee;
      const method = computed ? property.value : property.name;
      if (object.name === 'Math' && method === 'random') random = true;
      if (orderOrVenueCall(method)) methods.add(method);
      if (method === 'SetContractType') {
        const value = node.arguments[0];
        contracts.add(value?.value ?? item.args[value?.name] ?? '(dynamic)');
      }
    },
    MemberExpression(node) {
      const name = node.computed ? node.property.value : node.property.name;
      if (node.object.name === 'exchange' && orderOrVenueCall(name)) methods.add(name);
    },
    ThrowStatement() { hasFiniteExit = true; },
  });
  walk.ancestor(ast, {CallExpression(node, parents) {
    const method = node.callee;
    if (method.type === 'MemberExpression' && method.object.name === '$' &&
        /^(?:PlotLine|PlotHLine|PlotDot|PlotFlag|PlotBar)$/.test(method.property.name) &&
        parents.at(-2).type === 'ExpressionStatement') plottingRefs.add(method.object.start);
  }});
  const plotting = used.has('$') && unresolved.filter(r => r.identifier.name === '$').every(r => plottingRefs.has(r.identifier.start));
  const blocked = [...used].filter(name => unsupportedGlobals.test(name) && !(name === '$' && plotting));
  const requiredData = [...methods].filter(name => external.test(name));
  const conditionOrders = [...methods].filter(name => /ConditionOrder/.test(name));
  const futures = [...methods].some(name => futureAPIs.test(name));
  const maker = [...methods].some(name => orders.test(name));
  const stop = blocked.length ? `Deployment or host API references ${blocked.sort().join(', ')}`
    : network ? 'Source dynamically imports an external module'
    : requiredData.length ? `Original external-market inputs required by ${requiredData.sort().join(', ')}`
    : random ? 'Source uses unseeded Math.random()'
    : !maker ? 'No native order placement in the standalone source'
    : implicit.length ? `Public defaults or declarations missing for ${implicit.sort().join(', ')}`
    : conditionOrders.length ? 'Condition orders need independently reconciled native trigger and fill data'
    : [...contracts].some(contract => contract !== 'swap') ? `Requires contract type ${[...contracts].join(', ')}`
    : null;
  return {reason: stop, futures, plotting, localPersistence, hasFiniteExit, methods: [...methods].sort()};
}

function orderOrVenueCall(method) {
  return typeof method === 'string' && (/^[A-Z]/.test(method) || orders.test(method));
}

const records = read(candidates).map(item => ({id: item.id, ...screen(item)}));
fs.writeFileSync(output, JSON.stringify(records) + '\n');
