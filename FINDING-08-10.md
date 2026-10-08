# 代码审查发现（2026-10-08）

## 审查范围

- 对照 `BACKEND_PLAN.md` 独立检查现有实现，不采信其中的完成标记。
- 比较基准：`cb00cb22ffdce6a437aa35b23277bad732257b66`。
- 范围包括 staged、unstaged 和相关 untracked 文件。
- 本文件仅持久化审查结果，尚未修改对应实现。

## 发现

### [P1] OpenAI 非成功终止事件被误判为完成

- 状态：待修复
- 位置：`src/sortax/llm_gateway/openai.py:87`
- 关联计划：`BACKEND_PLAN.md:778`

适配器只处理 `response.completed`，忽略 `response.incomplete` 和
`response.failed`。如果模型先输出部分 delta，随后因为达到 Token 上限等原因产生
`response.incomplete`，迭代会正常结束，`ChatCoordinator` 将把不完整内容持久化为
`completed`。

建议将非成功终止事件转换为标准 Provider 错误，并要求收到
`response.completed` 后才能正常完成。

### [P2] 规划和检索期间不会发送 heartbeat

- 状态：待修复
- 位置：`src/sortax/chat/service.py:378`
- 关联计划：`BACKEND_PLAN.md:569`

意图规划和 Milvus 检索通过 `_await_cancellable` 整体等待，heartbeat 循环直到 LLM
开始生成时才启动。Embedding 或 Milvus 请求超过 15 秒时，SSE 连接会一直沉默，可能被
代理或网关作为空闲连接断开。

建议让规划和检索阶段也使用能够定期产生 heartbeat 的等待机制，使 heartbeat 覆盖完整
流式请求生命周期。

### [P2] 检索期间断开连接会遗留 pending retrieval run

- 状态：待修复
- 位置：`src/sortax/chat/service.py:518`
- 关联计划：`BACKEND_PLAN.md:941`

如果客户端在 `_start_retrieval()` 之后、`_complete_retrieval()` 之前断开，检索任务会被
取消，但 `asyncio.CancelledError` 分支只将消息和 generation 标记为取消。对应的
retrieval run 会一直保持 `pending`，且没有 `finished_at`。

建议在该分支调用 `_finish_retrieval(..., status="cancelled")`，与显式取消路径保持一致。

## 待补测试

- OpenAI `response.incomplete` 和 `response.failed` 的错误归一化与状态收敛。
- 意图规划或检索期间持续发送 heartbeat。
- 检索期间客户端断开后，retrieval run 收敛为 `cancelled` 并写入 `finished_at`。

## 总体判断

意图分流、持久化迁移、Provider 选择和共享取消设计基本一致，但上述生命周期问题意味着
阶段 5C 暂不应视为完全验收。

审查子代理受执行权限限制，未运行测试套件；这些结论来自完整 diff、调用路径和现有测试的
静态审查。
