from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .utils import CONFIG_DIR


@dataclass
class DifyAgentConfig:
    id: str
    name: str
    role: str
    api_key: str
    task_tree_node: str
    description: str
    input_contract: List[str]
    output_contract: List[str]
    source_curl: str = ""


@dataclass
class DifyCallResult:
    agent_id: str
    agent_name: str
    called: bool
    ok: bool
    elapsed_ms: float
    request_query: str
    response_text: str
    raw: Dict[str, Any]
    error: Optional[str] = None


class DifyClient:
    """Dify chat-messages client.

    注意：PDF 里的 curl 使用的是 response_mode=streaming。
    如果用普通 response.read() 等完整响应结束，流式接口可能一直不关闭，表现为本地超时；
    所以这里按 SSE 逐行读取，并在 message_end / agent_message 后主动结束。
    """

    def __init__(self, config_path: Optional[str] = None, timeout: int = 30) -> None:
        self.config = self._load_config(config_path)
        self.base_url = self.config["base_url"]
        self.response_mode = self.config.get("response_mode", "streaming")
        self.user = self.config.get("user", "line-downtime-local-orchestrator")
        self.enable_real_calls = bool(self.config.get("enable_real_calls", True))
        self.timeout = int(self.config.get("timeout_seconds", timeout))
        self.agents = {
            item["id"]: DifyAgentConfig(
                id=item["id"],
                name=item["name"],
                role=item["role"],
                api_key=item["api_key"],
                task_tree_node=item["task_tree_node"],
                description=item["description"],
                input_contract=item.get("input_contract", []),
                output_contract=item.get("output_contract", []),
                source_curl=item.get("source_curl", ""),
            )
            for item in self.config.get("agents", [])
        }

    @staticmethod
    def _load_config(config_path: Optional[str]) -> Dict[str, Any]:
        path = CONFIG_DIR / "dify_agents.json" if config_path is None else CONFIG_DIR / config_path
        return json.loads(path.read_text(encoding="utf-8"))

    def list_agents(self) -> List[Dict[str, Any]]:
        return [agent.__dict__ for agent in self.agents.values()]

    def get_agent(self, agent_id: str) -> DifyAgentConfig:
        if agent_id not in self.agents:
            raise KeyError(f"Unknown Dify agent: {agent_id}")
        return self.agents[agent_id]

    def invoke(self, agent_id: str, query: str, inputs: Optional[Dict[str, Any]] = None) -> DifyCallResult:
        agent = self.get_agent(agent_id)
        if not self.enable_real_calls:
            return DifyCallResult(
                agent_id=agent.id,
                agent_name=agent.name,
                called=False,
                ok=False,
                elapsed_ms=0.0,
                request_query=query,
                response_text=self._fallback_response(agent, inputs or {}, "Dify real call is disabled by config"),
                raw={"fallback": True, "disabled_by_config": True},
                error="Dify real call is disabled by config",
            )

        payload = {
            "inputs": inputs or {},
            "query": query,
            "response_mode": self.response_mode,
            "conversation_id": "",
            "user": self.user,
            "files": [],
        }
        start = time.perf_counter()
        try:
            request = urllib.request.Request(
                self.base_url,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                method="POST",
                headers={
                    "Authorization": f"Bearer {agent.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream" if self.response_mode == "streaming" else "application/json",
                },
            )
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                if self.response_mode == "streaming":
                    parsed = self._read_streaming_response(response)
                else:
                    body = response.read().decode("utf-8", errors="replace")
                    parsed = self._parse_response_body(body)

            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
            text = parsed.get("answer") or parsed.get("text") or json.dumps(parsed, ensure_ascii=False)
            return DifyCallResult(
                agent_id=agent.id,
                agent_name=agent.name,
                called=True,
                ok=True,
                elapsed_ms=elapsed_ms,
                request_query=query,
                response_text=text,
                raw=parsed,
            )
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
            return DifyCallResult(
                agent_id=agent.id,
                agent_name=agent.name,
                called=True,
                ok=False,
                elapsed_ms=elapsed_ms,
                request_query=query,
                response_text=self._fallback_response(agent, inputs or {}, str(exc)),
                raw={"fallback": True},
                error=str(exc),
            )

    def _read_streaming_response(self, response: Any) -> Dict[str, Any]:
        answer_chunks: List[str] = []
        events: List[Dict[str, Any]] = []
        deadline = time.perf_counter() + self.timeout

        while time.perf_counter() < deadline:
            raw_line = response.readline()
            if not raw_line:
                break
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line or not line.startswith("data:"):
                continue

            data = line.removeprefix("data:").strip()
            if data == "[DONE]":
                break

            event = json.loads(data)
            events.append(event)
            event_name = event.get("event")
            answer = event.get("answer")
            if answer:
                answer_chunks.append(answer)

            if event_name in {"message_end", "workflow_finished"}:
                break

        return {"answer": "".join(answer_chunks), "streaming": True, "events": events}

    @staticmethod
    def _parse_response_body(body: str) -> Dict[str, Any]:
        stripped = body.strip()
        if not stripped:
            return {"text": ""}
        if stripped.startswith("data:"):
            chunks = []
            events = []
            for line in stripped.splitlines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    continue
                event = json.loads(data)
                events.append(event)
                answer = event.get("answer") or event.get("data", {}).get("answer")
                if answer:
                    chunks.append(answer)
            return {"answer": "".join(chunks), "streaming": True, "events": events}
        return json.loads(stripped)

    @staticmethod
    def _fallback_response(agent: DifyAgentConfig, inputs: Dict[str, Any], error: str) -> str:
        available_keys = ", ".join(sorted(inputs.keys()))
        return (
            f"【本地降级结果】{agent.role} 未能成功访问 Dify 服务，已使用本地上下文生成占位输出。"
            f"\n失败原因：{error}"
            f"\n已传入上下文：{available_keys}"
            f"\n该子 Agent 的职责：{agent.description}"
        )
