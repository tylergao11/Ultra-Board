const fs = require('fs');

const result = JSON.parse(fs.readFileSync('data/research/buy_points_2026/statistics_2026.json', 'utf8'));
const total = JSON.parse(fs.readFileSync('一字首开研究总表.json', 'utf8'));
const records = total['一字首开股票与数据'];
const samples = result.buySamples;

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

assert(result.status.startsWith('complete:'), '统计状态未完成');
assert(samples.length === 45, `买入样本不是45，实际${samples.length}`);
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

const byCodeDate = new Map(samples.map((sample) => [`${sample.code}|${sample.date}`, sample]));
assert(byCodeDate.get('002578|2026-11-06')?.outcome.consecutiveNextBoards === 2, '闽发铝业时间链错误');
assert(byCodeDate.get('600838|2026-10-26')?.outcome.nextFinalSealed === true, '上海九百次日连板未标记');
for (const key of ['002578|2026-11-06', '601599|2026-11-06', '600838|2026-10-26']) {
  assert(byCodeDate.get(key)?.buyPoint.time == null, `缺少准确回封时刻的样本被写入伪时间：${key}`);
}
assert(byCodeDate.has('601086|2026-09-03'), '国芳集团未计入');
for (const code of ['000892', '002942', '603956', '600078']) assert(!samples.some((sample) => sample.code === code), `已知错误样本仍存在：${code}`);

assert(!Object.hasOwn(total, '2026竞价PK封板统计'), '旧失效统计节点仍存在');
assert(total['2026统计结果']?.买入样本?.length === 45, '总表正式统计未写入45条样本');
assert(JSON.stringify(total['2026统计结果']?.统计摘要) === JSON.stringify(result.statistics), '总表摘要与独立统计文件不一致');

console.log(JSON.stringify({
  verified: true,
  samples: samples.length,
  sealed: result.statistics.buyDayFinalSealed,
  nextBoards: result.statistics.nextDayFinalBoard,
  lowOpen: result.statistics.lowOpenSamples,
  lowOpenLimitDown: result.statistics.lowOpenFinalLimitDown,
}, null, 2));
