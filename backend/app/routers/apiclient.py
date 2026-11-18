"""API接入管理接口：维护API客户端，覆盖完成配置、启动接入、停用接入等动作。

同时承载API调用重试台账：失败请求回执从这里归集入账、按客户端和批次汇总，
是运维判断“哪些接口需要重试”的入口。
"""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.schemas import ActionPayload, ActionResult, EntryPayload, PageResult
from app.services.apiclient import ApiclientService
from app.services.apiclient_retry import LEDGER_FIELDS, retry_service

router = APIRouter(prefix="/api/apiclient", tags=["API接入管理"])

service = ApiclientService()

LIST_FIELDS = ["客户端编号", "接口名称", "请求方法", "认证凭证", "限流令牌", "重试策略", "超时配置", "启用状态"]
STATUSES = ["待配置", "已配置", "运行中", "已停用"]


def query_filters(request: Request) -> dict[str, str]:
    """只接受当前模块声明过的字段，忽略分页等保留参数。"""
    return {
        key: value.strip()
        for key, value in request.query_params.items()
        if key in LIST_FIELDS and value.strip()
    }


def ledger_filters(request: Request) -> dict[str, str]:
    """台账筛选只认台账字段：客户端、批次、来源、版本、重试状态都能过滤。"""
    return {
        key: value.strip()
        for key, value in request.query_params.items()
        if key in LEDGER_FIELDS and value.strip()
    }


@router.get("", response_model=PageResult[dict])
def list_entries(
    request: Request,
    keyword: str | None = Query(default=None, description="按客户端编号检索"),
    status: str | None = Query(default=None, description="待配置、已配置、运行中、已停用"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResult[dict]:
    """按页面字段、客户端编号关键字与状态过滤API接入管理列表。"""
    items, total = service.list_entries(
        filters=query_filters(request), keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries(
    request: Request,
    keyword: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> StreamingResponse:
    """下载当前筛选条件下的 UTF-8 CSV；必须声明在 /{entry_id} 之前。"""
    items, _ = service.list_entries(
        filters=query_filters(request), keyword=keyword, status=status, page=1, size=1000000)
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["id", *LIST_FIELDS, "status"])
    for item in items:
        row = []
        for value in [item.get("id"), *(item.get(field, "") for field in LIST_FIELDS), item.get("status", "")]:
            text = "" if value is None else str(value)
            row.append("'" + text if text.startswith(("=", "+", "-", "@")) else text)
        writer.writerow(row)
    return StreamingResponse(
        iter([output.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="apiclient.csv"'})


@router.get("/retry", response_model=PageResult[dict])
def list_retry_ledger(
    request: Request,
    keyword: str | None = Query(default=None, description="按请求编号检索"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResult[dict]:
    """分页查询API调用重试台账；按客户端、重试状态、来源、数据版本等字段过滤。"""
    items, total = retry_service.list_entries(
        filters=ledger_filters(request), keyword=keyword, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/retry/summary")
def retry_summary() -> dict[str, object]:
    """按客户端和批次汇总失败接口，并给出待处理清单；报告页同步取这里的数据。"""
    return retry_service.summary()


@router.post("/retry/receipts")
def register_receipt(payload: dict[str, object]) -> dict[str, object]:
    """另一个入口：登记失败请求回执，同步回写台账并返回最新待处理清单。

    重复登记同一请求编号只保留首版，其余拦住并说明原因。
    """
    entry, message = retry_service.register_receipt(payload)
    if entry is None:
        return {"ok": False, "message": message,
                "pending_list": retry_service.summary()["pending_list"]}
    return {"ok": True, "message": message, "entry": entry,
            "pending_list": retry_service.summary()["pending_list"]}


@router.post("/retry/rebuild")
def rebuild_retry_ledger() -> dict[str, object]:
    """重新归集：解析现有回执输入重建台账；重试状态按请求编号保留。"""
    summary = retry_service.rebuild()
    return {"ok": True, "message": "API调用重试台账已重新归集", "summary": summary}


@router.get("/retry/{retry_id}", response_model=dict)
def get_retry_entry(retry_id: int) -> dict:
    """读取单条重试记录：重试状态的数据快照。"""
    entry = retry_service.get_entry(retry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"重试记录 {retry_id} 不存在或已归档")
    return entry


@router.get("/retry/{retry_id}/diff", response_model=dict)
def retry_entry_diff(retry_id: int) -> dict:
    """口径差异：事件时间与接收时间各归哪个批次、当前采用哪个。"""
    diff = retry_service.diff(retry_id)
    if diff is None:
        raise HTTPException(status_code=404, detail=f"重试记录 {retry_id} 不存在或已归档")
    return diff


@router.post("/retry/{retry_id}/actions", response_model=ActionResult)
def run_retry_action(retry_id: int, payload: ActionPayload) -> ActionResult:
    """重试状态流转：开始重试、重试成功、重试失败、重新排队；非法流转拦下并说明。"""
    entry, message = retry_service.run_action(retry_id, payload.action.strip())
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条API客户端明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"API客户端 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: dict[str, object]) -> ActionResult:
    """登记一条API客户端，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="API客户端已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: ActionPayload) -> ActionResult:
    """对单条API客户端执行完成配置、启动接入、停用接入；不允许的动作会被拦下并说明原因。"""
    entry, message = service.run_action(entry_id, payload.action.strip())
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
