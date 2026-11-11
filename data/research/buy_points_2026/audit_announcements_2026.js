const fs = require('fs');
const path = require('path');

const root = process.cwd();
const total = JSON.parse(fs.readFileSync(path.join(root, '一字首开研究总表.json'), 'utf8'));
const records = total['一字首开股票与数据'].filter((record) => String(record.关注日期 || '').startsWith('2026-'));
const days = fs.readdirSync(path.join(root, 'data/kaipanla/raw')).filter((date) => /^2026-\d{2}-\d{2}$/.test(date)).sort();
const keywords = ['股权转让', '并购重组', '控制权', '实际控制人', '实控人变更', '重大资产重组', '资产置换', '主动退市'];
const cache = new Map();

function inferredStart(record) {
  if (record.底稿首板日期) return record.底稿首板日期;
  const match = String(record.底稿板序原文 || '').match(/(\d{2})-(\d{2})/);
  return match ? `${String(record.关注日期).slice(0, 4)}-${match[1]}-${match[2]}` : record.关注日期;
}

function rowsFor(date, code) {
  const file = path.join(root, `data/kaipanla/raw/${date}/historical_messages.json`);
  if (!fs.existsSync(file)) return [];
  if (!cache.has(file)) cache.set(file, JSON.parse(fs.readFileSync(file, 'utf8')));
  const hits = [];
  function walk(value) {
    if (!value || typeof value !== 'object') return;
    if (Array.isArray(value) && String(value[0]) === code) hits.push(value);
    for (const child of Object.values(value)) walk(child);
  }
  walk(cache.get(file));
  return hits;
}

const results = [];
for (const record of records) {
  const start = inferredStart(record);
  const end = record.首开日期 || record.关注日期;
  const evidence = [];
  const checkedFiles = [];
  for (const date of days.filter((day) => day >= start && day <= end)) {
    const file = `data/kaipanla/raw/${date}/historical_messages.json`;
    if (!fs.existsSync(path.join(root, file))) continue;
    const rows = rowsFor(date, record.股票代码);
    if (!rows.length) continue;
    checkedFiles.push(file);
    for (const row of rows) {
      const text = row.map((item) => String(item ?? '')).join(' | ');
      const matched = keywords.filter((keyword) => text.includes(keyword));
      if (matched.length) evidence.push({ date, matched, row: row.slice(0, 20) });
    }
  }
  results.push({
    recordKey: record.底稿记录键,
    code: record.股票代码,
    name: record.股票,
    formal: Object.hasOwn(record, '公告污染') ? record.公告污染 : null,
    checkedFiles: [...new Set(checkedFiles)],
    evidence,
  });
}

const output = {
  recordCount: records.length,
  missingFormal: results.filter((item) => item.formal === null),
  falseWithCapitalEvidence: results.filter((item) => item.formal === false && item.evidence.length),
  trueWithoutLocalCapitalEvidence: results.filter((item) => item.formal === true && !item.evidence.length),
  all: results,
};
fs.writeFileSync(path.join(root, 'data/research/buy_points_2026/audit_announcements_2026_findings.json'), `${JSON.stringify(output, null, 2)}\n`, 'utf8');
console.log(JSON.stringify({
  recordCount: output.recordCount,
  missingFormal: output.missingFormal.length,
  falseWithCapitalEvidence: output.falseWithCapitalEvidence.length,
  trueWithoutLocalCapitalEvidence: output.trueWithoutLocalCapitalEvidence.length,
}, null, 2));
