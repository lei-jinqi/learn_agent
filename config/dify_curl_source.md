# Dify curl 来源说明

本文件记录从 `../S25：智能体.pdf` 抽取并落到项目配置里的 curl 信息。

项目并不是直接执行 curl 命令，而是把 curl 里的四类信息翻译成 `config/dify_agents.json`：

- URL -> `base_url`
- Authorization Bearer -> 每个 Agent 的 `api_key`
- response_mode -> `response_mode`
- data-raw 请求体 -> `app/dify_client.py` 里的 Python HTTP payload

## 1. 现状评估 Agent

```bash
curl -X POST 'http://101.69.166.71:10081/v1/chat-messages' \
--header 'Authorization: Bearer app-3M151UInNwBLUyU33u8GPDrO' \
--header 'Content-Type: application/json' \
--data-raw '{
  "inputs": {},
  "query": "...",
  "response_mode": "streaming",
  "conversation_id": "",
  "user": "abc-123",
  "files": []
}'
```

## 2. 原因拆解 Agent

```bash
curl -X POST 'http://101.69.166.71:10081/v1/chat-messages' \
--header 'Authorization: Bearer app-QOrzUjepgXaXZUpaiXL8uOF6' \
--header 'Content-Type: application/json' \
--data-raw '{
  "inputs": {},
  "query": "...",
  "response_mode": "streaming",
  "conversation_id": "",
  "user": "abc-123",
  "files": []
}'
```

## 3. 结论输出 Agent

```bash
curl -X POST 'http://101.69.166.71:10081/v1/chat-messages' \
--header 'Authorization: Bearer app-EOAYQu0SFzY6ismhDIvfK1Xz' \
--header 'Content-Type: application/json' \
--data-raw '{
  "inputs": {},
  "query": "...",
  "response_mode": "streaming",
  "conversation_id": "",
  "user": "abc-123",
  "files": []
}'
```

## 为什么之前会超时

PDF 和 Postman 里的请求是 `response_mode=streaming`，也就是服务端按 SSE 流式返回。之前项目里把它改成了 `blocking`，而且客户端用 `response.read()` 等完整响应结束；如果服务端实际按流式返回或迟迟不关闭连接，本地就会等到超时。

现在 `app/dify_client.py` 已改成按 `streaming` 逐行读取，读到 `message_end` / `workflow_finished` 就主动结束。
