# 产线停机 Agent 项目啃代码指南

这份文档解决两个问题：

1. 当前项目到底是不是 LangGraph。
2. 从运行入口开始，整个项目的函数、类、配置是按什么顺序被调度的。

---

## 0. 先回答：当前项目不是 LangGraph

当前项目不是 LangGraph 项目，而是一个“手写版 Agent 编排原型”。

原因很简单：项目里没有引入 LangGraph 依赖，也没有使用 LangGraph 的图节点、边、状态图编译能力。当前项目用普通 Python 代码手写了类似 Agent 编排框架的核心机制：

- 指挥官路由：[`Commander`](../app/orchestrator.py:46)
- 任务树约束：[`TaskTreePolicy`](../app/react_agent.py:35)
- 本地 Agent 循环：[`ReActDowntimeAgent`](../app/react_agent.py:162)
- 规则 Planner：[`RuleBasedPlanner`](../app/react_agent.py:78)
- 工具注册与调用：[`ToolRegistry`](../app/tool_registry.py:40)
- Dify 子 Agent 调用：[`DifyClient`](../app/dify_client.py:39)
- 结果评估：[`ResultEvaluator`](../app/orchestrator.py:69)

所以你现在可以这样理解：

> 这个项目还不是 LangGraph，但它已经具备 LangGraph 项目里最核心的工程思想：状态、节点、工具、编排、外部 Agent 调用、结果评估。

如果以后要改成 LangGraph，不是推倒重写，而是把现在这些模块映射成 LangGraph 节点。

---

## 1. 整体运行链路，一句话版

你只需要先记住这条主线：

```text
python run.py
  -> main
  -> TaskTreeOrchestrator 初始化
  -> TaskTreeOrchestrator.run
  -> Commander.route
  -> ReActDowntimeAgent.run
  -> RuleBasedPlanner.next_action
  -> ToolRegistry.get
  -> Tool.run
  -> 反复调用 query_table / aggregate_downtime / pareto_analysis 等工具
  -> DifyClient.invoke 调用 3 个 Dify 子 Agent
  -> ResultEvaluator.evaluate
  -> save_orchestrator_result
  -> 输出报告和 JSON 结果
```

注意：上面这段是阅读地图，不是让你背。你啃代码的时候，只要能把每一段代码放回这条链路里，就不会迷路。

---

## 2. 第一层：运行入口

### 2.1 从哪里开始跑

入口文件是 [`run.py`](../run.py:1)。真正开始执行的是 [`main()`](../run.py:8)。

[`main()`](../run.py:8) 里做了 4 件事：

1. 写死一个用户问题：“帮我分析一下这个月产线停机的主要原因”。
2. 创建总编排器 [`TaskTreeOrchestrator`](../app/orchestrator.py:85)。
3. 调用 [`TaskTreeOrchestrator.run()`](../app/orchestrator.py:95) 执行完整 Agent 链路。
4. 调用 [`save_orchestrator_result()`](../app/orchestrator.py:216) 保存结果。

对应运行顺序：

| 顺序 | 代码位置 | 做什么 |
|---|---|---|
| 1 | [`main()`](../run.py:8) | 程序入口 |
| 2 | [`TaskTreeOrchestrator`](../app/orchestrator.py:85) | 创建总调度器 |
| 3 | [`TaskTreeOrchestrator.run()`](../app/orchestrator.py:95) | 执行完整链路 |
| 4 | [`save_orchestrator_result()`](../app/orchestrator.py:216) | 保存报告和结构化结果 |

你啃项目时，永远先从 [`run.py`](../run.py:1) 开始，不要从工具函数开始看。

---

## 3. 第二层：总编排器初始化

当 [`main()`](../run.py:8) 执行到创建 [`TaskTreeOrchestrator`](../app/orchestrator.py:85) 时，会进入 [`TaskTreeOrchestrator.__init__()`](../app/orchestrator.py:86)。

这里是在组装系统的各个部件：

| 成员 | 来源 | 作用 |
|---|---|---|
| 任务树 | [`load_task_tree()`](../app/utils.py:15) | 读取任务定义和边界 |
| 任务策略 | [`TaskTreePolicy`](../app/react_agent.py:35) | 约束允许哪些数据、哪些工具、哪些输出 |
| 指挥官 | [`Commander`](../app/orchestrator.py:46) | 判断用户问题属于什么任务 |
| 工具注册表 | [`build_default_registry()`](../app/tool_registry.py:233) | 注册所有可调用工具 |
| 本地 Agent | [`ReActDowntimeAgent`](../app/react_agent.py:162) | 执行本地工具调用分析 |
| Dify 客户端 | [`DifyClient`](../app/dify_client.py:39) | 调用外部 Dify 子 Agent |
| 评估器 | [`ResultEvaluator`](../app/orchestrator.py:69) | 检查结果是否合格 |

这一段你要这样理解：

> [`TaskTreeOrchestrator.__init__()`](../app/orchestrator.py:86) 不是业务分析逻辑，它是在搭舞台，把后面要用的角色全部准备好。

---

## 4. 第三层：主调度函数

整个项目最重要的函数是 [`TaskTreeOrchestrator.run()`](../app/orchestrator.py:95)。

它是主流程，建议你把它打印出来贴在旁边看。

### 4.1 主流程拆解

[`TaskTreeOrchestrator.run()`](../app/orchestrator.py:95) 的执行顺序如下：

| 顺序 | 代码位置 | 动作 | 结果 |
|---|---|---|---|
| 1 | [`Commander.route()`](../app/orchestrator.py:50) | 判断用户问题是否匹配任务树 | 得到路由决策 |
| 2 | [`ReActDowntimeAgent.run()`](../app/react_agent.py:175) | 本地 Agent 调工具分析数据 | 得到本地分析报告 |
| 3 | [`TaskTreeOrchestrator._load_required_mock_data()`](../app/orchestrator.py:166) | 加载任务要求的 mock 数据 | 得到证据包数据 |
| 4 | [`TaskTreeOrchestrator._invoke_specialist()`](../app/orchestrator.py:140) | 调用现状评估 Dify 子 Agent | 得到现状评估输出 |
| 5 | [`TaskTreeOrchestrator._invoke_specialist()`](../app/orchestrator.py:140) | 调用原因拆解 Dify 子 Agent | 得到原因拆解输出 |
| 6 | [`TaskTreeOrchestrator._invoke_specialist()`](../app/orchestrator.py:140) | 调用结论输出 Dify 子 Agent | 得到最终结论输出 |
| 7 | [`TaskTreeOrchestrator._compose_final_report()`](../app/orchestrator.py:202) | 合成本地报告和 Dify 输出 | 得到最终 Markdown 报告 |
| 8 | [`ResultEvaluator.evaluate()`](../app/orchestrator.py:70) | 检查结果完整性 | 得到评估结果 |

### 4.2 你读这段代码时要抓什么

不要被变量名绕晕。你只要抓住 3 个对象：

1. 路由决策对象：[`CommanderDecision`](../app/orchestrator.py:13)
2. 子 Agent 调用记录：[`SpecialistStep`](../app/orchestrator.py:23)
3. 总结果对象：[`OrchestratorResult`](../app/orchestrator.py:36)

这 3 个对象就是系统运行过程中的关键产物。

---

## 5. 第四层：Commander 怎么判断问题

[`Commander.route()`](../app/orchestrator.py:50) 做的是“问题识别”。

它会从任务树里读取关键词，然后判断用户问题里有没有命中这些关键词。

任务树配置在 [`config/task_tree.json`](../config/task_tree.json:1)。关键词在 [`config/task_tree.json`](../config/task_tree.json:5)。

判断逻辑大概是：

| 判断项 | 代码位置 | 意义 |
|---|---|---|
| 关键词命中数 | [`Commander.route()`](../app/orchestrator.py:50) | 判断问题是不是属于当前任务 |
| 是否有时间信息 | [`Commander.route()`](../app/orchestrator.py:50) | 判断是不是标准高频问题 |
| 是否有分析对象 | [`Commander.route()`](../app/orchestrator.py:50) | 判断是不是产线停机相关 |
| 是否有分析目标 | [`Commander.route()`](../app/orchestrator.py:50) | 判断用户是不是要原因分析 |

输出结果会放进 [`CommanderDecision`](../app/orchestrator.py:13)。

你要这样理解：

> Commander 是系统入口的门卫。它不负责分析数据，只负责判断这个问题该不该进入这条任务链路。

---

## 6. 第五层：本地 ReAct Agent 怎么跑

本地 Agent 的入口是 [`ReActDowntimeAgent.run()`](../app/react_agent.py:175)。

它的循环逻辑是这个：

```text
创建 AgentMemory
循环最多 20 步：
  Planner 根据当前 Memory 选择下一步动作
  Policy 检查这个动作是否允许
  如果动作是 finish：
    检查任务是否完成
    生成最终本地报告
    返回 Memory
  否则：
    从 ToolRegistry 取工具
    执行工具
    把工具结果写回 Memory
    记录本轮 Step
```

### 6.1 关键对象

| 对象 | 代码位置 | 作用 |
|---|---|---|
| 单步记录 | [`Step`](../app/react_agent.py:11) | 保存 Thought、Action、Observation |
| Agent 记忆 | [`AgentMemory`](../app/react_agent.py:19) | 保存数据、分析结果、步骤、最终答案 |
| 任务约束 | [`TaskTreePolicy`](../app/react_agent.py:35) | 控制允许哪些工具，检查是否完成 |
| 规则规划器 | [`RuleBasedPlanner`](../app/react_agent.py:78) | 决定下一步调用什么工具 |
| 本地 Agent | [`ReActDowntimeAgent`](../app/react_agent.py:162) | 执行完整工具调用循环 |

### 6.2 这里为什么叫 ReAct

ReAct 的核心是：

```text
Thought -> Action -> Observation -> Next Thought
```

在当前项目里：

- Thought 存在 [`Step`](../app/react_agent.py:11) 的 thought 字段。
- Action 是工具名，由 [`RuleBasedPlanner.next_action()`](../app/react_agent.py:88) 产生。
- Observation 是工具返回结果，在 [`ReActDowntimeAgent.run()`](../app/react_agent.py:175) 中写入。
- Memory 是 [`AgentMemory`](../app/react_agent.py:19)，负责保存整个过程。

这不是 LangGraph，但它已经是一个清晰的 Agent loop。

---

## 7. 第六层：Planner 的动作顺序

[`RuleBasedPlanner.next_action()`](../app/react_agent.py:88) 是当前项目里最适合你“啃”的函数之一。

它根据当前 [`AgentMemory`](../app/react_agent.py:19) 判断下一步缺什么，然后返回下一步动作。

它的动作顺序是：

| 顺序 | 条件 | 返回动作 | 工具位置 |
|---|---|---|---|
| 1 | 缺任意必需数据表 | query_table | [`query_table()`](../app/tool_registry.py:69) |
| 2 | 缺数据质量检查 | data_quality_check | [`data_quality_check()`](../app/tool_registry.py:76) |
| 3 | 缺原因维度聚合 | aggregate_downtime | [`aggregate_downtime()`](../app/tool_registry.py:94) |
| 4 | 缺产线维度聚合 | aggregate_downtime | [`aggregate_downtime()`](../app/tool_registry.py:94) |
| 5 | 缺设备维度聚合 | aggregate_downtime | [`aggregate_downtime()`](../app/tool_registry.py:94) |
| 6 | 缺 Pareto 分析 | pareto_analysis | [`pareto_analysis()`](../app/tool_registry.py:126) |
| 7 | 缺根因关联 | correlate_root_causes | [`correlate_root_causes()`](../app/tool_registry.py:144) |
| 8 | 缺图表 | generate_svg_chart | [`generate_svg_chart()`](../app/tool_registry.py:179) |
| 9 | 全部完成 | finish | [`ReActDowntimeAgent.run()`](../app/react_agent.py:175) 内处理 |

注意：这不是“固定写死每一步直接执行”，而是每轮都根据 [`AgentMemory`](../app/react_agent.py:19) 判断当前还缺什么。

所以你可以把它理解为：规则版 Planner。

---

## 8. 第七层：工具是怎么被调用的

工具系统在 [`tool_registry.py`](../app/tool_registry.py:1)。

### 8.1 工具注册

所有工具是在 [`build_default_registry()`](../app/tool_registry.py:233) 里注册的。

它会创建 [`ToolRegistry`](../app/tool_registry.py:40)，然后把每个工具包装成 [`Tool`](../app/tool_registry.py:24) 后注册进去。

### 8.2 工具调用

当 [`ReActDowntimeAgent.run()`](../app/react_agent.py:175) 拿到 Planner 返回的动作后，会执行：

1. 通过 [`ToolRegistry.get()`](../app/tool_registry.py:47) 根据工具名取工具。
2. 调用 [`Tool.run()`](../app/tool_registry.py:31) 执行具体工具函数。
3. 工具返回 [`ToolResult`](../app/tool_registry.py:16)。
4. 如果成功，把工具结果写回 [`AgentMemory`](../app/react_agent.py:19)。

### 8.3 工具职责表

| 工具 | 代码位置 | 职责 |
|---|---|---|
| 查询 CSV 表 | [`query_table()`](../app/tool_registry.py:69) | 从本地 mock 数据读取指定月份的数据 |
| 数据质量检查 | [`data_quality_check()`](../app/tool_registry.py:76) | 检查必要字段是否缺失 |
| 停机聚合 | [`aggregate_downtime()`](../app/tool_registry.py:94) | 按原因、产线、设备聚合停机时长和次数 |
| Pareto 分析 | [`pareto_analysis()`](../app/tool_registry.py:126) | 找出关键少数原因 |
| 根因关联 | [`correlate_root_causes()`](../app/tool_registry.py:144) | 关联报警、维修、缺料、质量证据 |
| 图表生成 | [`generate_svg_chart()`](../app/tool_registry.py:179) | 生成 SVG 可视化 |
| 旧版 Dify 工具 | [`call_dify_agent()`](../app/tool_registry.py:210) | 保留的通用 Dify 工具，当前主链路不用它 |

重点记住：当前主链路调用 Dify 是通过 [`DifyClient`](../app/dify_client.py:39)，不是通过 [`call_dify_agent()`](../app/tool_registry.py:210)。

---

## 9. 第八层：本地 Agent 输出什么

当本地工具调用全部完成后，会进入 [`ReActDowntimeAgent._compose_final_answer()`](../app/react_agent.py:220)。

它会从 [`AgentMemory`](../app/react_agent.py:19) 里拿这些结果：

- 原因维度聚合结果
- 产线维度聚合结果
- 设备维度聚合结果
- Pareto 分析结果
- 根因假设结果
- 图表路径

然后生成本地 Markdown 报告。

这个本地报告会被放进 [`TaskTreeOrchestrator.run()`](../app/orchestrator.py:95) 里的上下文，继续传给 Dify 子 Agent。

---

## 10. 第九层：Dify 子 Agent 怎么接入

Dify 配置在 [`config/dify_agents.json`](../config/dify_agents.json:1)。

Dify 客户端在 [`DifyClient`](../app/dify_client.py:39)。

### 10.1 Dify 配置读取

创建 [`DifyClient`](../app/dify_client.py:39) 时，会执行 [`DifyClient.__init__()`](../app/dify_client.py:47)。

它会读取 [`config/dify_agents.json`](../config/dify_agents.json:1)，并把每个子 Agent 转成 [`DifyAgentConfig`](../app/dify_client.py:13)。

### 10.2 子 Agent 调用顺序

在 [`TaskTreeOrchestrator.run()`](../app/orchestrator.py:95) 中，Dify 子 Agent 被调用 3 次：

| 顺序 | Agent 配置 | 业务角色 | 调用函数 |
|---|---|---|---|
| 1 | current_assessment | 现状评估 | [`TaskTreeOrchestrator._invoke_specialist()`](../app/orchestrator.py:140) |
| 2 | cause_breakdown | 原因拆解 | [`TaskTreeOrchestrator._invoke_specialist()`](../app/orchestrator.py:140) |
| 3 | conclusion_output | 结论输出 | [`TaskTreeOrchestrator._invoke_specialist()`](../app/orchestrator.py:140) |

### 10.3 每次调用 Dify 前做了什么

每次进入 [`TaskTreeOrchestrator._invoke_specialist()`](../app/orchestrator.py:140) 时，会做这些事：

1. 调用 [`TaskTreeOrchestrator._compact_context()`](../app/orchestrator.py:173) 压缩上下文。
2. 把上下文转成“本地证据包”。
3. 把证据包拼进 query，要求 Dify 必须基于证据回答。
4. 调用 [`DifyClient.invoke()`](../app/dify_client.py:82) 发 HTTP 请求。
5. 把调用结果包装成 [`SpecialistStep`](../app/orchestrator.py:23)。

这里最关键的是“本地证据包”。它解决的是 Dify 大模型容易编造的问题。

### 10.4 为什么不会再像之前那样超时

因为 [`config/dify_agents.json`](../config/dify_agents.json:1) 里使用的是 streaming 响应模式，而 [`DifyClient.invoke()`](../app/dify_client.py:82) 会在 streaming 模式下调用 [`DifyClient._read_streaming_response()`](../app/dify_client.py:150)。

[`DifyClient._read_streaming_response()`](../app/dify_client.py:150) 会一行一行读取 SSE 数据，并在 message_end 或 workflow_finished 时停止。

这就是之前 Postman 能跑、本地会超时的根因修复点。

---

## 11. 第十层：最终报告和评估

Dify 三个子 Agent 调完之后，回到 [`TaskTreeOrchestrator.run()`](../app/orchestrator.py:95)。

后面会做两件事：

1. 调用 [`TaskTreeOrchestrator._compose_final_report()`](../app/orchestrator.py:202) 合成最终报告。
2. 调用 [`ResultEvaluator.evaluate()`](../app/orchestrator.py:70) 检查结果是否通过。

[`ResultEvaluator.evaluate()`](../app/orchestrator.py:70) 目前检查这些内容：

- 是否命中任务。
- Planner 策略是什么。
- Dify 子 Agent 调了几个。
- Dify 子 Agent 成功几个。
- 最终报告有没有核心章节。
- 是否有本地证据。
- 是否通过基础检查。

最后 [`save_orchestrator_result()`](../app/orchestrator.py:216) 会保存两个文件：

- [`outputs/orchestrated_result.json`](../outputs/orchestrated_result.json:1)
- [`outputs/orchestrated_report.md`](../outputs/orchestrated_report.md:1)

---

## 12. 按调用栈啃代码

如果你不知道怎么读，就严格按这个顺序打开文件。

### 第 1 步：入口

看 [`run.py`](../run.py:1)。

只看懂一件事：程序从 [`main()`](../run.py:8) 进入，然后调用 [`TaskTreeOrchestrator.run()`](../app/orchestrator.py:95)。

---

### 第 2 步：总流程

看 [`TaskTreeOrchestrator.run()`](../app/orchestrator.py:95)。

只看懂一件事：它按顺序调度 Commander、本地 Agent、Dify 子 Agent、Evaluator。

---

### 第 3 步：任务识别

看 [`Commander.route()`](../app/orchestrator.py:50)。

只看懂一件事：它根据 [`config/task_tree.json`](../config/task_tree.json:1) 的关键词判断用户问题是不是当前任务。

---

### 第 4 步：本地 Agent 循环

看 [`ReActDowntimeAgent.run()`](../app/react_agent.py:175)。

只看懂一件事：它不断让 Planner 选动作，然后调工具，把结果写回 Memory。

---

### 第 5 步：Planner

看 [`RuleBasedPlanner.next_action()`](../app/react_agent.py:88)。

只看懂一件事：它根据 [`AgentMemory`](../app/react_agent.py:19) 判断还缺什么，然后返回下一个工具名。

---

### 第 6 步：工具层

看 [`build_default_registry()`](../app/tool_registry.py:233)，再看每个工具函数。

只看懂一件事：工具是稳定做计算和取数的，不应该让大模型负责这些确定性工作。

---

### 第 7 步：Dify 接入

看 [`TaskTreeOrchestrator._invoke_specialist()`](../app/orchestrator.py:140) 和 [`DifyClient.invoke()`](../app/dify_client.py:82)。

只看懂一件事：本地分析结果会作为证据包传给 Dify 子 Agent。

---

### 第 8 步：评估和输出

看 [`ResultEvaluator.evaluate()`](../app/orchestrator.py:70) 和 [`save_orchestrator_result()`](../app/orchestrator.py:216)。

只看懂一件事：Agent 不是输出了就结束，还要检查输出是否可信。

---

## 13. 按“数据流”啃代码

除了调用顺序，你还要理解数据是怎么流动的。

```text
用户问题
  -> CommanderDecision
  -> AgentMemory
  -> memory.data
  -> memory.analysis
  -> local_report
  -> context
  -> compact_context
  -> Dify query + inputs
  -> SpecialistStep
  -> final_report
  -> evaluator
  -> outputs
```

对应代码位置：

| 数据 | 创建位置 | 作用 |
|---|---|---|
| 用户问题 | [`main()`](../run.py:8) | 原始输入 |
| 路由决策 | [`Commander.route()`](../app/orchestrator.py:50) | 判断任务类型 |
| Agent 记忆 | [`AgentMemory`](../app/react_agent.py:19) | 保存工具调用过程 |
| 本地数据 | [`query_table()`](../app/tool_registry.py:69) | 作为分析证据 |
| 分析结果 | [`aggregate_downtime()`](../app/tool_registry.py:94) 等工具 | 形成指标和根因证据 |
| 本地报告 | [`ReActDowntimeAgent._compose_final_answer()`](../app/react_agent.py:220) | 给用户和 Dify 使用 |
| Dify 上下文 | [`TaskTreeOrchestrator._compact_context()`](../app/orchestrator.py:173) | 控制传给 Dify 的证据范围 |
| Dify 调用记录 | [`SpecialistStep`](../app/orchestrator.py:23) | 记录每个子 Agent 输出 |
| 最终报告 | [`TaskTreeOrchestrator._compose_final_report()`](../app/orchestrator.py:202) | 用户看到的完整报告 |
| 评估结果 | [`ResultEvaluator.evaluate()`](../app/orchestrator.py:70) | 判断结果是否可靠 |

---

## 14. 如果改成 LangGraph，怎么映射

当前项目不是 LangGraph，但很容易映射。

| 当前模块 | 未来 LangGraph 里的角色 |
|---|---|
| [`Commander.route()`](../app/orchestrator.py:50) | router node |
| [`ReActDowntimeAgent.run()`](../app/react_agent.py:175) | local_analysis node 或子图 |
| [`RuleBasedPlanner.next_action()`](../app/react_agent.py:88) | conditional edge 逻辑 |
| [`query_table()`](../app/tool_registry.py:69) | tool node |
| [`aggregate_downtime()`](../app/tool_registry.py:94) | tool node |
| [`pareto_analysis()`](../app/tool_registry.py:126) | tool node |
| [`TaskTreeOrchestrator._invoke_specialist()`](../app/orchestrator.py:140) | dify_specialist node |
| [`ResultEvaluator.evaluate()`](../app/orchestrator.py:70) | evaluator node |
| [`OrchestratorResult`](../app/orchestrator.py:36) | graph final state |

所以我之前说“以后可以改成 LangGraph”，不是说当前项目已经是 LangGraph，而是说：

> 现在项目先把 Agent 系统的职责边界写清楚；后面换 LangGraph，只是把这些职责挂到图节点上。

---

## 15. 当前项目里你先别啃的内容

为了降低负担，有些内容你可以暂时不看：

1. [`call_dify_agent()`](../app/tool_registry.py:210)：这是旧版通用 Dify 工具，当前主链路不用。
2. [`save_trace()`](../app/react_agent.py:266)：当前一键入口没有调用它，先不用管。
3. [`add_log()`](../app/utils.py:24)：当前主链路没重点使用。
4. [`now_ms()`](../app/utils.py:20)：只是日志时间工具。

你现在优先看主链路，不要被边缘函数干扰。

---

## 16. 你应该如何在代码里做标注

建议你在本地边看边写注释，但不要急着改代码。

你可以按这 4 类标注：

1. 入口：这个函数从哪里被调用。
2. 输入：这个函数吃什么数据。
3. 输出：这个函数返回什么数据。
4. 责任：这个函数在业务链路里解决什么问题。

比如看 [`aggregate_downtime()`](../app/tool_registry.py:94)，你应该标注：

- 入口：由 [`ReActDowntimeAgent.run()`](../app/react_agent.py:175) 通过 [`Tool.run()`](../app/tool_registry.py:31) 调用。
- 输入：停机记录和聚合维度。
- 输出：总时长、次数、占比、排序后的分组结果。
- 责任：把原始停机明细转成可以分析的指标。

这才叫真正啃代码。

---

## 17. 最小学习目标

你现在不要追求一次看懂所有细节。第一轮只需要达到下面 5 个目标：

1. 能从 [`main()`](../run.py:8) 讲到 [`TaskTreeOrchestrator.run()`](../app/orchestrator.py:95)。
2. 能说清 [`Commander.route()`](../app/orchestrator.py:50) 是怎么判断标准问题的。
3. 能说清 [`ReActDowntimeAgent.run()`](../app/react_agent.py:175) 的循环机制。
4. 能说清 [`RuleBasedPlanner.next_action()`](../app/react_agent.py:88) 为什么会按顺序调用工具。
5. 能说清 [`DifyClient.invoke()`](../app/dify_client.py:82) 是怎么把本地证据传给 Dify 的。

达到这 5 点，你就已经不是“只会看代码”，而是能讲清项目架构了。

---

## 18. 面试表达版本

如果面试官问“你这个 Agent 项目是怎么跑的”，你可以这样讲：

> 项目入口是 [`main()`](../run.py:8)。用户问题进入后，由 [`TaskTreeOrchestrator.run()`](../app/orchestrator.py:95) 统一编排。首先 [`Commander.route()`](../app/orchestrator.py:50) 基于任务树关键词和槽位判断是否命中产线停机分析任务；然后 [`ReActDowntimeAgent.run()`](../app/react_agent.py:175) 启动本地 ReAct 循环，由 [`RuleBasedPlanner.next_action()`](../app/react_agent.py:88) 根据 [`AgentMemory`](../app/react_agent.py:19) 当前缺失的数据和分析结果选择工具，并通过 [`ToolRegistry`](../app/tool_registry.py:40) 调用查询、聚合、Pareto、根因关联和图表生成工具。完成本地证据链后，系统通过 [`TaskTreeOrchestrator._invoke_specialist()`](../app/orchestrator.py:140) 把压缩后的证据包传给 Dify 的现状评估、原因拆解、结论输出三个子 Agent，最后由 [`ResultEvaluator.evaluate()`](../app/orchestrator.py:70) 对输出完整性和证据存在性做检查，并通过 [`save_orchestrator_result()`](../app/orchestrator.py:216) 保存结果。

这段话你不用背，但你要能理解每个名词对应哪段代码。

---

## 19. 最后记住：当前项目的核心不是 Dify，也不是 LangGraph

当前项目的核心是这套工程化拆法：

```text
业务问题
  -> 任务树
  -> Commander 路由
  -> Policy 约束
  -> Planner 决策
  -> Tool Calling 取数和计算
  -> Dify 子 Agent 表达和补充
  -> Evaluator 检查
  -> 可追踪输出
```

以后你学 LangGraph，也是在学怎么把这套结构用更标准的图编排框架表达出来。

所以你现在最应该啃的不是框架名，而是这套调度次序和职责边界。
