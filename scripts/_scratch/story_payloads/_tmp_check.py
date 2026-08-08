# -*- coding: utf-8 -*-
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

ROOT = Path(r"C:\Ai\Ultra-Board")
LIMIT = ROOT / "data" / "ths" / "limit_pool"
OUT = ROOT / "scripts" / "_scratch" / "story_payloads"
OUT.mkdir(parents=True, exist_ok=True)


def pool_map(day: str) -> dict[str, str]:
    data = json.loads((LIMIT / f"{day}.json").read_text(encoding="utf-8-sig"))
    return {str(r["code"]).zfill(6): str(r["name"]).strip() for r in data.get("stocks") or []}


def stocks(day: str, rows: list[tuple[str, str]]) -> list[dict]:
    m = pool_map(day)
    out = []
    for code, story in rows:
        code = code.zfill(6)
        if code not in m:
            raise KeyError(f"{day} missing {code}")
        out.append({"code": code, "name": m[code], "story": story})
    return out


def write(day: str, stories: list[dict]) -> None:
    # uniqueness check
    seen = []
    for s in stories:
        for st in s["stocks"]:
            seen.append(st["code"])
    if len(seen) != len(set(seen)):
        from collections import Counter
        c = Counter(seen)
        raise ValueError(f"dup codes {[k for k,v in c.items() if v>1]}")
    pool = set(pool_map(day))
    miss = pool - set(seen)
    extra = set(seen) - pool
    print(day, "payload", len(seen), "pool", len(pool), "miss", sorted(miss), "extra", sorted(extra))
    payload = {"stories": stories}
    path = OUT / f"{day}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "write_story_day.py"), day, "--payload", str(path)],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
    )
    print(day, "rc", r.returncode, r.stdout.strip(), r.stderr.strip())
    if r.returncode != 0:
        raise SystemExit(r.returncode)


d = "2026-02-09"
# Image has 83 = pool; sections from image + 其他概念
write(d, [
    {"context":"AI应用","story":"字节跳动发布Seedance2.0推动AI短剧/漫剧降本增效","stocks":stocks(d,[
        ("002624","减亏+AI应用+电竞赛事"),
        ("002830","AI传媒+粤港澳大湾区+亲装龙头"),
        ("000892","业绩预增+短剧游戏+AIGC"),
        ("301262","AI漫剧+短剧+算力+AI出海"),
        ("301231","AI互动玩具+阿里概念+少儿图书"),
        ("603533","AI短剧+数字阅读+海外扩张"),
        ("603466","文生视频+豆包合作+人形机器人"),
        ("601595","AI影视+流浪山猫款+上海国资"),
        ("605287","AI漫剧+城市更新+扭亏为盈"),
        ("300364","短剧出海+AI应用+AIGC"),
        ("603103","影视院线+春节档+AI漫剧"),
        ("001330","影视院线+春节IP+AI短剧"),
        ("300182","AI漫剧+影视版权+文化传媒"),
        ("600666","文生视频+算力租赁+蓝宝石"),
        ("603598","AI营销+短剧出海+业绩预增"),
        ("601360","AI漫剧+AI应用+扭亏为盈+Sora概念"),
        ("688435","信创软件+数据复刻+华为鲲鹏"),
    ])},
    {"context":"光伏","story":"马斯克调研国内光伏厂商，太空光伏及设备订单预期提升","stocks":stocks(d,[
        ("002506","马斯克调研+太空光伏+TOPCon+钙钛矿"),
        ("002015","马斯克调研协同+光伏设备+锆钕材料合作"),
        ("600586","光伏玻璃+钙钛矿"),
        ("002323","光伏建筑一体化+光伏设备+枣庄国资"),
        ("300982","光伏+光储充+虚拟电厂"),
        ("002623","特斯拉概念+钙钛矿+阿联酋项目"),
        ("002309","光储储能+钙钛矿电池+国企+厦门国资"),
        ("001266","光储+算力+商业航天"),
        ("002501","光伏+铝型材+新能源汽车"),
        ("002079","光伏银浆+BC电池+HJT银包铜浆料+先进封装"),
        ("002129","光伏硅片龙头+马斯克调研+BC专利复审"),
        ("600875","光伏+氢能源+央企"),
        ("688503","太空光伏+铜浆量产+半导体掩模"),
        ("002218","太空光伏+钙钛矿+回购注销"),
    ])},
    {"context":"算力","story":"北美云厂商大幅上调资本开支，英伟达大涨","stocks":stocks(d,[
        ("003018","液冷冷却+瓶盖龙头+业绩承压"),
        ("002429","CPO+AI应用+MiniLED+深圳国资"),
        ("600589","算力租赁+东数西算+IDC"),
        ("600172","热沉片量产+培育钻石+国资背景"),
        ("688025","光通信+CPO+钙钛矿"),
        ("603031","商业航天+CPO+南孚电池+业绩预增"),
        ("002272","液冷服务器+AI液冷+清洁能源装备+晋能移动合作"),
        ("600590","数据中心+军工信息化+扭亏为盈"),
        ("601869","空芯光纤+800G硅光模块+华为网络"),
        ("600841","年报扭亏+数据中心+上海国资"),
        ("603629","算力租赁+年报预增+英伟达合作"),
    ])},
    {"context":"化工","story":"染料及农药价格上涨，行业景气度提升","stocks":stocks(d,[
        ("002455","锂电闭环+光刻胶概念+半导体制程+固态电池"),
        ("603188","染料涨价+年报预增+半导体投资"),
        ("600722","甲醇+风电+国企改革"),
        ("002054","纺织助剂龙头+本源量子IPO+2025年预增"),
        ("002099","创新药+染料+原料药+创投"),
        ("603980","控制权变更+染料+宇树科技"),
        ("605566","染料+机器人概念+资产处置"),
        ("001217","染料涨价+国资入股+光伏减亏"),
        ("000525","农药+国企改革+回购注销"),
        ("002440","染料+苯二胺产能+硝酸化工+氟基树脂项目"),
    ])},
    {"context":"电力","story":"大量变压器厂处于满产状态，订单排到2027年","stocks":stocks(d,[
        ("002438","核电阀门+商业航天+中低核阀器"),
        ("603163","新能源洁净+光伏设备+半导体制器"),
        ("002296","轨交设备+卫星通信+AI信创"),
        ("002534","可控核聚变+余热锅炉+数据中心+光热储能"),
        ("605060","燃气轮机+AIDC+风电+精密零部件"),
        ("603308","燃气轮机+可控核聚变+航空发动机"),
        ("603191","500kV变压器+数据中心+取向硅钢"),
    ])},
    {"context":"航天","story":"马斯克称SpaceX重心转向月球与星球","stocks":stocks(d,[
        ("600477","中标火箭基地+光伏研发+钢结构"),
        ("605598","商业航天+钙钛矿电池+一带一路"),
        ("000571","海南自贸区+煤炭+航空发动机"),
        ("600330","铌酸锂晶体+商业航天+光伏设备"),
        ("002471","商业航天+高温合金+电网设备"),
        ("300749","商业航天+扭亏为盈+大家居定制"),
        ("301232","商业航天+风电紧固件+业绩预增"),
    ])},
    {"context":"并购重组","story":"市场并购重组持续活跃","stocks":stocks(d,[
        ("603616","拟收购兴福新材+PEEK新材料+PCCP水利"),
        ("300912","拟收购金旺达+人形机器人+尾气后处理"),
        ("600884","安徽国资入主+固态电池+偏光片龙头"),
        ("000014","拟收购晶华电子+房地产+国资背景"),
        ("603729","拟收购惠恒影业58%股权+影视内容+复牌"),
    ])},
    {"context":"半导体产业链","story":"存储芯片等价格上涨，台积电等加大资本开支","stocks":stocks(d,[
        ("000016","MiniLED+央企+白电"),
        ("603929","IC洁净室+台积电扩产"),
        ("300480","半导体封测+第三代半导体+订单满产"),
    ])},
    {"context":"机器人","story":"第三代特斯拉人形机器人即将亮相","stocks":stocks(d,[
        ("603626","人形机器人+固态电池+精密制造"),
        ("301232","PLACEHOLDER"),  # wrong - already in 航天
    ])},
])
