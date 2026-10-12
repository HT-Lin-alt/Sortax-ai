# Sortax 有限税务聊天前端实施计划

## 1. 目标

构建与参考截图视觉和交互接近的移动优先聊天页面，并接入 Sortax 后端规划中的 OpenAPI 0.3 契约。前端负责展示、输入、问卷交互、SSE 流消费、错误恢复和历史恢复；税务意图判断、问卷状态、支持范围、多主题检索、Document Checklist、citation 验证和税务总结均以后端为事实来源。

完整用户链路：

```text
创建会话
  → 助手流式问候
  → 用户自由输入
  → 后端路由
      ├─ 普通聊天 → 流式回复 → 等待下一条消息
      ├─ 不支持税务主题 → 展示有限服务说明
      └─ 有限税务服务
           → 三步问卷
           → 提交答案
           → Thinking / 检索状态
           → Document Checklist（逐文件解释和 citation）
           → 是否需要税务总结
                ├─ 否 → 结束本轮
                └─ 是 → 流式生成带引用的税务总结
```

## 2. MVP 范围

### 2.1 必须实现

- 开发身份初始化和 Bearer Token 使用
- 创建、加载和恢复会话
- 调用会话 start 接口并展示首次助手问候
- 普通文字消息输入和发送
- POST SSE 流式解析和增量渲染
- 普通聊天消息展示
- 税务三步问卷、单选/多选和进度展示
- 问卷逐题保存、页面刷新恢复和完成提交
- Thinking、检索开始、检索完成和失败状态
- 结构化 Document Checklist
- Checklist 每个文件的通俗解释、取得/保留方式、适用原因和 citation
- 税务总结确认
- 带引用的结构化税务总结
- 消息历史恢复
- 生成失败后的重新生成
- 取消活动生成和路由切换时中止本地流
- 移动端安全区、虚拟键盘和滚动处理
- 加载、空状态、断网、认证失效、并发冲突和证据不足错误状态

### 2.2 明确不实现

- 赞/踩反馈
- 文件附件上传
- 语音输入
- 回答朗读
- 回答复制
- 回答分享
- Workspace 实际功能
- 创建任务
- 多人实时协作
- 消息编辑和单条删除
- 后台知识库管理页面
- 自动报税、付款、入账或外部会计系统操作

参考截图中相应图标如为保持布局必须保留，应作为不可交互的装饰元素并从键盘焦点和无障碍树中排除；推荐直接移除，只保留“重新生成”。

## 3. 有限服务范围

前端只宣称支持 2025–26 税务年度的以下三个服务领域：

1. Employment income + work-related deductions
2. Residential rental property
3. Australian bank interest

对应后端内部类别：

```text
salary_wages
working_from_home
work_related_car
self_education
residential_rental_property
australian_bank_interest
```

以下主题不得显示为可用问卷选项：

- Overseas income
- Government payments
- Shares、managed funds、crypto 等一般投资收入
- Commercial property
- Business/sole trader income
- Donations 和其他未导入扣除类别

后端返回 `unsupported_tax_topic` 或 `unsupported_tax_year` 时，前端展示明确范围说明，不把请求自动改发普通聊天。

## 4. 技术栈

| 类别 | 选择 | 说明 |
| --- | --- | --- |
| UI 框架 | React 19 | 组件化聊天和结构化消息渲染 |
| 语言 | TypeScript strict | 对 OpenAPI、SSE 和状态机进行静态约束 |
| 构建工具 | Vite | SPA 开发和构建；开发代理到 FastAPI |
| 样式 | CSS Modules + CSS Variables | 精确还原截图，不引入大型组件库 |
| 图标 | Lucide React | 菜单、箭头、勾选、刷新等基础图标 |
| HTTP | 原生 Fetch | JSON API、认证和错误信封 |
| SSE | Fetch + ReadableStream | 当前流式端点为 POST 且需要 Bearer Token，不能使用原生 EventSource |
| 状态 | React Context + useReducer | 会话、生成和税务工作流状态规模有限 |
| 本地存储 | localStorage | 仅保存非敏感 UI 偏好、最近会话 ID；不保存问卷答案或税务总结正文 |
| 单元/组件测试 | Vitest + React Testing Library | reducer、SSE parser 和组件交互 |
| 端到端测试 | Playwright | 移动视口、流式事件、刷新恢复和截图回归 |

不引入 Redux、MobX、Next.js、SSR、WebSocket 或大型 UI 组件库。后续只有在状态复杂度或产品路由显著扩张时再评估。

## 5. 建议目录结构

```text
frontend/
├─ src/
│  ├─ api/
│  │  ├─ client.ts
│  │  ├─ errors.ts
│  │  ├─ sse-parser.ts
│  │  └─ generated-types.ts
│  ├─ app/
│  │  ├─ App.tsx
│  │  ├─ AppProvider.tsx
│  │  └─ app-reducer.ts
│  ├─ components/
│  │  ├─ ChatHeader/
│  │  ├─ MessageTimeline/
│  │  ├─ TextMessage/
│  │  ├─ ThinkingMessage/
│  │  ├─ RegenerateButton/
│  │  ├─ Composer/
│  │  └─ CitationList/
│  ├─ features/
│  │  ├─ auth/
│  │  ├─ conversations/
│  │  ├─ chat/
│  │  ├─ tax-intake/
│  │  ├─ document-checklist/
│  │  └─ tax-summary/
│  ├─ hooks/
│  │  ├─ useChatStream.ts
│  │  ├─ useConversation.ts
│  │  ├─ useTaxIntake.ts
│  │  └─ useAutoScroll.ts
│  ├─ styles/
│  │  ├─ tokens.css
│  │  ├─ globals.css
│  │  └─ responsive.css
│  ├─ test/
│  │  ├─ fixtures/
│  │  └─ render.tsx
│  └─ main.tsx
├─ e2e/
├─ index.html
├─ vite.config.ts
├─ tsconfig.json
└─ package.json
```

`generated-types.ts` 应从 `docs/openapi.yaml` 生成或严格对照生成；不得在不同 feature 中重复手写互相冲突的接口类型。

## 6. 页面布局与视觉规范

### 6.1 参考视口

- 主要参考尺寸：484 × 1024
- 同时验证：390 × 844、430 × 932、桌面窄窗
- 页面使用 `min-height: 100dvh`
- 聊天主体最大宽度约 484px，桌面端居中
- 使用 `env(safe-area-inset-top)` 和 `env(safe-area-inset-bottom)`
- 真实移动浏览器不自行绘制系统状态栏；桌面截图模式可使用开发专用 mock

### 6.2 视觉令牌

建议使用 CSS Variables 管理：

```text
--color-bg
--color-bg-accent
--color-surface
--color-surface-selected
--color-text-primary
--color-text-secondary
--color-brand
--color-success
--color-border
--radius-card
--radius-option
--shadow-card
--space-page-inline
--composer-height
```

目标特征：

- 白色到淡紫色的轻微背景渐变
- 深蓝灰正文和紫蓝品牌色
- 白色卡片、浅灰紫边框、约 20px 圆角
- 选中项使用淡紫背景和紫色圆形勾选
- 完成状态使用淡绿色圆形勾选
- 所有交互控件最小触控区域 44 × 44px
- 动画控制在 120–220ms，并遵守 `prefers-reduced-motion`

### 6.3 固定区域

- 顶部 header 保持菜单、新会话按钮和产品名称区域；Workspace 不提供实际功能
- 中部 MessageTimeline 独立滚动
- 底部只保留文字输入框和发送/停止按钮
- 建议问题 chips 可作为静态快捷输入，但不是必须的首批功能
- 键盘弹出时输入框不得被遮挡；发送新消息或收到 delta 时仅在用户已靠近底部时自动滚动

## 7. 前端状态模型

### 7.1 应用状态

```ts
type AppState = {
  auth: AuthState;
  conversation: ConversationState;
  stream: StreamState;
  taxIntake: TaxIntakeState;
  network: NetworkState;
};
```

前端状态只用于展示和未完成请求管理。会话、消息、问卷答案、工作流状态、checklist 和 summary 均以后端响应为事实来源。

### 7.2 生成状态

```text
idle
starting
classifying
questionnaire
retrieving
generating
completed
failed
cancelling
cancelled
```

事件映射：

| SSE 事件 | 前端行为 |
| --- | --- |
| `generation.started` | 保存 generation ID，进入 Thinking 状态 |
| `retrieval.started` | 展示正在查找相关 ATO 资料 |
| `retrieval.completed` | 展示正在组织 checklist |
| `message.delta` | 按 seq 追加文本；忽略重复 seq |
| `message.completed` | 按 content_type 渲染结构化组件并结束流 |
| `message.failed` | 清理临时消息，展示稳定错误和重新生成入口 |
| `heartbeat` | 更新连接存活时间，不创建可见消息 |

### 7.3 税务问卷状态

前端不得自行推进后端工作流，只根据 `TaxIntake.status` 显示：

```text
questionnaire_active
questionnaire_completed
retrieving_documents
checklist_ready
awaiting_summary_confirmation
summary_declined
generating_summary
summary_completed
cancelled
failed
```

答案提交成功后必须采用服务器返回的 `version`；后续请求使用新版本进行乐观并发控制。

## 8. 消息渲染

根据 `content_type` 使用穷尽匹配：

```text
text                 → TextMessage
questionnaire        → QuestionnaireMessage
document_checklist   → DocumentChecklistMessage
summary_confirmation → SummaryConfirmationMessage
tax_summary          → TaxSummaryMessage
```

遇到未知 `content_type`：

- 不崩溃；
- 显示“当前客户端版本无法展示此消息”；
- 保留纯文本 `content` 作为降级内容；
- 记录不包含消息正文的客户端诊断信息。

### 8.1 QuestionnaireMessage

- 展示三段进度条和当前题号
- 单选题使用原生 radio 语义
- 多选题使用原生 checkbox 语义
- 选项来自服务端 `questions`，不在前端复制业务映射
- 点击下一步前保存当前答案
- 网络失败时保留当前临时选择，明确提示重新提交
- 收到 `409 invalid_workflow_state` 时重新获取 intake 并恢复
- 完成后折叠为 Question List 摘要，不展示 Restricted 详细答案给旁观者；展开行为不在首批范围

固定模板预期：

1. 是否首次在澳大利亚报税：单选
2. 工作相关支出：居家办公、车辆、自我教育、None，多选
3. 收入：工资/PAYG、住宅租金、澳大利亚银行利息、None，多选

### 8.2 DocumentChecklistMessage

每个 `ChecklistItem` 必须展示：

- 文件名称
- 通俗解释
- 如何取得或保留
- 为什么适用于当前用户
- 至少一个 citation 标记

前端在渲染前执行防御性检查：

- `citation_ordinals` 非空
- 每个 ordinal 能在消息的 citations 中找到
- citation URL 使用 HTTPS
- citation 税务年度与 checklist 一致

若校验失败，不展示看似完整的 checklist；改为显示“此清单的来源信息不完整，请重新生成”。前端校验只用于防御，不能代替服务端验证。

### 8.3 SummaryConfirmationMessage

- 显示“是否需要税务总结”
- 仅提供明确的 Yes / No
- 点击后立即禁用两按钮，避免重复请求
- Yes 提交 `requested=true`
- No 提交 `requested=false`
- 自由文本中的 “yes” 不由前端自动转换为确认请求

### 8.4 TaxSummaryMessage

- 按 section 展示标题和通俗正文
- 每个来源支持的 section 展示 citation 标记
- 明确展示免责声明
- 不提供下载、分享或正式申报按钮

## 9. API 集成顺序

### 9.1 应用启动

开发环境：

1. 获取开发 JWT，或使用已有有效 Token
2. `GET /api/v1/auth/me`
3. 从 URL/本地最近会话确定 conversation ID
4. 无会话时 `POST /api/v1/conversations`
5. `GET /api/v1/conversations/{id}/messages`
6. 新会话且没有消息时调用 `POST /api/v1/conversations/{id}/start`

生产环境不允许调用开发 Token 端点；身份由外部登录系统提供。

### 9.2 普通消息

```text
POST /api/v1/conversations/{id}/messages
Authorization: Bearer ...
Content-Type: application/json

{
  "client_message_id": "uuid",
  "content": "user text"
}
```

该请求可能完成为普通文本、questionnaire、旧版 clarification、明确不支持错误或其他结构化消息。前端不能在发送前自行判定税务分支。

### 9.3 问卷

```text
GET /api/v1/tax-intakes/{tax_intake_id}
PUT /api/v1/tax-intakes/{tax_intake_id}/answers/{question_key}
POST /api/v1/tax-intakes/{tax_intake_id}/complete
```

`complete` 为 POST SSE。客户端生成并持久保留本次尝试的 `client_request_id`，直到收到完成或可确认的最终失败；网络重连不得生成新幂等键。

### 9.4 税务总结

```text
POST /api/v1/tax-intakes/{tax_intake_id}/summary
```

请求包含：

```json
{
  "client_request_id": "uuid",
  "requested": true,
  "version": 4
}
```

Yes/No 请求均消费后端返回的 SSE；No 分支不应出现长时间生成状态。

### 9.5 取消

- 保存 `generation.started.generation_id`
- 用户主动停止或离开当前会话时调用 `POST /api/v1/generations/{id}/cancel`
- 同时 abort 本地 fetch
- 路由切换时先发送取消，再释放组件状态
- 页面关闭属于 best effort；重新打开后以历史消息和后端状态为准

### 9.6 重新生成

消息操作区只实现重新生成：

```text
POST /api/v1/messages/{message_id}/retry
```

当前 retry 接口返回非流式 Generation：

1. 点击后禁用按钮并显示 Thinking
2. 等待请求完成
3. 重新 GET 会话消息
4. 以 `retry_of_message_id` 展示最新回复

结构化消息重试必须由后端保留对应 intake/checklist 上下文；在后端完成该能力前，前端只对后端明确允许重试的消息显示按钮。

## 10. SSE Parser 要求

必须支持：

- UTF-8 增量解码
- 网络 chunk 任意位置拆分
- 多行 `data:`
- `event:`、`id:`、空行终止
- 同一响应多个事件
- 重复事件 ID 和重复 delta seq 去重
- 未知事件忽略并记录类型，不中断已知事件
- AbortController
- 连接结束但没有 completed/failed 时视为异常中断
- `message.failed` 的 ErrorEnvelope 风格错误展示

不得假设一个 `ReadableStream` chunk 等于一个 SSE 事件。

## 11. 错误处理

| 错误 | UI 行为 |
| --- | --- |
| `unauthorized` | 清理失效 Token，进入重新认证状态 |
| `not_found` | 返回会话列表或创建新会话 |
| `conversation_busy` | 禁用发送，恢复活动生成状态后重试 |
| `idempotency_conflict` | 停止自动重试并提示刷新 |
| `invalid_workflow_state` | 重新 GET intake，以服务器状态恢复 |
| `intake_incomplete` | 定位到第一个未完成必答题 |
| `unsupported_tax_topic` | 展示有限支持范围，不自动改走普通聊天 |
| `unsupported_tax_year` | 说明当前只支持 2025–26 |
| `insufficient_evidence` | 说明资料不足，不展示无来源 checklist |
| `retrieval_unavailable` | 显示可重试状态，遵守 retry_after_seconds |
| `provider_timeout` / `provider_unavailable` | 展示重新生成按钮 |
| 断网 | 保留未发送输入；恢复网络后由用户明确重试 |

前端展示 `request_id` 作为问题反馈编号，但不得显示 Provider 原始异常、堆栈或敏感 details。

## 12. 安全和隐私

- 不在 localStorage、sessionStorage、URL、analytics 或普通 console log 中保存问卷答案、税务总结、JWT 或完整消息正文
- Token 首选内存或受控身份层；开发环境临时方案必须与生产实现隔离
- 外链 citation 使用 `target="_blank"` 时添加 `rel="noopener noreferrer"`
- 仅渲染纯文本；如未来支持 Markdown，必须使用严格 allowlist sanitizer
- 不通过 `dangerouslySetInnerHTML` 渲染模型内容
- 错误监控仅上传错误码、request ID、事件类型和非敏感 UI 状态
- 页面隐藏或切换会话时停止不必要的流和计时器
- 问卷答案展示应避免在折叠卡片中直接暴露详细税务选择

## 13. 无障碍

- 所有输入都有可见 label 或 `aria-label`
- 单选/多选使用原生语义，不用普通 div 模拟
- 进度条提供当前步骤和总步骤文本
- 新的流式 delta 不逐 token 触发屏幕阅读器；完成后使用克制的 live region 通知
- Thinking 状态使用 `aria-busy`
- 错误与题目关联使用 `aria-describedby`
- 键盘可完成整套问卷、发送、停止、确认总结和重新生成
- 焦点不会因每个 SSE delta 被重置
- 颜色不是选中、错误或完成状态的唯一提示

## 14. 测试策略

### 14.1 单元测试

- SSE 跨 chunk、UTF-8、多行 data、重复 seq、未知事件和异常结束
- app reducer 的所有合法状态迁移
- API ErrorEnvelope 归一化
- citation ordinal 解析和无效引用拒绝
- intake version 更新和 409 恢复
- client_message_id/client_request_id 在网络重试中保持不变

### 14.2 组件测试

- 单选题只能选择一个选项
- 多选题、None 互斥和必答校验
- 问卷进度及完成按钮
- Questionnaire、Checklist、Summary Confirmation、Tax Summary 渲染
- 每个 checklist item 的 citation 可访问
- unsupported、insufficient evidence 和 provider failure 状态
- 只有允许重试的助手消息显示重新生成

### 14.3 端到端测试

- 新会话 → 首次问候
- 普通聊天 → 流式回答
- 税务输入 → 三步问卷 → 刷新恢复
- 多选工资、居家办公、租赁和银行利息 → 组合 checklist
- 每个 checklist item 至少一个 citation
- Yes → 税务总结
- No → 不生成总结
- 不支持税务主题 → 范围说明
- 检索不可用 → 不显示无来源 checklist
- 重新生成 → Thinking → 历史刷新后显示新消息
- 流式过程中取消、切换会话和断网恢复
- 390×844、430×932、484×1024 截图回归

### 14.4 契约测试

- 前端生成类型与 `docs/openapi.yaml` 0.3.0 一致
- 每个后端 `content_type` 都有穷尽渲染分支
- 每个 SSE 事件 schema 都有 fixture
- 后端新增枚举值时，前端构建或契约测试明确失败

## 15. 实施顺序

### 阶段 F0：工程与契约（已完成，2026-10-11）

- [x] 创建 React + TypeScript + Vite 工程
- [x] 配置 strict TypeScript、ESLint、Vitest 和 Playwright
- [x] 配置 `/api` 开发代理
- [x] 从 OpenAPI 生成类型并建立契约 fixture
- [x] 建立 CSS tokens 和移动页面骨架

**出口条件：已满足。** 前端可以启动，health/auth 客户端已建立，生成类型与
OpenAPI 一致。`npm run check` 已通过类型生成检查、TypeScript、ESLint、6 个
Vitest 测试和生产构建；`npm run test:e2e` 已通过 1 个移动端 Playwright 测试。

**对应提交：** `7b6ba4b Complete frontend F0 foundation`

### 阶段 F1：静态视觉还原（已完成，2026-10-12）

- [x] 实现 header、背景、时间线和底部 composer
- [x] 实现文字消息、Thinking、Questionnaire 和 Question List 外观
- [x] 实现 Checklist、citation 和 Tax Summary 视觉组件
- [x] 完成三个移动视口截图回归基线

**出口条件：已满足。** OpenAPI typed fixtures 可以展示文字消息、问卷、已完成问题
列表、Thinking、Document Checklist、summary confirmation 和 Tax Summary。390×844、
430×932、484×1024 三个视口已建立 Playwright 截图基线且回归通过；`npm run check`
已通过 OpenAPI 类型检查、严格 TypeScript、ESLint、10 个 Vitest 测试和生产构建，
`npm run test:e2e` 已通过 4 个 Playwright 测试。

**对应提交：** `12c1e73 Complete frontend F1 visual foundation`

### 阶段 F2：聊天与 SSE（已完成，2026-10-12）

- [x] 实现认证和会话 API client
- [x] 实现 start、历史加载和普通消息发送
- [x] 实现 SSE parser、消息增量、失败和取消
- [x] 实现自动滚动、重连后的历史恢复和并发发送保护

**出口条件：已满足。** 开发身份 Token 只保存在内存；客户端可以创建或恢复会话、
为新会话流式生成一次问候、加载服务端消息历史并发送普通消息。POST SSE parser 支持
UTF-8 跨 chunk、多行 data、未知事件、事件 ID/seq 去重、异常结束和 Abort；流结束或
中断后重新读取服务端历史。`npm run check` 已通过 OpenAPI 类型检查、严格 TypeScript、
ESLint、16 个 Vitest 测试和生产构建，`npm run test:e2e` 已通过 5 个 Playwright 测试，
其中包含首次问候和普通流式聊天端到端场景。

**对应提交：** `b9beca9 Complete frontend F2 chat streaming`

### 阶段 F3：税务问卷（已完成并通过后端联调，2026-10-12）

- [x] 按 `QuestionnaireContent` 渲染服务器问题
- [x] 实现逐题 PUT、version 更新、加载和冲突恢复
- [x] 实现 complete SSE 和检索 Thinking 状态
- [x] 页面刷新后从 GET intake 恢复

**出口条件：已满足。** 三步问卷可以在 OpenAPI typed
fixtures 下逐题保存，使用最新 version，收到 409 后重新 GET intake，刷新页面后恢复，
并通过 complete SSE 触发多 claim type 检索和 Checklist。`npm run check` 已通过 OpenAPI
类型检查、严格 TypeScript、ESLint、22 个 Vitest 测试和生产构建；`npm run test:e2e`
已通过 6 个 Playwright 测试，其中 F3/F4 场景覆盖 409、刷新恢复、三步保存、组合检索、
总结确认、税务总结和结构化历史恢复。后端运行时 schema 已与 OpenAPI 对齐为 `status`、
answers 数组、version，以及 `selected_options + version` 的逐题保存和 complete 请求。

**对应提交：** `84734b2 Implement frontend F3 tax questionnaire`

### 阶段 F4：Checklist 与总结（已完成，2026-10-12）

1. [x] 实现逐项 checklist 和 citation 防御性校验
2. [x] 实现总结 Yes/No
3. [x] 实现结构化税务总结和免责声明
4. [x] 实现结构化消息历史恢复

**出口条件：已满足并通过后端联调。** Checklist 和总结均在渲染前校验 citation ordinal、HTTPS URL
和 2025–26 税务年度；校验失败时 fail closed。Yes/No 均通过带幂等键的 summary SSE 请求，No
分支不会触发总结生成；历史恢复沿用会话消息重新加载，并支持结构化消息渲染。后端集成测试
覆盖 Checklist/Summary SSE、引用快照、幂等重放、No 分支不调用 LLM、取消恢复和重试。

### 阶段 F5：重新生成与质量收敛（进行中，2026-10-12）

1. [x] 接入允许范围内的 retry
2. [x] 实现失败态和历史刷新
3. 完成无障碍、键盘和移动安全区检查
4. [x] 完成移动端性能预算检查
5. [x] 完成 Playwright E2E 和截图回归

**当前状态：** 9 个 Playwright E2E 和三个移动视口截图回归通过；覆盖普通聊天、三步问卷、
409/刷新恢复、Checklist、Summary Yes/No、retry 历史刷新和移动性能预算。390×844 本地生产构建
实测 DOMContentLoaded 41ms、FCP 112ms、JS 261,563B、CSS 16,873B、283 个 DOM 节点且无横向溢出。
剩余出口项为完整无障碍、键盘和移动安全区专项验收。

## 16. 后端依赖和开发阻塞

前端真实集成依赖以下后端阶段完成：

- OpenAPI 0.3 规划接口落地
- `/conversations/{id}/start`
- 结构化 `Message.content_type` 和 `structured_content`
- `tax_intake_sessions` 及四个 intake 接口
- TaxIntake 运行时 schema 与 OpenAPI 对齐：`status`、answers 数组、version，以及
  `selected_options + version` 的逐题保存和 complete 请求
- 六类知识来源完成 manifest 和 Milvus 导入
- 多主题检索和逐项 citation
- 总结确认和税务总结
- 结构化消息历史恢复和 retry 语义
- CORS，或由同域反向代理/Vite proxy 解决

在后端未完成前，前端可使用严格符合 OpenAPI 的 MSW/Playwright fixtures 开发视觉和交互，但 fixture 不得被当作真实税务能力验收。

## 17. MVP 验收清单

- [x] 页面在 390、430、484 宽度下无横向溢出
- [x] 新会话只生成一次助手问候
- [x] 普通文字聊天可流式展示并恢复历史
- [x] 税务问题由后端返回三步问卷
- [x] 问卷单选、多选、进度、保存和刷新恢复正确
- [x] 不支持类别不显示为可用选项
- [x] 完成问卷后显示检索/Thinking 状态
- [x] Document Checklist 每个文件都有通俗解释和至少一个有效 citation
- [x] citation 可打开 ATO HTTPS 来源
- [x] 用户明确选择 Yes 后才生成税务总结
- [x] 选择 No 不调用 LLM 生成总结
- [x] 税务总结显示来源和免责声明
- [x] 证据不足或检索不可用时不显示无来源 checklist
- [ ] 重新生成可用，其他消息操作未实现
- [ ] 切换会话或停止生成会取消本地流并通知后端
- [x] JWT、问卷答案和税务正文未进入 localStorage、URL 或普通日志
- [ ] 键盘和屏幕阅读器可完成核心链路
- [ ] OpenAPI 契约、组件测试、E2E 和截图回归通过

## 18. 完成定义

前端 MVP 完成必须同时满足：

1. 参考截图中的欢迎、问卷、完成和 Thinking 状态得到高保真实现；
2. 普通聊天和有限税务服务严格由后端路由；
3. 问卷状态和答案以后端为事实来源；
4. Checklist 不存在无 citation 的文件条目；
5. 税务总结只有显式确认后生成；
6. 不支持的税务范围不会通过普通聊天绕过；
7. 页面刷新、网络重试和重新生成不会产生重复消息或重复模型费用；
8. 排除功能没有伪装成可用按钮；
9. 移动端、无障碍、安全和契约测试达到验收要求。
