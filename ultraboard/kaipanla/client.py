# -*- coding: utf-8 -*-
"""开盘啦历史接口客户端。

约束：
- DeviceID 固定，生成一次后永久复用
- 请求间隔默认 1~2 秒随机
- 失败即停，不重试轰炸
"""
from __future__ import annotations

import json
import random
import time
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
import urllib3

urllib3.disable_warnings()

HIS_URL = "https://apphis.longhuvip.com/w1/api/index.php"
CURRENT_URL = "https://apphq.longhuvip.com/w1/api/index.php"
SECTOR_URL = "https://apphwhq.longhuvip.com/w1/api/index.php"
VERSION = "5.21.0.2"
APIV = "w42"
UA = "Dalvik/2.1.0 (Linux; U; Android 9; SHARK PRS-A0 Build/PQ3A.190605.01141736)"
CN_TZ = timezone(timedelta(hours=8))


class KaipanlaClient:
    def __init__(
        self,
        data_dir: Path,
        interval_min: float = 1.0,
        interval_max: float = 2.0,
    ):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.interval_min = interval_min
        self.interval_max = interval_max
        self._last_req = 0.0
        self.device_id = self._load_or_create_device_id()

    def _load_or_create_device_id(self) -> str:
        path = self.data_dir / "device_id.txt"
        if path.exists():
            did = path.read_text(encoding="utf-8").strip()
            if did:
                return did
        did = str(uuid.uuid4())
        path.write_text(did, encoding="utf-8")
        return did

    def _wait(self) -> None:
        gap = random.uniform(self.interval_min, self.interval_max)
        elapsed = time.time() - self._last_req
        if elapsed < gap:
            time.sleep(gap - elapsed)

    def _headers(self, host: str) -> dict[str, str]:
        return {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": UA,
            "Host": host,
            "Accept-Encoding": "gzip",
        }

    def post(self, url: str, extra: dict[str, Any], day: str | None = None) -> dict[str, Any]:
        """发一次请求。errcode 非 0 时仍返回 body，由调用方决定是否停。"""
        self._wait()
        host = url.split("//", 1)[1].split("/", 1)[0]
        data = {
            "PhoneOSNew": "1",
            "DeviceID": self.device_id,
            "VerSion": VERSION,
            "apiv": APIV,
        }
        if day:
            data["Day"] = day
        data.update(extra)
        try:
            r = requests.post(
                url,
                data=data,
                headers=self._headers(host),
                verify=False,
                timeout=12,
            )
            self._last_req = time.time()
            r.raise_for_status()
            return r.json()
        except Exception as e:
            self._last_req = time.time()
            return {"errcode": "EXC", "errmsg": f"{type(e).__name__}: {e}"}

    def his_zhangfu(self, day: str) -> dict[str, Any]:
        return self.post(HIS_URL, {"a": "HisZhangFuDetail", "c": "HisHomeDingPan"}, day)

    def current_zhangfu(self) -> dict[str, Any]:
        """读取最新交易日情绪统计；响应正文自带日期。"""
        return self.post(CURRENT_URL, {"a": "ZhangFuDetail", "c": "HomeDingPan"})

    def zhangting_expression(self, day: str) -> dict[str, Any]:
        return self.post(HIS_URL, {"a": "ZhangTingExpression", "c": "HisHomeDingPan"}, day)

    def current_zhangting_expression(self) -> dict[str, Any]:
        """读取最新梯队指标；当前接口可能返回反爬占位符。"""
        return self.post(
            CURRENT_URL,
            {"a": "ZhangTingExpression", "c": "HomeDingPan"},
        )

    def latest_plate_info(self, index: int = 0) -> dict[str, Any]:
        """最新交易日涨停原因板块。

        ``GetPlateInfo_w38`` 会静默忽略历史日期，因此这里只暴露“最新快照”
        语义，避免调用方误以为它支持历史回放。
        """
        return self.post(
            SECTOR_URL,
            {
                "a": "GetPlateInfo_w38",
                "st": "100",
                "c": "DailyLimitResumption",
                "Index": str(index),
            },
        )

    @staticmethod
    def _plate_info_day(body: dict[str, Any]) -> str | None:
        """从涨停原因股票的首封时间推断快照交易日。"""
        days = []
        for sector in body.get("list") or []:
            for stock in sector.get("StockList") or []:
                if not isinstance(stock, list) or len(stock) <= 6:
                    continue
                stamp = stock[6]
                if not isinstance(stamp, (int, float)) or stamp <= 0:
                    continue
                days.append(
                    datetime.fromtimestamp(stamp, CN_TZ).date().isoformat()
                )
        return Counter(days).most_common(1)[0][0] if days else None

    def plate_info(self, expected_day: str, index: int = 0) -> dict[str, Any]:
        """读取最新涨停原因，并严格校验它确实属于 ``expected_day``。

        该接口不是历史接口。日期不一致时只返回明确错误，不把响应正文交给
        调用方，从数据入口阻断“当前榜倒灌历史节点”的未来信息污染。
        """
        body = self.latest_plate_info(index=index)
        if not ok(body):
            return body
        actual_day = self._plate_info_day(body)
        if actual_day != expected_day:
            return {
                "errcode": "DATE_MISMATCH",
                "errmsg": (
                    "GetPlateInfo_w38 仅返回最新交易日，"
                    f"期望 {expected_day}，实际 {actual_day or '无法识别'}"
                ),
                "expected_day": expected_day,
                "actual_day": actual_day,
            }
        body["snapshot_day"] = actual_day
        return body

    def sector_ladder(self, day: str) -> dict[str, Any]:
        """板块核心梯队 + 反包板。

        注意：该接口历史用 `Date`（大写）而非 `Day`。
        返回 List[板块]，每个板块的 TD 按 TDType 分组：
          0=反包板  1=首板  2=2连板 ...  9=打开高度标注
        """
        return self.post(HIS_URL, {"a": "GetYTFP_BKHX", "c": "FuPanLa", "Date": day})

    def daily_limit_performance(self, day: str, pid_type: int) -> dict[str, Any]:
        """涨停池分组。

        PidType 1~4 = 恰好 N 板；PidType 5 = 「5 板及以上」。
        真实板数必须读个股数组下标 15，不能用 PidType 代替。
        """
        return self.post(
            HIS_URL,
            {
                "Order": "0",
                "a": "DailyLimitPerformance",
                "st": "2000",
                "c": "HisHomeDingPan",
                "Index": "0",
                "PidType": str(pid_type),
                "Type": "4",
            },
            day,
        )

    def his_daban_list(self, day: str, type_: int = 4, index: int = 0) -> dict[str, Any]:
        return self.post(
            HIS_URL,
            {
                "Order": "1",
                "a": "HisDaBanList",
                "st": "200",
                "c": "HisHomeDingPan",
                "Index": str(index),
                "Is_st": "1",
                "PidType": "2",
                "Type": str(type_),
                "FilterMotherboard": "0",
                "Filter": "0",
                "FilterTIB": "0",
                "FilterGem": "0",
            },
            day,
        )


def ok(body: dict[str, Any]) -> bool:
    return str(body.get("errcode", "")) == "0"


def dump_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
