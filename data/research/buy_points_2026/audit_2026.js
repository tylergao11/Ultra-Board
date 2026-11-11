const fs=require('fs'),path=require('path');
const root=process.cwd();
const total=JSON.parse(fs.readFileSync(path.join(root,'一字首开研究总表.json'),'utf8'));
const records=total.一字首开股票与数据.filter(x=>String(x.关注日期||'').startsWith('2026-'));
const dayDirs=fs.readdirSync(path.join(root,'data/kaipanla/raw')).filter(x=>/^2026-\d\d-\d\d$/.test(x)).sort();
const poolCache=new Map();
function pool(date){if(poolCache.has(date))return poolCache.get(date);const p=path.join(root,`data/kaipanla/raw/${date}/zt_pool.json`);const v=fs.existsSync(p)?(JSON.parse(fs.readFileSync(p,'utf8')).stocks||[]):[];poolCache.set(date,v);return v;}
function strictRow(row){return !!(row&&Array.isArray(row.raw)&&row.raw.length>17&&row.raw[16]!==null&&row.raw[17]!==null&&row.raw[16]!==''&&row.raw[17]!==''&&+row.raw[16]===0&&+row.raw[17]===0);}
function bars(code){const p=path.join(root,`data/research/buy_points_2026/ths_kline/${code}-2026-00.js`);if(!fs.existsSync(p))return[];const s=fs.readFileSync(p,'utf8'),m=s.match(/\(\{"data":"([\s\S]*?)"\}\)/);if(!m)return[];return m[1].split(';').filter(Boolean).map(r=>{const a=r.split(',');return{date:`${a[0].slice(0,4)}-${a[0].slice(4,6)}-${a[0].slice(6,8)}`,open:+a[1],high:+a[2],low:+a[3],close:+a[4]};});}
const firstOpenMismatches=[],sourceMismatches=[],missingFormal=[];
const aliases={'AI应用':['AI应用','AI视频','短剧','AIGC'],'农业':['农业','农药','种植','水产品'],'消费':['消费','零售','食品饮料','白酒','酿酒','乳业','旅游','酒店'],'消费电子':['消费电子','AI PC','AI眼镜'],'金融概念':['金融概念','证券','金融'],'机器人':['机器人','减速器'],'算力':['算力','液冷'],'芯片':['芯片','存储','金刚石'],'化工':['化工','PTFE'],'医药':['医药','疫苗','医药零售'],'低空经济':['低空经济','飞行汽车'],'通信':['通信','高速连接'],'锂电':['锂电','固态电池'],'核电':['核电','可控核聚变']};
const confirmed={'002674':['机器人']};
const confirmedByDate={'2026-01-12':{'300986':['AI应用']}};
const conceptRoot=path.join(root,'data/kaipanla/concepts_current'),conceptDirs=fs.existsSync(conceptRoot)?fs.readdirSync(conceptRoot):[],conceptCache=new Map();
function conceptAttrs(code){if(conceptCache.has(code))return conceptCache.get(code);const out=[];for(const dir of conceptDirs){const p=path.join(conceptRoot,dir,`${code}.json`);if(!fs.existsSync(p))continue;try{const j=JSON.parse(fs.readFileSync(p,'utf8'));for(const list of [j.concepts,j.raw_response?.List,j.raw_response?.ListJX])if(Array.isArray(list))for(const v of list){const name=Array.isArray(v)?v[1]:v?.CName;if(name)out.push(name);}}catch{}}const v=[...new Set(out)];conceptCache.set(code,v);return v;}
function attrs(code,row,date){const known=total.一字首开股票与数据.filter(x=>x.股票代码===code&&Array.isArray(x.开盘啦完整属性集)).flatMap(x=>x.开盘啦完整属性集);return [...new Set([row?.theme,row?.theme_tags_text,Array.isArray(row?.raw)?row.raw[12]:null,...known,...conceptAttrs(code),...(confirmed[code]||[]),...(confirmedByDate[date]?.[code]||[])].filter(Boolean))];}
function attributeMatches(main,value){const tokens=String(value).split(/[、,，|；;]/).map(x=>x.trim());const map={'机器人概念':'机器人','种植业':'种植','锂电池':'锂电'};return tokens.some(t=>(aliases[main]||[main]).includes(map[t]||t));}
function themeHit(main,list){return list.some(x=>attributeMatches(main,x));}
const pressureHits=[];
const pkUnopenedHits=[];
const pkAllHits=[],pkPeers=[],pkMissingPrice=[];
const coverage=[],priceConflicts=[];
const barCache=new Map();function barsCached(code){if(!barCache.has(code))barCache.set(code,bars(code));return barCache.get(code);}
function recordStart(record){if(record.底稿首板日期)return record.底稿首板日期;const match=String(record.底稿板序原文||'').match(/(\d{2})-(\d{2})/);return match?`${String(record.关注日期).slice(0,4)}-${match[1]}-${match[2]}`:null;}
for(const d of records){
 const formal=d;
 const start=recordStart(formal);if(!start){missingFormal.push({code:d.股票代码,name:d.股票,recordKey:d.底稿记录键,missing:'底稿首板日期且板序原文无可推导日期'});continue;}
 const stockBars=bars(d.股票代码),barDates=dayDirs.filter(x=>x>=start&&x<=(d.首开日期||dayDirs.at(-1)));
 for(const date of barDates){const row=pool(date).find(x=>x.code===d.股票代码),bar=stockBars.find(x=>x.date===date);if(row&&bar){const flat=bar.open===bar.high&&bar.high===bar.low&&bar.low===bar.close;if(strictRow(row)!==flat)priceConflicts.push({code:d.股票代码,name:d.股票,date,raw16:row.raw?.[16],raw17:row.raw?.[17],bar});}}
 const focusDate=d.关注日期,stockTradeDates=stockBars.map(x=>x.date),sequenceDates=((stockTradeDates.includes(focusDate)?stockTradeDates:dayDirs)).filter(x=>x>=start),focusIndex=sequenceDates.indexOf(focusDate),strictDates=[];
 if(focusIndex>=0){for(let i=focusIndex;i>=0;i-=1){const date=sequenceDates[i],row=pool(date).find(x=>x.code===d.股票代码);if(!strictRow(row))break;strictDates.unshift(date);}}
 const needsKline=formal.公告污染!==true;
 coverage.push({recordKey:formal.底稿记录键,code:d.股票代码,name:d.股票,start,recordedFirstOpen:d.首开日期,hasKline:stockBars.length>0,needsKline,strictDates,main:formal.唯一主炒作属性,hasAttributes:Array.isArray(formal.开盘啦完整属性集)&&formal.开盘啦完整属性集.length>0});
 const nextTradeDate=focusIndex>=0?sequenceDates[focusIndex+1]:null,actualFirstOpen=nextTradeDate&&!strictRow(pool(nextTradeDate).find(y=>y.code===d.股票代码))?nextTradeDate:null;
 const hasRecordedFirstOpen=Boolean(d.首开日期);
 if(!strictDates.length||(hasRecordedFirstOpen&&(!actualFirstOpen||actualFirstOpen!==d.首开日期)))firstOpenMismatches.push({code:d.股票代码,name:d.股票,focus:focusDate,recorded:d.首开日期,actual:actualFirstOpen,segmentStrictDates:strictDates,recordKey:formal.底稿记录键});
 if(!strictDates.length)continue;
 const firstStrict=strictDates[0];
 const expectedSources=strictDates.map(x=>`data/kaipanla/raw/${x}/zt_pool.json`);
 const got=formal.一字压制属性来源||[];
 if(JSON.stringify(expectedSources)!==JSON.stringify(got))sourceMismatches.push({recordKey:formal.底稿记录键,code:d.股票代码,name:d.股票,recorded:d.首开日期,actualFirstOpen,expectedSources,got});
 for(const date of strictDates){
  const p=pool(date),self=p.find(x=>x.code===d.股票代码);if(!self)continue;
  for(const o of p){if(o.code===d.股票代码||+o.boards<=+self.boards||!strictRow(o))continue;const list=attrs(o.code,o,date);if(themeHit(formal.唯一主炒作属性,list))pressureHits.push({recordKey:formal.底稿记录键,candidate:d.股票,code:d.股票代码,main:formal.唯一主炒作属性,date,selfHeight:+self.boards,opponent:o.name,opponentCode:o.code,opponentHeight:+o.boards,matchedAttrs:list.filter(x=>(aliases[formal.唯一主炒作属性]||[formal.唯一主炒作属性]).some(a=>String(x).includes(a))),current:formal.压制判断});}
 }
 if(actualFirstOpen){
  const p=pool(actualFirstOpen),self=p.find(x=>x.code===d.股票代码);let targetHeight=self?+self.boards:null;
  if(!targetHeight){const prevRows=dayDirs.filter(x=>x<actualFirstOpen&&x>=firstStrict).map(x=>pool(x).find(y=>y.code===d.股票代码)).filter(Boolean);const last=prevRows.at(-1);targetHeight=last?+last.boards+1:(+formal.PK候选身位||0)+1;}
  for(const o of p){if(o.code===d.股票代码||+o.boards<targetHeight||!strictRow(o))continue;const list=attrs(o.code,o,actualFirstOpen);if(themeHit(formal.唯一主炒作属性,list))pkUnopenedHits.push({candidate:d.股票,code:d.股票代码,main:formal.唯一主炒作属性,recordedFirstOpen:d.首开日期,actualFirstOpen,targetHeight,opponent:o.name,opponentCode:o.code,opponentHeight:+o.boards,matchedAttrs:list.filter(x=>(aliases[formal.唯一主炒作属性]||[formal.唯一主炒作属性]).some(a=>String(x).includes(a))),current:formal.同题材PK结果});}
  const prevDate=dayDirs.filter(x=>x<actualFirstOpen).at(-1),prevPool=pool(prevDate),selfPrev=prevPool.find(x=>x.code===d.股票代码),candidatePrevHeight=selfPrev?+selfPrev.boards:Math.max(1,targetHeight-1);
  const cb=barsCached(d.股票代码),ci=cb.findIndex(x=>x.date===actualFirstOpen),candidateAuction=ci>0?+(100*(cb[ci].open/cb[ci-1].close-1)).toFixed(4):null;
  for(const oPrev of prevPool){if(oPrev.code===d.股票代码||+oPrev.boards<candidatePrevHeight)continue;const list=attrs(oPrev.code,oPrev,prevDate);if(!themeHit(formal.唯一主炒作属性,list))continue;const oNow=p.find(x=>x.code===oPrev.code),unopened=strictRow(oNow),ob=barsCached(oPrev.code),oi=ob.findIndex(x=>x.date===actualFirstOpen);if(!oNow&&oi<0)continue;let oppAuction=oNow?.open_pct??null;if(oppAuction===null&&oi>0)oppAuction=+(100*(ob[oi].open/ob[oi-1].close-1)).toFixed(4);
   pkPeers.push({recordKey:formal.底稿记录键,candidate:d.股票,code:d.股票代码,main:formal.唯一主炒作属性,date:actualFirstOpen,candidatePrevHeight,targetHeight,candidateAuction,opponent:oPrev.name,opponentCode:oPrev.code,opponentPrevHeight:+oPrev.boards,opponentAuction:oppAuction,opponentUnopened:unopened,matchedAttrs:list.filter(x=>(aliases[formal.唯一主炒作属性]||[formal.唯一主炒作属性]).some(a=>String(x).includes(a)))});
   if(oppAuction===null&&!unopened)pkMissingPrice.push({candidate:d.股票,date:actualFirstOpen,opponent:oPrev.name,opponentCode:oPrev.code});
   const loses=unopened||(candidateAuction!==null&&oppAuction!==null&&candidateAuction<oppAuction-0.0001);
   if(loses)pkAllHits.push({candidate:d.股票,code:d.股票代码,main:formal.唯一主炒作属性,date:actualFirstOpen,candidatePrevHeight,targetHeight,candidateAuction,opponent:oPrev.name,opponentCode:oPrev.code,opponentPrevHeight:+oPrev.boards,opponentAuction:oppAuction,opponentUnopened:unopened,matchedAttrs:list.filter(x=>(aliases[formal.唯一主炒作属性]||[formal.唯一主炒作属性]).some(a=>String(x).includes(a))),current:formal.同题材PK结果});
  }
 }
}
const output={status:'审计进行中；疑点扫描结果不等于最终裁决，禁止据此计算收益',scope:'总表全部2026年关注记录',recordCount:records.length,limitations:['属性扫描使用现有完整属性与快照联合检索，命中需要逐项核验；未命中不代表完整查询通过','日线不能提供首次开板时间；全组一字开盘比较必须补充开板时间','原始涨停池缺行不自动证明盘中未封板','补涨和公告污染尚未逐条重新核验','同一股票的多段严格一字至首开分别核验，不因更早一段存在而自动删除后段'],coverage,priceConflicts,missingFormal,firstOpenMismatches,sourceMismatches,pressureHits,pkUnopenedHits,pkPeers,pkAllHits,pkMissingPrice};
if(process.argv.includes('--save')){fs.writeFileSync(path.join(root,'data/research/buy_points_2026/audit_2026_findings.json'),JSON.stringify(output,null,2)+'\n','utf8');console.log(JSON.stringify({recordCount:records.length,dateSuspects:firstOpenMismatches.length,priceConflicts:priceConflicts.length,missingRequiredKline:coverage.filter(x=>x.needsKline&&!x.hasKline).length,missingPKPrice:pkMissingPrice.length,pressurePairs:pressureHits.length,pkPairs:pkAllHits.length},null,2));}else console.log(JSON.stringify(output,null,2));
