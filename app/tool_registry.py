from __future__ import annotations

import csv
import json
import os
import time
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .utils import DATA_DIR, OUTPUT_DIR


@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    error: Optional[str] = None
    elapsed_ms: float = 0.0


@dataclass
class Tool:
    name: str
    description: str
    parameters: Dict[str, Any]
    func: Callable[[Dict[str, Any]], Any]

    def run(self, args: Dict[str, Any]) -> ToolResult:
        start = time.perf_counter()
        try:
            data = self.func(args)
            return ToolResult(ok=True, data=data, elapsed_ms=round((time.perf_counter() - start) * 1000, 2))
        except Exception as exc:
            return ToolResult(ok=False, error=str(exc), elapsed_ms=round((time.perf_counter() - start) * 1000, 2))


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name}")
        return self._tools[name]

    def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {"name": tool.name, "description": tool.description, "parameters": tool.parameters}
            for tool in self._tools.values()
        ]


def _load_csv(file_name: str) -> List[Dict[str, Any]]:
    path = DATA_DIR / file_name
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def _filter_month(rows: List[Dict[str, Any]], month: str) -> List[Dict[str, Any]]:
    return [row for row in rows if str(row.get("date", "")).startswith(month)]


def query_table(args: Dict[str, Any]) -> Dict[str, Any]:
    table = args["table"]
    month = args.get("month", "2026-05")
    rows = _filter_month(_load_csv(f"{table}.csv"), month)
    return {"table": table, "month": month, "row_count": len(rows), "rows": rows}


def data_quality_check(args: Dict[str, Any]) -> Dict[str, Any]:
    rows = args["rows"]
    required_fields = args["required_fields"]
    missing_by_field = {field: 0 for field in required_fields}
    for row in rows:
        for field in required_fields:
            if row.get(field) in (None, ""):
                missing_by_field[field] += 1
    total_missing = sum(missing_by_field.values())
    return {
        "row_count": len(rows),
        "required_fields": required_fields,
        "missing_by_field": missing_by_field,
        "total_missing": total_missing,
        "passed": total_missing == 0 and len(rows) > 0,
    }


def aggregate_downtime(args: Dict[str, Any]) -> Dict[str, Any]:
    rows = args["rows"]
    group_by = args["group_by"]
    duration_sum: Dict[str, float] = defaultdict(float)
    count_sum: Counter[str] = Counter()
    normalized_rows = []
    for row in rows:
        item = dict(row)
        item["duration_min"] = float(item.get("duration_min") or 0)
        normalized_rows.append(item)
        key = str(item.get(group_by) or "UNKNOWN")
        duration_sum[key] += item["duration_min"]
        count_sum[key] += 1
    total_duration = sum(duration_sum.values()) or 1.0
    groups = [
        {
            group_by: key,
            "duration_min": round(duration, 2),
            "count": count_sum[key],
            "duration_ratio": round(duration / total_duration, 4),
        }
        for key, duration in duration_sum.items()
    ]
    groups.sort(key=lambda item: item["duration_min"], reverse=True)
    return {
        "group_by": group_by,
        "total_duration_min": round(total_duration, 2),
        "total_count": len(normalized_rows),
        "groups": groups,
    }


def pareto_analysis(args: Dict[str, Any]) -> Dict[str, Any]:
    items = args["items"]
    value_key = args.get("value_key", "duration_min")
    label_key = args.get("label_key")
    total = sum(float(item[value_key]) for item in items) or 1.0
    cumulative = 0.0
    enriched = []
    key_items = []
    for item in items:
        cumulative += float(item[value_key])
        new_item = dict(item)
        new_item["cumulative_ratio"] = round(cumulative / total, 4)
        enriched.append(new_item)
        if cumulative / total <= 0.8 or not key_items:
            key_items.append(new_item)
    return {"total": round(total, 2), "label_key": label_key, "items": enriched, "key_items": key_items}


def correlate_root_causes(args: Dict[str, Any]) -> Dict[str, Any]:
    downtime_rows = args["downtime_rows"]
    alarm_rows = args.get("alarm_rows", [])
    maintenance_rows = args.get("maintenance_rows", [])
    shortage_rows = args.get("shortage_rows", [])
    quality_rows = args.get("quality_rows", [])

    equipment_fault_rows = [row for row in downtime_rows if row.get("reason_category") == "设备故障"]
    equipment_counter = Counter(row.get("equipment_id", "UNKNOWN") for row in equipment_fault_rows)
    alarm_counter = Counter(row.get("alarm_code", "UNKNOWN") for row in alarm_rows)
    repeated_orders = [row for row in maintenance_rows if str(row.get("repeated_fault_flag", "")).lower() == "true"]
    shortage_total = sum(float(row.get("shortage_duration_min") or 0) for row in shortage_rows)
    quality_total = sum(float(row.get("impact_duration_min") or 0) for row in quality_rows if str(row.get("stop_line_flag", "")).lower() == "true")

    hypotheses = []
    if equipment_counter:
        top_equipment, top_count = equipment_counter.most_common(1)[0]
        hypotheses.append(f"设备故障集中在 {top_equipment}，出现 {top_count} 次；报警侧高频代码为 {alarm_counter.most_common(1)[0][0] if alarm_counter else 'UNKNOWN'}。")
    if repeated_orders:
        hypotheses.append(f"维修工单中存在 {len(repeated_orders)} 条重复故障记录，说明部分故障未彻底闭环。")
    if shortage_total > 0:
        hypotheses.append(f"缺料等待累计影响 {shortage_total:.0f} 分钟，需要检查供应商到料与配送窗口。")
    if quality_total > 0:
        hypotheses.append(f"质量异常停线累计影响 {quality_total:.0f} 分钟，需要关注批次复检与来料质量。")

    return {
        "top_fault_equipments": equipment_counter.most_common(5),
        "top_alarm_codes": alarm_counter.most_common(5),
        "repeated_order_count": len(repeated_orders),
        "shortage_total_min": round(shortage_total, 2),
        "quality_total_min": round(quality_total, 2),
        "hypotheses": hypotheses,
    }


def generate_svg_chart(args: Dict[str, Any]) -> Dict[str, Any]:
    items = args["items"]
    label_key = args["label_key"]
    value_key = args.get("value_key", "duration_min")
    title = args.get("title", "Downtime Chart")
    output_name = args.get("output_name", "downtime_chart.svg")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / output_name
    width = 900
    row_h = 36
    height = 90 + row_h * len(items)
    max_value = max(float(item[value_key]) for item in items) if items else 1.0
    bars = []
    for idx, item in enumerate(items):
        y = 60 + idx * row_h
        label = str(item[label_key])
        value = float(item[value_key])
        bar_w = 620 * value / max_value if max_value else 0
        bars.append(
            f'<text x="20" y="{y + 20}" font-size="14">{label}</text>'
            f'<rect x="160" y="{y}" width="{bar_w:.1f}" height="22" fill="#6aa9ff" />'
            f'<text x="{170 + bar_w:.1f}" y="{y + 17}" font-size="13">{value:.0f} min</text>'
        )
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">' \
          f'<rect width="100%" height="100%" fill="white" />' \
          f'<text x="20" y="32" font-size="20" font-weight="bold">{title}</text>' \
          + ''.join(bars) + '</svg>'
    path.write_text(svg, encoding="utf-8")
    return {"chart_path": str(path), "item_count": len(items)}


def call_dify_agent(args: Dict[str, Any]) -> Dict[str, Any]:
    api_url = args.get("api_url") or os.getenv("DIFY_API_URL")
    api_key = args.get("api_key") or os.getenv("DIFY_API_KEY")
    query = args["query"]
    inputs = args.get("inputs", {})
    if not api_url or not api_key:
        return {
            "called": False,
            "reason": "DIFY_API_URL or DIFY_API_KEY is not configured",
            "mock_response": "Dify 工具已注册，但当前未配置真实地址和密钥。",
        }
    payload = json.dumps({"inputs": inputs, "query": query, "response_mode": "blocking", "user": "local-agent-demo"}).encode("utf-8")
    request = urllib.request.Request(
        api_url,
        data=payload,
        method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        body = response.read().decode("utf-8")
    return {"called": True, "raw": json.loads(body)}


def build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(Tool("query_table", "查询一个制造业务数据表，支持按月份过滤。", {"table": "str", "month": "YYYY-MM"}, query_table))
    registry.register(Tool("data_quality_check", "检查数据行的必填字段完整性。", {"rows": "list", "required_fields": "list[str]"}, data_quality_check))
    registry.register(Tool("aggregate_downtime", "按指定维度聚合停机时长和次数。", {"rows": "list", "group_by": "str"}, aggregate_downtime))
    registry.register(Tool("pareto_analysis", "对聚合结果做 Pareto 分析。", {"items": "list", "value_key": "str", "label_key": "str"}, pareto_analysis))
    registry.register(Tool("correlate_root_causes", "关联停机、报警、维修、缺料、质量数据并生成根因假设。", {"downtime_rows": "list", "alarm_rows": "list", "maintenance_rows": "list", "shortage_rows": "list", "quality_rows": "list"}, correlate_root_causes))
    registry.register(Tool("generate_svg_chart", "根据分析结果生成 SVG 条形图。", {"items": "list", "label_key": "str", "value_key": "str", "title": "str", "output_name": "str"}, generate_svg_chart))
    registry.register(Tool("call_dify_agent", "调用 Dify agent，可作为外部智能体工具。", {"query": "str", "inputs": "dict", "api_url": "optional", "api_key": "optional"}, call_dify_agent))
    return registry
