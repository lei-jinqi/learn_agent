from __future__ import annotations

import json

from app.orchestrator import TaskTreeOrchestrator, save_orchestrator_result


def main() -> None:
    query = "帮我分析一下这个月产线停机的主要原因"
    orchestrator = TaskTreeOrchestrator()
    result = orchestrator.run(query)
    paths = save_orchestrator_result(result)

    print(result.final_report)
    print("\n--- 运行摘要 ---")
    print(
        json.dumps(
            {
                "入口文件": "run.py",
                "问题": query,
                "commander_decision": result.commander_decision.__dict__,
                "dify_agent_count": len(result.specialist_steps),
                "dify_success_count": sum(1 for step in result.specialist_steps if step.ok),
                "evaluator": result.evaluator,
                **paths,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
