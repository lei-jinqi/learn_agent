from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

from .dify_client import DifyCallResult, DifyClient
from .react_agent import ReActDowntimeAgent, TaskTreePolicy
from .tool_registry import build_default_registry
from .utils import OUTPUT_DIR, ensure_outputs_dir, load_task_tree


@dataclass
class CommanderDecision:
    task_id: str
    matched: bool
    confidence: float
    query_type: str
    planner_strategy: str
    reason: str


@dataclass
class SpecialistStep:
    agent_id: str
    agent_name: str
    role: str
    ok: bool
    elapsed_ms: float
    input_keys: List[str]
    output_key: str
    response_text: str
    error: str | None = None


@dataclass
class OrchestratorResult:
    user_query: str
    commander_decision: CommanderDecision
    local_analysis_report: str
    specialist_steps: List[SpecialistStep] = field(default_factory=list)
    final_report: str = ""
    evaluator: Dict[str, Any] = field(default_factory=dict)


class Commander:
    def __init__(self, task_tree: Dict[str, Any]) -> None:
        self.task_tree = task_tree

    def route(self, user_query: str) -> CommanderDecision:
        keywords = self.task_tree.get("intent", {}).get("keywords", [])
        hit_count = sum(1 for keyword in keywords if keyword in user_query)
        confidence = round(hit_count / max(len(keywords), 1), 3)
        has_time = any(word in user_query for word in ["本月", "这个月", "最近", "五月", "5月"])
        has_object = any(word in user_query for word in ["产线", "生产线", "停机", "停线"])
        has_goal = any(word in user_query for word in ["原因", "主因", "分析", "为什么"])
        matched = hit_count >= 2 and has_object
        is_standard = matched and has_time and has_goal
        return CommanderDecision(
            task_id=self.task_tree.get("task_id", "unknown"),
            matched=matched,
            confidence=confidence,
            query_type="standard_high_frequency" if is_standard else "ambiguous_or_open",
            planner_strategy="rule_first_hybrid" if is_standard else "llm_assisted_hybrid",
            reason="任务树关键词和必要槽位完整，走规则主路径。" if is_standard else "存在槽位缺失或语义模糊，需要 LLM/Dify 子 Agent 辅助澄清。",
        )


class ResultEvaluator:
    def evaluate(self, result: OrchestratorResult) -> Dict[str, Any]:
        required_sections = ["核心结论", "Top 原因", "根因假设", "分部门建议"]
        final_text = result.final_report or ""
        return {
            "matched_task": result.commander_decision.matched,
            "planner_strategy": result.commander_decision.planner_strategy,
            "specialist_agent_count": len(result.specialist_steps),
            "specialist_success_count": sum(1 for step in result.specialist_steps if step.ok),
            "dify_fallback_count": sum(1 for step in result.specialist_steps if not step.ok),
            "required_sections_hit": {section: section in final_text for section in required_sections},
            "has_local_evidence": bool(result.local_analysis_report),
            "passed": bool(result.local_analysis_report) and len(result.specialist_steps) == 3,
        }


class TaskTreeOrchestrator:
    def __init__(self) -> None:
        self.task_tree = load_task_tree()
        self.policy = TaskTreePolicy(self.task_tree)
        self.commander = Commander(self.task_tree)
        self.registry = build_default_registry()
        self.local_agent = ReActDowntimeAgent(registry=self.registry, policy=self.policy)
        self.dify_client = DifyClient()
        self.evaluator = ResultEvaluator()

    def run(self, user_query: str) -> OrchestratorResult:
        decision = self.commander.route(user_query)
        local_memory = self.local_agent.run(user_query)
        local_report = local_memory.final_answer or ""
        context: Dict[str, Any] = {
            "user_query": user_query,
            "commander_decision": asdict(decision),
            "task_tree": self.task_tree,
            "mock_data": self._load_required_mock_data(),
            "local_analysis": local_memory.analysis,
            "local_report": local_report,
        }
        result = OrchestratorResult(user_query=user_query, commander_decision=decision, local_analysis_report=local_report)

        current = self._invoke_specialist(
            "current_assessment",
            "请基于输入的本地 mock 数据和任务树要求，输出本月产线停机现状评估。重点包括总停机时长、停机次数、Top 产线、Top 设备、Top 原因和数据质量问题。",
            context,
            "current_assessment_result",
        )
        result.specialist_steps.append(current[0])
        context["current_assessment_result"] = current[1]

        cause = self._invoke_specialist(
            "cause_breakdown",
            "请承接现状评估结果，对停机原因做 Pareto 拆解，并结合设备报警、维修工单、缺料和质量异常证据输出根因假设、责任环节和置信度。",
            context,
            "cause_breakdown_result",
        )
        result.specialist_steps.append(cause[0])
        context["cause_breakdown_result"] = cause[1]

        conclusion = self._invoke_specialist(
            "conclusion_output",
            "请基于现状评估和原因拆解结果，生成可直接给生产、设备、计划物料和质量部门使用的最终业务分析结论。",
            context,
            "conclusion_output_result",
        )
        result.specialist_steps.append(conclusion[0])
        context["conclusion_output_result"] = conclusion[1]

        result.final_report = self._compose_final_report(local_report, result.specialist_steps)
        result.evaluator = self.evaluator.evaluate(result)
        return result

    def _invoke_specialist(self, agent_id: str, instruction: str, context: Dict[str, Any], output_key: str) -> tuple[SpecialistStep, str]:
        compact_context = self._compact_context(context)
        evidence_json = json.dumps(compact_context, ensure_ascii=False, indent=2)
        query = (
            f"{instruction}\n\n"
            "你必须严格使用下面【本地证据包】里的数据回答。"
            "如果你的原始提示词、知识库或历史示例与证据包冲突，以证据包为准。"
            "禁止编造产线、设备、月份、停机时长和次数。\n\n"
            f"【本地证据包】\n{evidence_json}"
        )
        inputs = {"context": compact_context, "task_id": self.task_tree.get("task_id")}
        call_result: DifyCallResult = self.dify_client.invoke(agent_id, query=query, inputs=inputs)
        agent = self.dify_client.get_agent(agent_id)
        step = SpecialistStep(
            agent_id=agent_id,
            agent_name=agent.name,
            role=agent.role,
            ok=call_result.ok,
            elapsed_ms=call_result.elapsed_ms,
            input_keys=sorted(compact_context.keys()),
            output_key=output_key,
            response_text=call_result.response_text,
            error=call_result.error,
        )
        return step, call_result.response_text

    def _load_required_mock_data(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        for table in self.task_tree.get("required_data", []):
            result = self.registry.get("query_table").run({"table": table, "month": self.task_tree.get("goal", {}).get("time_range", "2026-05")})
            data[table] = result.data if result.ok else {"error": result.error}
        return data

    @staticmethod
    def _compact_context(context: Dict[str, Any]) -> Dict[str, Any]:
        compact = {}
        for key, value in context.items():
            if key == "local_analysis" and isinstance(value, dict):
                compact[key] = {
                    analysis_key: analysis_value
                    for analysis_key, analysis_value in value.items()
                    if analysis_key in ["quality", "by_reason", "by_line", "by_equipment", "pareto_reason", "root_causes"]
                }
            elif key == "task_tree" and isinstance(value, dict):
                compact[key] = {
                    "task_id": value.get("task_id"),
                    "task_name": value.get("task_name"),
                    "required_data": value.get("required_data"),
                    "output_schema": value.get("output_schema"),
                }
            elif key == "mock_data" and isinstance(value, dict):
                compact[key] = {
                    table_name: {
                        "row_count": table_data.get("row_count"),
                        "rows": table_data.get("rows", []),
                    }
                    for table_name, table_data in value.items()
                }
            else:
                compact[key] = value
        return compact

    @staticmethod
    def _compose_final_report(local_report: str, steps: List[SpecialistStep]) -> str:
        specialist_sections = []
        for step in steps:
            status = "成功" if step.ok else "本地降级"
            specialist_sections.append(
                f"## {step.role}：{step.agent_name}\n\n"
                f"- 调用状态：{status}\n"
                f"- 耗时：{step.elapsed_ms} ms\n"
                f"- 输出：\n\n{step.response_text}\n"
            )
        return "# Commander 调度 + Dify 子 Agent 产线停机分析报告\n\n" + local_report + "\n\n# Dify 子 Agent 调用结果\n\n" + "\n".join(specialist_sections)


def save_orchestrator_result(result: OrchestratorResult) -> Dict[str, str]:
    ensure_outputs_dir()
    result_path = OUTPUT_DIR / "orchestrated_result.json"
    report_path = OUTPUT_DIR / "orchestrated_report.md"
    payload = {
        "user_query": result.user_query,
        "commander_decision": asdict(result.commander_decision),
        "specialist_steps": [asdict(step) for step in result.specialist_steps],
        "evaluator": result.evaluator,
        "final_report": result.final_report,
    }
    result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(result.final_report, encoding="utf-8")
    return {"result_path": str(result_path), "report_path": str(report_path)}
