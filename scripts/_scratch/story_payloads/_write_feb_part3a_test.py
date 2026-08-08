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


# ---- 2026-02-09 ----
d = "2026-02-09"
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
        ("001217","染料涨价+国资入股肤+光伏减亏"),
        ("000525","农药+国企改革+回购注销"),
        ("603980","染料+苯二胺产能+硝酸化工+氟基树指项目"),
    ])},
])
# wait - 603980 appears twice in 化工 for 02-09. Looking at image again:
# 二板 002455 百川股份
# 首板 603188 亚邦股份
# 首板 600722 金牛化工
# 首板 002054 德美化工
# 二板 002099 海翔药业
# 二板 603980 吉华集团
# 首板 605566 福莱蒽特
# 首板 001217 华尔泰
# 首板 000525 红太阳
# 首板 001217 华尔泰 - wait image says 001217 twice? Let me re-read

# From image description for 化工:
# 二板 002455 百川股份
# 首板 603188 亚邦股份  
# 首板 600722 金牛化工
# 首板 002054 德美化工
# 二板 002099 海翔药业
# 二板 603980 吉华集团
# 首板 605566 福莱蒽特
# 首板 001217 华尔泰
# 首板 000525 红太阳
# 首板 001217? Wait last one: "首板 001217 华尔泰" and "染料+苯二胺产能..." - that would be duplicate of 001217

# Looking at OCR more carefully:
# 首板 001217 华尔泰 13:01:25 染料+国资入股肤+光伏减亏
# 首板 000525 红太阳 14:34:49 农药+国企改革+回购注销  
# 首板 001217? 红太阳 next... Actually last: "首板 001217 华尔泰 14:34:09 染料+苯二胺..." NO

# Image text: "首板 001217 华尔泰 13:01:25" and last "首板 001217" - that can't be right.
# Looking: "首板 001217 华尔泰" and "首板 00???? " for 染料+苯二胺

# From limit_pool names related to dye:
# 605566 福莱蒽特 - dye
# 603188 亚邦股份
# 603980 吉华集团  
# 001217 华尔泰
# 000525 红太阳
# 002440 闰土股份 - is 闰土 in pool? Yes 002440

# Looking at image again carefully from OCR:
# 二板 002455 百川股份
# 首板 603188 亚邦股份
# 首板 600722 金牛化工
# 首板 002054 德美化工
# 二板 002099 海翔药业
# 二板 603980 吉华集团
# 首板 605566 福莱蒽特
# 首板 001217 华尔泰
# 首板 000525 红太阳
# 首板 002440 闰土股份  -- last line "染料+苯二胺产能+硝酸化工+氟基树指项目"

# OCR said "001217 华尔泰" twice incorrectly - last is likely 002440 闰土股份 which has dye business.
# Count: 10 stocks in 化工 section. Pool has 83, AI has 17, PV 14, compute 11 = 42, chem 10 = 52...

print("part3a should not run yet")
