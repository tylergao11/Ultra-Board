const fs = require('fs');

const total = JSON.parse(fs.readFileSync('一字首开研究总表.json', 'utf8'));
const audit = JSON.parse(fs.readFileSync('data/research/buy_points_2026/audit_2026_findings.json', 'utf8'));
const buyPointObservations = JSON.parse(fs.readFileSync('data/research/buy_points_2026/buy_point_observations.json', 'utf8'));
const records = total['一字首开股票与数据'].filter((record) => String(record.关注日期 || '').startsWith('2026-'));
const tradingDays = fs.readdirSync('data/kaipanla/raw').filter((date) => /^2026-\d{2}-\d{2}$/.test(date)).sort();
const poolCache = new Map();

function pool(date) {
  if (poolCache.has(date)) return poolCache.get(date);
  const file = `data/kaipanla/raw/${date}/zt_pool.json`;
  const result = fs.existsSync(file) ? (JSON.parse(fs.readFileSync(file, 'utf8')).stocks || []) : [];
  poolCache.set(date, result);
  return result;
}

const barCache = new Map();
function bars(code) {
  if (barCache.has(code)) return barCache.get(code);
  const file = `data/research/buy_points_2026/ths_kline/${code}-2026-00.js`;
  if (!fs.existsSync(file)) return [];
  const text = fs.readFileSync(file, 'utf8');
  const match = text.match(/\(\{"data":"([\s\S]*?)"\}\)/);
  const result = match ? match[1].split(';').filter(Boolean).map((row) => {
    const a = row.split(',');
    return {
      date: `${a[0].slice(0, 4)}-${a[0].slice(4, 6)}-${a[0].slice(6, 8)}`,
      open: +a[1], high: +a[2], low: +a[3], close: +a[4],
    };
  }) : [];
  barCache.set(code, result);
  return result;
}

function round(value, digits = 4) {
  return value == null ? null : +value.toFixed(digits);
}

function priceLimitRate(code) {
  if (/^(300|301|688|689)/.test(code)) return 0.2;
  if (/^(4|8|92)/.test(code)) return 0.3;
  return 0.1;
}

function roundedPrice(value) {
  return Math.floor(value * 100 + 0.5000001) / 100;
}

function inferredLimitPrice(code, previousClose) {
  return roundedPrice(previousClose * (1 + priceLimitRate(code)));
}

function timePart(value) {
  if (!value) return null;
  const match = String(value).match(/(\d{2}:\d{2}:\d{2})/);
  return match ? match[1] : null;
}

function timestampTime(value) {
  if (!value) return null;
  return new Date((+value + 8 * 3600) * 1000).toISOString().slice(11, 19);
}

function equalPrice(a, b) {
  return a != null && b != null && Math.abs(a - b) < 0.0051;
}

const threeFilterPassed = records.filter((record) =>
  record.首开日期 &&
  record.补涨判断 === '非补涨' &&
  String(record.压制判断 || '').startsWith('无') &&
  record.公告污染 === false
);

const rows = threeFilterPassed.map((record) => {
  const stockBars = bars(record.股票代码);
  const index = stockBars.findIndex((bar) => bar.date === record.首开日期);
  const auction = index > 0 ? 100 * (stockBars[index].open / stockBars[index - 1].close - 1) : null;
  const pkLosses = audit.pkAllHits.filter((hit) => hit.code === record.股票代码 && hit.date === record.首开日期);
  const cachedBuyPoint = buyPointObservations.find((item) => item.股票代码 === record.股票代码 && item.首开日期 === record.首开日期) || null;
  return {
    recordKey: record.底稿记录键,
    code: record.股票代码,
    name: record.股票,
    firstOpenDate: record.首开日期,
    main: record.唯一主炒作属性,
    auctionPct: round(auction),
    auctionPassed: auction != null && auction >= 0,
    pkLosses: pkLosses.map((hit) => ({
      opponent: hit.opponent,
      opponentCode: hit.opponentCode,
      opponentUnopened: hit.opponentUnopened,
      candidateAuctionPct: hit.candidateAuction,
      opponentAuctionPct: hit.opponentAuction,
    })),
    provisionalPkPassed: auction != null && auction >= 0 && pkLosses.length === 0,
    cachedBuyPoint: cachedBuyPoint ? {
      openingShape: cachedBuyPoint.首开日开盘形态,
      firstTouchTime: cachedBuyPoint.打板客首次触板时间,
      sealCount: cachedBuyPoint.同花顺封板次数,
      open: cachedBuyPoint.同花顺开盘价,
      limit: cachedBuyPoint.同花顺涨停价,
      low: cachedBuyPoint.同花顺最低价,
      high: cachedBuyPoint.同花顺最高价,
      firstLimitTime: cachedBuyPoint.同花顺首次涨停时间,
      finalLimitTime: cachedBuyPoint.同花顺最终涨停时间,
    } : null,
  };
});

function observationFor(row) {
  if (row.cachedBuyPoint) return row.cachedBuyPoint;
  const stockBars = bars(row.code);
  const index = stockBars.findIndex((bar) => bar.date === row.firstOpenDate);
  if (index < 1) return null;
  const bar = stockBars[index];
  const poolRow = pool(row.firstOpenDate).find((item) => item.code === row.code);
  return {
    derivedFromSavedMarketData: true,
    openingShape: null,
    firstTouchTime: poolRow ? timestampTime(poolRow.first_limit_ts) : null,
    sealCount: poolRow ? 1 : 0,
    open: bar.open,
    limit: poolRow?.price ?? inferredLimitPrice(row.code, stockBars[index - 1].close),
    low: bar.low,
    high: bar.high,
    firstLimitTime: poolRow ? timestampTime(poolRow.first_limit_ts) : null,
    // 开盘啦只保存首次封板时刻。T字回封的准确时刻未落盘时不得拿09:25冒充。
    finalLimitTime: null,
  };
}

function buyPointFor(row) {
  const observation = observationFor(row);
  const stockBars = bars(row.code);
  const index = stockBars.findIndex((bar) => bar.date === row.firstOpenDate);
  if (!observation || index < 1) return { triggered: false, reason: 'missing-observation', observation };
  const bar = stockBars[index];
  const limit = observation.limit ?? inferredLimitPrice(row.code, stockBars[index - 1].close);
  const onePriceOpen = equalPrice(observation.open, limit);
  const opened = observation.low < limit - 0.005;
  const finalSealed = equalPrice(bar.close, limit) && Boolean(pool(row.firstOpenDate).find((item) => item.code === row.code));
  if (onePriceOpen) {
    const resealed = opened && ((+observation.sealCount || 0) >= 2 || timePart(observation.firstLimitTime) > '09:30:00' || finalSealed);
    return {
      triggered: resealed,
      type: resealed ? '一字开板后回封' : (opened ? '一字开板后未回封' : '全天一字未开'),
      time: resealed
        ? (timePart(observation.finalLimitTime) || (observation.derivedFromSavedMarketData ? null : timePart(observation.firstLimitTime)))
        : null,
      finalSealed,
      limit,
      observation,
    };
  }
  const touched = observation.high >= limit - 0.005 || (+observation.sealCount || 0) > 0;
  const firstTouch = timePart(observation.firstTouchTime) || timePart(observation.firstLimitTime);
  const triggered = touched && firstTouch != null && firstTouch < '10:00:00';
  return {
    triggered,
    type: triggered ? '非一字开盘10点前首次上板' : (touched ? (firstTouch ? '10点后首次上板' : '触板时间缺失') : '未触及涨停'),
    time: firstTouch,
    finalSealed,
    limit,
    observation,
  };
}

const provisionalRows = rows.filter((row) => row.provisionalPkPassed);
for (const row of provisionalRows) row.buyPoint = buyPointFor(row);

const allOnePricePeerReviews = audit.pkPeers.filter((peer) => {
  const row = provisionalRows.find((candidate) => candidate.recordKey === peer.recordKey);
  return row && peer.candidateAuction >= 9.5 && peer.opponentAuction >= 9.5 && !peer.opponentUnopened;
}).map((peer) => ({
  ...peer,
  affectsBuySample: Boolean(provisionalRows.find((row) => row.recordKey === peer.recordKey)?.buyPoint?.triggered),
}));

const buySamples = provisionalRows.filter((row) => row.buyPoint?.triggered && !allOnePricePeerReviews.some((review) => review.recordKey === row.recordKey && review.affectsBuySample));

function outcomeFor(row) {
  const stockBars = bars(row.code);
  const buyIndex = stockBars.findIndex((bar) => bar.date === row.firstOpenDate);
  const buyBar = stockBars[buyIndex];
  const nextBar = stockBars[buyIndex + 1] || null;
  const finalSealed = row.buyPoint.finalSealed;
  const nextFinalSealed = Boolean(nextBar && pool(nextBar.date).find((item) => item.code === row.code));
  let consecutiveNextBoards = 0;
  let cursor = buyIndex + 1;
  while (cursor < stockBars.length && pool(stockBars[cursor].date).some((item) => item.code === row.code)) {
    consecutiveNextBoards += 1;
    cursor += 1;
  }
  const sellIndex = finalSealed ? cursor : buyIndex + 1;
  const sellBar = stockBars[sellIndex] || null;
  const expectedLimitDown = nextBar ? roundedPrice(buyBar.close * (1 - priceLimitRate(row.code))) : null;
  return {
    buyPrice: row.buyPoint.limit,
    buyDayFinalSealed: finalSealed,
    nextDate: nextBar?.date ?? null,
    nextOpen: nextBar?.open ?? null,
    nextClose: nextBar?.close ?? null,
    nextLowOpen: Boolean(nextBar && nextBar.open < buyBar.close - 0.005),
    nextCloseRed: Boolean(nextBar && nextBar.close > buyBar.close + 0.005),
    nextFinalSealed: finalSealed && nextFinalSealed,
    nextFinalLimitDown: Boolean(nextBar && equalPrice(nextBar.close, expectedLimitDown)),
    consecutiveNextBoards,
    sellDate: sellBar?.date ?? null,
    sellClose: sellBar?.close ?? null,
    returnPct: sellBar ? round(100 * (sellBar.close / row.buyPoint.limit - 1)) : null,
  };
}

for (const row of buySamples) row.outcome = outcomeFor(row);

function rate(numerator, denominator) {
  return denominator ? round(100 * numerator / denominator, 2) : null;
}

const sealedCount = buySamples.filter((row) => row.outcome.buyDayFinalSealed).length;
const nextBoardCount = buySamples.filter((row) => row.outcome.nextFinalSealed).length;
const lowOpenRows = buySamples.filter((row) => row.outcome.nextLowOpen);
const lowOpenNextBoards = lowOpenRows.filter((row) => row.outcome.nextFinalSealed).length;
const lowOpenRed = lowOpenRows.filter((row) => row.outcome.nextCloseRed).length;
const lowOpenLimitDown = lowOpenRows.filter((row) => row.outcome.nextFinalLimitDown).length;
const returns = buySamples.map((row) => row.outcome.returnPct).filter((value) => value != null);

const statistics = {
  formal2026Records: records.length,
  threeFilterPassed: threeFilterPassed.length,
  auctionPassed: rows.filter((row) => row.auctionPassed).length,
  pkEliminated: rows.filter((row) => row.auctionPassed && row.pkLosses.length).length,
  pkPassedBeforeOpeningTimeTie: provisionalRows.length,
  openingTimeTieReviews: allOnePricePeerReviews.length,
  openingTimeTieAffectsBuySamples: allOnePricePeerReviews.filter((row) => row.affectsBuySample).length,
  buyPointTriggered: buySamples.length,
  buyDayFinalSealed: sealedCount,
  buyDaySealRatePct: rate(sealedCount, buySamples.length),
  nextDayFinalBoard: nextBoardCount,
  nextDayBoardRatePct: rate(nextBoardCount, buySamples.length),
  lowOpenSamples: lowOpenRows.length,
  lowOpenNextBoard: lowOpenNextBoards,
  lowOpenNextBoardRatePct: rate(lowOpenNextBoards, lowOpenRows.length),
  lowOpenCloseRed: lowOpenRed,
  lowOpenCloseRedRatePct: rate(lowOpenRed, lowOpenRows.length),
  lowOpenFinalLimitDown: lowOpenLimitDown,
  lowOpenFinalLimitDownRatePct: rate(lowOpenLimitDown, lowOpenRows.length),
  tailSellReturnSamples: returns.length,
  tailSellAverageReturnPct: returns.length ? round(returns.reduce((sum, value) => sum + value, 0) / returns.length, 2) : null,
  tailSellWinRatePct: rate(returns.filter((value) => value > 0).length, returns.length),
};

const output = {
  status: allOnePricePeerReviews.some((row) => row.affectsBuySample) ? 'working: 存在会影响买入样本的一字开盘PK开板时间待比较' : 'complete: 统计链已重算；同为一字开盘的待比较项不影响买入样本',
  counts: {
    formal2026Records: records.length,
    threeFilterPassed: threeFilterPassed.length,
    missingAuction: rows.filter((row) => row.auctionPct == null).length,
    negativeAuction: rows.filter((row) => row.auctionPct != null && row.auctionPct < 0).length,
    auctionPassed: rows.filter((row) => row.auctionPassed).length,
    provisionalPkEliminated: rows.filter((row) => row.auctionPassed && row.pkLosses.length).length,
    provisionalPkPassed: rows.filter((row) => row.provisionalPkPassed).length,
    provisionalPkPassedMissingBuyPointCache: rows.filter((row) => row.provisionalPkPassed && !row.cachedBuyPoint).length,
  },
  statistics,
  allOnePricePeerReviews,
  buySamples: buySamples.map((row) => ({
    recordKey: row.recordKey,
    code: row.code,
    name: row.name,
    date: row.firstOpenDate,
    main: row.main,
    auctionPct: row.auctionPct,
    buyPoint: row.buyPoint,
    outcome: row.outcome,
  })),
  rows,
};

fs.writeFileSync('data/research/buy_points_2026/statistics_2026.json', `${JSON.stringify(output, null, 2)}\n`, 'utf8');
if (output.status.startsWith('complete:')) {
  total['2026统计结果'] = {
    数据截至: tradingDays.at(-1),
    状态: '已按当前正式口径重算并通过一致性核验',
    统计摘要: statistics,
    买入样本: output.buySamples.map((sample) => ({
      首开日期: sample.date,
      股票代码: sample.code,
      股票: sample.name,
      唯一主炒作属性: sample.main,
      竞价涨幅: sample.auctionPct,
      买点类型: sample.buyPoint.type,
      买点时间: sample.buyPoint.time,
      买入日最终封板: sample.outcome.buyDayFinalSealed,
      次日最终连板: sample.outcome.nextFinalSealed,
      买入后连续封板天数: sample.outcome.consecutiveNextBoards,
      次日低开: sample.outcome.nextLowOpen,
      次日最终跌停: sample.outcome.nextFinalLimitDown,
      尾盘卖出日期: sample.outcome.sellDate,
      尾盘卖出收益率: sample.outcome.returnPct,
    })),
    统计来源: 'data/research/buy_points_2026/statistics_2026.json',
  };
  fs.writeFileSync('一字首开研究总表.json', `${JSON.stringify(total, null, 2)}\n`, 'utf8');
}
console.log(JSON.stringify({ status: output.status, statistics }, null, 2));
