"""API调用重试台账业务规则：失败请求归集、版本口径与重试状态流转都收在这里。

数据流：API客户端数据 + 失败请求回执 → 解析归集 → API调用重试台账。
- 失败请求必须绑定客户端与批次；同一请求编号只保留首版有效记录，重复登记一律拦住。
- 归属批次以数据版本为准：v2 新口径按事件发生时间（反映请求真实发生时段），
  v1 旧口径按接收时间（兼容旧数据）；迟到回执各按口径归批，
  两种口径都不破坏“一个失败请求只对应一个当前重试状态”。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.seed import APICLIENT_RECEIPT_SEED, APICLIENT_RETRY_STATUS_SEED
from app.store import store

MODULE = "apiclient_retry"
CLIENT_MODULE = "apiclient"

LEDGER_FIELDS = ["台账编号", "请求编号", "客户端编号", "接口名称", "请求方法", "回执批次", "归属批次",
                 "归属依据", "数据版本", "事件发生时间", "接收时间", "来源", "失败原因", "冲突处理",
                 "重试状态", "快照时间"]
RECEIPT_REQUIRED = ["请求编号", "客户端编号", "接口名称", "事件发生时间"]
STATUS_ORDER = ["待重试", "重试中", "重试成功", "重试失败"]
ACTION_RULES = {
    "开始重试": ("重试中", ["待重试", "重试失败"]),
    "重试成功": ("重试成功", ["重试中"]),
    "重试失败": ("重试失败", ["重试中"]),
    "重新排队": ("待重试", ["重试失败"]),
}
# 数据版本决定归属依据：v2 新口径看事件发生时间，v1 旧口径看接收时间。
VERSION_BASIS = {"v2": "事件时间", "v1": "接收时间"}
VERSIONS = ["v2", "v1"]
PENDING_STATUSES = ["待重试", "重试失败"]
TIME_FORMATS = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _parse_time(text: Any) -> datetime | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _batch_of(client_code: str, moment: datetime) -> str:
    return f"BATCH-{client_code}-{moment.strftime('%Y%m%d')}"


class ApiclientRetryService:
    """重试台账服务：启动时把种子回执归集成台账，运行期接收新回执并回写。"""

    def __init__(self) -> None:
        self._receipts: list[dict[str, Any]] = [dict(row) for row in APICLIENT_RECEIPT_SEED]
        self._blocked: list[dict[str, Any]] = []
        self._collect(status_overrides=APICLIENT_RETRY_STATUS_SEED)

    # ---------- 归集 ----------

    def _client_exists(self, client_code: str) -> bool:
        return any(str(row.get("客户端编号", "")) == client_code for row in store.rows(CLIENT_MODULE))

    def _attribute(self, receipt: dict[str, Any]) -> tuple[str, str, str]:
        """按数据版本决定归属批次与依据；返回（归属批次, 归属依据, 冲突处理）。"""
        version = str(receipt.get("数据版本") or "v2").strip().lower()
        if version not in VERSION_BASIS:
            version = "v2"
        basis = VERSION_BASIS[version]
        event_at = _parse_time(receipt.get("事件发生时间"))
        received_at = _parse_time(receipt.get("接收时间")) or event_at
        anchor = event_at if basis == "事件时间" else received_at
        assert anchor is not None and received_at is not None  # 校验阶段已拦住空时间
        batch = _batch_of(str(receipt.get("客户端编号", "")), anchor)
        conflict = ""
        if anchor.date() < received_at.date():
            # 响应迟到：原批次已关闭并生成台账后才到的回执，按口径归批并留痕。
            target = "原批次" if basis == "事件时间" else "下一批次"
            conflict = f"迟到回执按{basis}归入{target}{batch}；该批次台账已生成，本次追加不另立记录"
        return batch, basis, conflict

    def _build_row(self, receipt: dict[str, Any]) -> dict[str, Any]:
        batch, basis, conflict = self._attribute(receipt)
        rows = store.rows(MODULE)
        seq = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        version = str(receipt.get("数据版本") or "v2").strip().lower()
        row = {
            "id": seq,
            "台账编号": f"RETRY-{seq:04d}",
            "请求编号": str(receipt.get("请求编号", "")).strip(),
            "客户端编号": str(receipt.get("客户端编号", "")).strip(),
            "接口名称": str(receipt.get("接口名称", "")).strip(),
            "请求方法": str(receipt.get("请求方法", "")).strip() or "GET",
            "回执批次": str(receipt.get("批次号", "")).strip(),
            "归属批次": batch,
            "归属依据": basis,
            "数据版本": version,
            "事件发生时间": str(receipt.get("事件发生时间", "")).strip(),
            "接收时间": str(receipt.get("接收时间", "")).strip(),
            "来源": str(receipt.get("来源", "")).strip() or "实时回执",
            "失败原因": str(receipt.get("失败原因", "")).strip(),
            "冲突处理": conflict,
            "重试状态": STATUS_ORDER[0],
            "快照时间": str(receipt.get("登记时间", "")).strip() or _now(),
        }
        row["status"] = row["重试状态"]
        row["pending"] = True
        row["abnormal"] = False
        return row

    def _collect(self, status_overrides: dict[str, str] | None = None) -> None:
        """解析回执输入，按客户端归集失败请求生成台账；重复请求编号仅首版保留。"""
        store.rows(MODULE).clear()
        self._blocked = []
        seen: set[str] = set()
        ordered = sorted(self._receipts, key=lambda r: (str(r.get("登记时间", "")), int(r.get("id", 0))))
        for receipt in ordered:
            request_id = str(receipt.get("请求编号", "")).strip()
            if request_id in seen:
                self._blocked.append({
                    "回执编号": receipt.get("回执编号", ""),
                    "请求编号": request_id,
                    "原因": "重复登记：同一请求已存在有效重试记录，仅首版保留",
                })
                continue
            seen.add(request_id)
            store.rows(MODULE).append(self._build_row(receipt))
        for request_id, status in (status_overrides or {}).items():
            row = self._find_by_request(request_id)
            if row is not None:
                self._apply_status(row, status)

    def _find_by_request(self, request_id: str) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if row.get("请求编号") == request_id:
                return row
        return None

    def _apply_status(self, row: dict[str, Any], status: str) -> None:
        row["重试状态"] = status
        row["status"] = status
        row["pending"] = status != "重试成功"
        row["abnormal"] = status == "重试失败"
        row["快照时间"] = _now()

    # ---------- 查询 ----------

    def list_entries(
        self,
        *,
        filters: dict[str, str] | None = None,
        keyword: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = list(store.rows(MODULE))
        for field, expected in (filters or {}).items():
            rows = [row for row in rows if expected.casefold() in str(row.get(field, "")).casefold()]
        if keyword:
            rows = [row for row in rows if keyword.casefold() in str(row.get("请求编号", "")).casefold()]
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def summary(self) -> dict[str, Any]:
        """按客户端和批次汇总失败接口，并给出待处理清单。"""
        rows = list(store.rows(MODULE))
        clients: dict[str, dict[str, Any]] = {}
        batches: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            client = str(row.get("客户端编号", ""))
            status = str(row.get("重试状态", ""))
            bucket = clients.setdefault(client, {"客户端编号": client, "失败请求数": 0,
                                                 "待重试": 0, "重试中": 0, "重试成功": 0, "重试失败": 0})
            bucket["失败请求数"] += 1
            if status in bucket:
                bucket[status] += 1
            key = (client, str(row.get("归属批次", "")))
            batch = batches.setdefault(key, {
                "客户端编号": client, "归属批次": key[1], "失败接口数": 0, "接口列表": [],
                "待重试": 0, "重试中": 0, "重试成功": 0, "重试失败": 0,
                "批次状态": self._batch_state(key[1]),
            })
            interface = str(row.get("接口名称", ""))
            if interface and interface not in batch["接口列表"]:
                batch["接口列表"].append(interface)
                batch["失败接口数"] += 1
            if status in batch:
                batch[status] += 1
        pending_list = [
            {field: row.get(field) for field in
             ["台账编号", "请求编号", "客户端编号", "接口名称", "归属批次", "归属依据", "重试状态", "快照时间"]}
            for row in rows if row.get("重试状态") in PENDING_STATUSES
        ]
        return {
            "clients": sorted(clients.values(), key=lambda item: item["客户端编号"]),
            "batches": sorted(batches.values(), key=lambda item: (item["客户端编号"], item["归属批次"])),
            "pending_list": pending_list,
            "blocked_list": list(self._blocked),
            "totals": {
                "失败请求": len(rows),
                "待处理": len(pending_list),
                "重试中": sum(1 for row in rows if row.get("重试状态") == "重试中"),
                "重试成功": sum(1 for row in rows if row.get("重试状态") == "重试成功"),
                "重试失败": sum(1 for row in rows if row.get("重试状态") == "重试失败"),
            },
        }

    def review_snapshot(self) -> dict[str, Any]:
        """给相邻业务面（采集报告）的待核对视图：跟随台账状态变化实时计算。"""
        summary = self.summary()
        return {
            "待核对数": summary["totals"]["待处理"],
            "待核对清单": summary["pending_list"],
            "失败接口批次": summary["batches"],
        }

    @staticmethod
    def _batch_state(batch: str) -> str:
        """批次日期早于今天视为已关闭（台账已生成）；当天批次仍开放。"""
        try:
            batch_date = datetime.strptime(batch.rsplit("-", 1)[-1], "%Y%m%d").date()
        except (ValueError, IndexError):
            return "已关闭"
        return "已关闭" if batch_date < datetime.now().date() else "开放中"

    # ---------- 差异 ----------

    def diff(self, entry_id: int) -> dict[str, Any] | None:
        """口径差异：同一条台账按事件时间与接收时间各归哪个批次，哪个被采用。"""
        row = self.get_entry(entry_id)
        if row is None:
            return None
        client = str(row.get("客户端编号", ""))
        event_at = _parse_time(row.get("事件发生时间"))
        received_at = _parse_time(row.get("接收时间"))
        event_batch = _batch_of(client, event_at) if event_at else ""
        receive_batch = _batch_of(client, received_at) if received_at else ""
        adopted = str(row.get("归属依据", ""))
        legs = [
            {"口径": "事件时间", "时间": row.get("事件发生时间", ""), "归属批次": event_batch,
             "说明": "v2 新口径：按请求真实发生时段归集", "是否采用": adopted == "事件时间"},
            {"口径": "接收时间", "时间": row.get("接收时间", ""), "归属批次": receive_batch,
             "说明": "v1 旧口径：按回执接收时间归集（旧数据兼容）", "是否采用": adopted == "接收时间"},
        ]
        if event_batch == receive_batch:
            difference = "两种口径归属同一批次，无差异"
        else:
            difference = (f"事件时间口径归 {event_batch}，接收时间口径归 {receive_batch}；"
                          f"本条数据版本 {row.get('数据版本')} 采用{adopted}，归属 {row.get('归属批次')}")
        return {
            "台账编号": row.get("台账编号"),
            "请求编号": row.get("请求编号"),
            "客户端编号": client,
            "接口名称": row.get("接口名称"),
            "数据版本": row.get("数据版本"),
            "回执批次": row.get("回执批次"),
            "归属批次": row.get("归属批次"),
            "归属依据": adopted,
            "重试状态": row.get("重试状态"),
            "口径对比": legs,
            "差异": difference,
            "冲突处理": row.get("冲突处理") or "无",
        }

    # ---------- 回写 ----------

    def register_receipt(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """另一个入口：登记失败请求回执，同步回写台账并返回待处理清单。"""
        missing = [field for field in RECEIPT_REQUIRED if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        client_code = str(values.get("客户端编号", "")).strip()
        if not self._client_exists(client_code):
            return None, f"客户端 {client_code} 未登记，失败请求必须绑定已有客户端"
        if _parse_time(values.get("事件发生时间")) is None:
            return None, "事件发生时间无法解析，支持 YYYY-MM-DD HH:MM:SS"
        if str(values.get("接收时间") or "").strip() and _parse_time(values.get("接收时间")) is None:
            return None, "接收时间无法解析，支持 YYYY-MM-DD HH:MM:SS"
        version = str(values.get("数据版本") or "v2").strip().lower()
        if version not in VERSIONS:
            return None, f"数据版本「{version}」不支持，仅接受 v2（事件时间口径）或 v1（接收时间旧口径）"
        request_id = str(values.get("请求编号", "")).strip()
        if self._find_by_request(request_id) is not None:
            self._blocked.append({"回执编号": values.get("回执编号", ""), "请求编号": request_id,
                                  "原因": "重复登记：同一请求已存在有效重试记录，仅首版保留"})
            return None, f"重复登记已拦住：请求 {request_id} 已存在有效重试记录，仅首版保留"
        receipt = {
            "id": max((int(r.get("id", 0)) for r in self._receipts), default=0) + 1,
            "回执编号": str(values.get("回执编号") or "").strip()
                       or f"RCPT-{len(self._receipts) + 1:04d}",
            "请求编号": request_id,
            "客户端编号": client_code,
            "接口名称": str(values.get("接口名称", "")).strip(),
            "请求方法": str(values.get("请求方法", "")).strip() or "GET",
            "批次号": str(values.get("批次号", "")).strip(),
            "事件发生时间": str(values.get("事件发生时间", "")).strip(),
            "接收时间": str(values.get("接收时间") or "").strip() or _now(),
            "数据版本": version,
            "来源": str(values.get("来源", "")).strip() or "实时回执",
            "失败原因": str(values.get("失败原因", "")).strip(),
            "登记时间": _now(),
        }
        self._receipts.append(receipt)
        row = self._build_row(receipt)
        store.rows(MODULE).append(row)
        message = f"失败请求已归集：{row['台账编号']} 按{row['归属依据']}归入 {row['归属批次']}"
        if row["冲突处理"]:
            message += f"（{row['冲突处理']}）"
        return row, message

    def rebuild(self) -> dict[str, Any]:
        """重新归集：按当前全部回执重算归属批次；重试状态是运维进度，按请求编号保留。"""
        status_by_request = {row.get("请求编号"): row.get("重试状态")
                             for row in store.rows(MODULE)}
        self._collect(status_overrides=status_by_request)
        return self.summary()

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        row = self.get_entry(entry_id)
        if row is None:
            return None, f"重试记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于重试台账可执行范围"
        target, sources = ACTION_RULES[action]
        current = str(row.get("重试状态", ""))
        if current not in sources:
            return None, f"当前状态「{current}」不允许{action}，可执行状态：{'、'.join(sources)}"
        self._apply_status(row, target)
        return row, f"{row['台账编号']} 已{action}，当前状态：{target}"


retry_service = ApiclientRetryService()
