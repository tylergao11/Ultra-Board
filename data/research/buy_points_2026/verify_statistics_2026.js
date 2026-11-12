const fs = require('fs');

const result = JSON.parse(fs.readFileSync('data/research/buy_points_2026/statistics_2026.json', 'utf8'));
const total = JSON.parse(fs.readFileSync('一字首开研究总表.json', 'utf8'));
const tradeStudy = JSON.parse(fs.readFileSync('一字首开买卖研究表.json', 'utf8'));
const archivedStatistics = tradeStudy.迁移前统计存档['2026统计结果'];
const records = total['一字首开股票与数据'];
const samples = result.buySamples;

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

assert(result.status.startsWith('complete:'), '统计状态未完成');
assert(samples.length === result.statistics.buyPointTriggered, '买入样本数与统计摘要不一致');
assert(new Set(samples.map((sample) => sample.recordKey)).size === samples.length, '买入样本记录键重复');
assert(result.statistics.buyDayFinalSealed === samples.filter((sample) => sample.outcome.buyDayFinalSealed).length, '封板数量不一致');
assert(result.statistics.nextDayFinalBoard === samples.filter((sample) => sample.outcome.nextFinalSealed).length, '次日连板数量不一致');
assert(result.statistics.lowOpenSamples === samples.filter((sample) => sample.outcome.nextLowOpen).length, '低开数量不一致');
assert(result.statistics.lowOpenFinalLimitDown === samples.filter((sample) => sample.outcome.nextLowOpen && sample.outcome.nextFinalLimitDown).length, '低开跌停数量不一致');

for (const sample of samples) {
  const formal = records.find((record) => record.底稿记录键 === sample.recordKey);
  assert(formal, `正式记录缺失：${sample.recordKey}`);
  assert(formal.补涨判断 === '非补涨', `样本仍属补涨：${sample.recordKey}`);
  assert(String(formal.压制判断).startsWith('无'), `样本仍有压制：${sample.recordKey}`);
  assert(formal.公告污染 === false, `样本仍有公告污染：${sample.recordKey}`);
  assert(sample.auctionPct >= 0, `样本竞价低于0轴：${sample.recordKey}`);
  assert(sample.buyPoint.triggered, `样本未触发买点：${sample.recordKey}`);
}

assert(!Object.hasOwn(total, '2026竞价PK封板统计'), '旧失效统计节点仍存在');
assert(!Object.hasOwn(total, '2026统计结果'), '交易统计仍混在静态股票表');
assert(archivedStatistics?.买入样本?.length === samples.length, '迁入统计样本数不一致');
assert(JSON.stringify(archivedStatistics?.统计摘要) === JSON.stringify(result.statistics), '迁入摘要与原统计文件不一致');

console.log(JSON.stringify({
  verified: true,
  scope: '迁移前竞价PK统计资料',
  samples: samples.length,
  sealed: result.statistics.buyDayFinalSealed,
  nextBoards: result.statistics.nextDayFinalBoard,
  lowOpen: result.statistics.lowOpenSamples,
  lowOpenLimitDown: result.statistics.lowOpenFinalLimitDown,
}, null, 2));
