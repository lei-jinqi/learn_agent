# 产线停机分析 Agent

你现在只需要看一个入口：这个项目是用来学习 Agent 和产线停机分析的。

```bat
python run.py
```

如果 Windows 控制台中文乱码，用：

```bat
set PYTHONIOENCODING=utf-8 && python run.py
```

## 项目主链路

```text
Commander -> TaskTreePolicy -> Hybrid Planner -> Local ReAct Agent -> Dify 子 Agent -> Evaluator
```

## 目录说明

```text
line-downtime-agent/
├── run.py                         # 唯一推荐运行入口
├── app/
│   ├── orchestrator.py             # Commander + 编排 + Evaluator
│   ├── dify_client.py              # Dify streaming 调用客户端
│   ├── react_agent.py              # 本地 ReAct 工具调用 Agent
│   ├── tool_registry.py            # 本地 mock 数据工具和分析工具
│   └── utils.py                    # 路径和配置加载
├── config/
│   ├── task_tree.json              # 任务树约束
│   ├── dify_agents.json            # 从 PDF curl 落下来的 Dify Agent 配置
│   └── dify_curl_source.md         # curl 来源说明
├── data/                           # 本地 mock 数据
└── outputs/                        # 运行输出
```

## Dify 为什么之前超时

你的 Postman 能跑通，是因为 PDF 里的 curl 使用的是 `streaming`。之前项目里按 `blocking` 调，并用普通 `response.read()` 等完整响应结束；如果 Dify 服务按 SSE 流式返回，连接可能不会立刻关闭，于是本地等到超时。

现在已经修复：

- `config/dify_agents.json` 改回 `response_mode: streaming`。
- `app/dify_client.py` 按 SSE 逐行读取。
- 读到 `message_end` 或 `workflow_finished` 就主动结束。
- 超时时间改成 60 秒。

## curl 是怎么导入项目的

项目不是直接执行 curl，而是把 curl 拆成配置和 Python 请求：

- curl 的 URL -> `config/dify_agents.json` 里的 `base_url`
- curl 的 Bearer token -> 每个 Agent 的 `api_key`
- curl 的 `response_mode` -> `response_mode`
- curl 的 `data-raw` -> `app/dify_client.py` 里的 payload

原始 curl 摘要保存在：

```text
config/dify_curl_source.md
```

## 输出文件

运行后看：

```text
outputs/orchestrated_report.md
outputs/orchestrated_result.json
```

## 当前保留的核心文件

- `run.py`：唯一入口。
- `app/orchestrator.py`：总指挥层，判断走规则还是大模型辅助，并串起子 Agent。
- `app/dify_client.py`：真正调用 Dify 的地方。
- `app/react_agent.py`：本地 ReAct 分析链路。
- `app/tool_registry.py`：读取 mock 数据并计算指标。
- `config/dify_agents.json`：Dify 子 Agent 配置。
- `config/task_tree.json`：任务树。
