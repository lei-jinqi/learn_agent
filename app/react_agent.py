from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .tool_registry import ToolRegistry, build_default_registry
from .utils import OUTPUT_DIR, ensure_outputs_dir, load_task_tree


@dataclass
class Step:
    thought: str
    action: str
    args: Dict[str, Any]
    observation: Dict[str, Any]


@dataclass
class AgentMemory:
    user_query: str
    month: str = "2026-05"
    data: Dict[str, Any] = field(default_factory=dict)
    analysis: Dict[str, Any] = field(default_factory=dict)
    steps: List[Step] = field(default_factory=list)
    final_answer: Optional[str] = None

    def has_table(self, name: str) -> bool:
        return name in self.data and bool(self.data[name].get("rows"))

    def has_analysis(self, name: str) -> bool:
        return name in self.analysis


class TaskTreePolicy:
    """Use the business task tree as guardrails for a tool-using agent.

    The task tree does not hard-code every step. It defines what data is required,
    which tools are allowed, and what the final answer must contain. The planner can
    still choose the next action dynamically from current observations.
    """

    def __init__(self, task_tree: Optional[Dict[str, Any]] = None) -> None:
        self.task_tree = task_tree or load_task_tree()
        self.required_data = self.task_tree.get("required_data", [])
        self.output_schema = self.task_tree.get("output_schema", [])
        self.allowed_tools = set(
            self.task_tree.get(
                "allowed_tools",
                [
                    "query_table",
                    "data_quality_check",
                    "aggregate_downtime",
                    "pareto_analysis",
                    "correlate_root_causes",
                    "generate_svg_chart",
                    "call_dify_agent",
                ],
            )
        )

    def assert_allowed(self, action: str) -> None:
        if action != "finish" and action not in self.allowed_tools:
            raise ValueError(f"Action {action} is not allowed by task tree policy")

    def completion_check(self, memory: AgentMemory) -> Dict[str, Any]:
        required_analysis = ["quality", "by_reason", "by_line", "by_equipment", "pareto_reason", "root_causes", "chart"]
        missing_data = [table for table in self.required_data if not memory.has_table(table)]
        missing_analysis = [key for key in required_analysis if not memory.has_analysis(key)]
        return {
            "passed": not missing_data and not missing_analysis,
            "missing_data": missing_data,
            "missing_analysis": missing_analysis,
            "output_schema": self.output_schema,
        }


class RuleBasedPlanner:
    """A transparent planner that chooses tools from current observations.

    This is not an LLM planner, but it behaves like an agent policy: the next action
    is selected from current memory, not from a fixed workflow edge list.
    """

    def __init__(self, policy: Optional[TaskTreePolicy] = None) -> None:
        self.policy = policy or TaskTreePolicy()

    def next_action(self, memory: AgentMemory) -> Dict[str, Any]:
        required_tables = self.policy.required_data
        for table in required_tables:
            if not memory.has_table(table):
                return {
                    "thought": f"我需要先获得 {table}，否则无法基于证据分析停机原因。",
                    "action": "query_table",
                    "args": {"table": table, "month": memory.month},
                    "save_to": ("data", table),
                }

        if not memory.has_analysis("quality"):
            return {
                "thought": "已经拿到停机记录，下一步要检查关键字段是否完整，避免后续指标口径错误。",
                "action": "data_quality_check",
                "args": {
                    "rows": memory.data["downtime_records"]["rows"],
                    "required_fields": ["date", "line_id", "equipment_id", "duration_min", "reason_code", "reason_category", "department"],
                },
                "save_to": ("analysis", "quality"),
            }

        for key, group_by in [("by_reason", "reason_category"), ("by_line", "line_id"), ("by_equipment", "equipment_id")]:
            if not memory.has_analysis(key):
                return {
                    "thought": f"需要按 {group_by} 聚合停机时长和次数，用于判断主要影响因素。",
                    "action": "aggregate_downtime",
                    "args": {"rows": memory.data["downtime_records"]["rows"], "group_by": group_by},
                    "save_to": ("analysis", key),
                }

        if not memory.has_analysis("pareto_reason"):
            return {
                "thought": "已经得到原因维度统计，下一步用 Pareto 找出少数关键原因。",
                "action": "pareto_analysis",
                "args": {"items": memory.analysis["by_reason"]["groups"], "value_key": "duration_min", "label_key": "reason_category"},
                "save_to": ("analysis", "pareto_reason"),
            }

        if not memory.has_analysis("root_causes"):
            return {
                "thought": "仅有原因占比还不够，需要关联报警、维修、缺料和质量异常记录形成根因假设。",
                "action": "correlate_root_causes",
                "args": {
                    "downtime_rows": memory.data["downtime_records"]["rows"],
                    "alarm_rows": memory.data["equipment_alarms"]["rows"],
                    "maintenance_rows": memory.data["maintenance_orders"]["rows"],
                    "shortage_rows": memory.data["material_shortage_records"]["rows"],
                    "quality_rows": memory.data["quality_incidents"]["rows"],
                },
                "save_to": ("analysis", "root_causes"),
            }

        if not memory.has_analysis("chart"):
            return {
                "thought": "为了让报告更可解释，我生成一张原因维度停机时长图表。",
                "action": "generate_svg_chart",
                "args": {
                    "items": memory.analysis["by_reason"]["groups"],
                    "label_key": "reason_category",
                    "value_key": "duration_min",
                    "title": "本月产线停机原因 Top 分布",
                    "output_name": "reason_duration_chart.svg",
                },
                "save_to": ("analysis", "chart"),
            }

        return {
            "thought": "关键数据、指标、Pareto 和根因证据都已具备，可以停止工具调用并生成最终答案。",
            "action": "finish",
            "args": {},
        }


class ReActDowntimeAgent:
    def __init__(
        self,
        registry: Optional[ToolRegistry] = None,
        planner: Optional[RuleBasedPlanner] = None,
        policy: Optional[TaskTreePolicy] = None,
        max_steps: int = 20,
    ):
        self.registry = registry or build_default_registry()
        self.policy = policy or TaskTreePolicy()
        self.planner = planner or RuleBasedPlanner(self.policy)
        self.max_steps = max_steps

    def run(self, user_query: str) -> AgentMemory:
        memory = AgentMemory(user_query=user_query)
        for _ in range(self.max_steps):
            decision = self.planner.next_action(memory)
            action = decision["action"]
            self.policy.assert_allowed(action)
            if action == "finish":
                completion = self.policy.completion_check(memory)
                observation = {"ok": completion["passed"], "message": "ready_to_finish", "policy_check": completion}
                memory.steps.append(Step(decision["thought"], action, {}, observation))
                if not completion["passed"]:
                    memory.final_answer = f"任务树约束检查未通过：{completion}"
                    return memory
                memory.final_answer = self._compose_final_answer(memory)
                return memory

            tool = self.registry.get(action)
            result = tool.run(decision["args"])
            observation = {"ok": result.ok, "elapsed_ms": result.elapsed_ms, "error": result.error}
            if result.ok:
                observation["data_preview"] = self._preview(result.data)
                target_area, target_key = decision["save_to"]
                getattr(memory, target_area)[target_key] = result.data
            memory.steps.append(Step(decision["thought"], action, decision["args"], observation))
            if not result.ok:
                memory.final_answer = f"工具 {action} 调用失败：{result.error}"
                return memory

        memory.final_answer = "达到最大步数，未完成分析。"
        return memory

    @staticmethod
    def _preview(data: Any) -> Any:
        if isinstance(data, dict):
            preview = {}
            for key, value in data.items():
                if key == "rows" and isinstance(value, list):
                    preview[key] = {"row_count": len(value), "sample": value[:2]}
                elif isinstance(value, list):
                    preview[key] = value[:3]
                else:
                    preview[key] = value
            return preview
        return data

    @staticmethod
    def _compose_final_answer(memory: AgentMemory) -> str:
        by_reason = memory.analysis["by_reason"]
        by_line = memory.analysis["by_line"]
        by_equipment = memory.analysis["by_equipment"]
        pareto = memory.analysis["pareto_reason"]
        root_causes = memory.analysis["root_causes"]
        chart = memory.analysis["chart"]

        top_reason = by_reason["groups"][0]
        top_line = by_line["groups"][0]
        top_equipment = by_equipment["groups"][0]
        reason_lines = [
            f"- {item['reason_category']}：{item['duration_min']:.0f} min，{item['count']} 次，占比 {item['duration_ratio'] * 100:.1f}%"
            for item in by_reason["groups"]
        ]
        key_reason_lines = [
            f"- {item['reason_category']}：累计占比 {item['cumulative_ratio'] * 100:.1f}%"
            for item in pareto["key_items"]
        ]
        hypothesis_lines = [f"- {item}" for item in root_causes["hypotheses"]]
        return f"""# ReAct 产线停机原因分析报告

## 核心结论
本月产线停机总时长为 {by_reason['total_duration_min']:.0f} min，共 {by_reason['total_count']} 次。首要原因是 **{top_reason['reason_category']}**，停机 {top_reason['duration_min']:.0f} min，占比 {top_reason['duration_ratio'] * 100:.1f}%。影响最明显的产线是 **{top_line['line_id']}**，关键设备是 **{top_equipment['equipment_id']}**。

## Top 原因
{chr(10).join(reason_lines)}

## Pareto 关键原因
{chr(10).join(key_reason_lines)}

## 根因假设
{chr(10).join(hypothesis_lines)}

## 可视化证据
- 图表文件：{chart['chart_path']}

## 分部门建议
- 设备部：优先处理 EQ-A01 送料模块重复故障，复盘维修闭环和备件匹配。
- 生产部：优化换线前检查清单，减少治具、物料、参数确认等待。
- 计划/物料部：对关键物料建立到料预警与配送窗口校验。
- 质量部：建立快速复检通道，降低质量异常停线等待。
"""


def save_trace(memory: AgentMemory) -> Dict[str, str]:
    ensure_outputs_dir()
    trace = {
        "user_query": memory.user_query,
        "task_tree_policy": TaskTreePolicy().completion_check(memory),
        "steps": [
            {"thought": step.thought, "action": step.action, "args": step.args, "observation": step.observation}
            for step in memory.steps
        ],
        "analysis_keys": list(memory.analysis.keys()),
        "final_answer": memory.final_answer,
    }
    trace_path = OUTPUT_DIR / "react_trace.json"
    answer_path = OUTPUT_DIR / "react_report.md"
    trace_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
    answer_path.write_text(memory.final_answer or "", encoding="utf-8")
    return {"trace_path": str(trace_path), "answer_path": str(answer_path)}
