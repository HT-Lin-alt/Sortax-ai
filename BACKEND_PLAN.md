# 智慧会计平台——聊天页面后端项目计划

## 1. 项目目标

为智慧会计平台构建**仅服务于聊天页面**的可运行 Demo 后端，支持用户创建会话、由助手发起问候、发送消息、接收大模型流式回复、查看历史记录、停止生成、重试，以及对会话进行重命名和归档。后端先把用户输入路由到普通聊天或有限支持的税务服务；税务分支通过结构化问卷收集情况，按答案检索人工导入的 ATO 官方资料，返回逐项带来源的 Document Checklist，并在用户明确确认后生成带引用的通俗税务总结。

首期以后端可运行 Demo 为标准，保留必要的用户隔离、权限校验、敏感信息保护、基础用量记录和日志，但不追求生产级高可用、复杂审计或容量治理。系统只提供会计问答与信息辅助，不执行记账、报税、付款或修改总账等具有财务后果的操作。

### 1.1 首期范围（MVP）

- 用户身份解析与租户隔离
- 会话的创建、查询、重命名、归档
- 消息发送、历史分页、流式回复
- 会话首次助手问候及幂等恢复
- 普通聊天与有限支持税务服务的意图路由
- 2025–26 税务年度的结构化税务问卷、答案持久化和断点恢复
- Employment income + work-related deductions、Residential rental property、Australian bank interest 三个有限服务领域
- 根据多选问卷答案执行多主题 ATO 检索、合并、去重和失败关闭
- 返回结构化 Document Checklist；每个待准备文件必须带至少一个实际 ATO citation 和通俗解释
- 用户明确确认后生成个性化税务总结，并复用已持久化的问卷、checklist 和引用快照
- 停止生成、失败重试、幂等提交
- LLM 提供商抽象、提示词组装、上下文裁剪
- 基础内容安全、敏感字段脱敏与会计免责声明
- 用量、错误和关键操作审计
- 基于 Milvus 的 ATO 官方资料 RAG，为不同退税/扣除申报类型检索所需证明文件并返回来源引用
- 健康检查、指标、日志、追踪
- 单元测试、集成测试、API 契约测试与最小部署配置

### 1.2 暂不纳入首期

- 聊天页面前端
- 自动生成或提交正式会计凭证
- 自动报税、付款、资金划转、总账写入
- 语音、视频、多人实时协作
- 海外收入、政府补助、商业地产、个体经营、一般投资/证券/加密资产、捐赠等未导入知识范围
- 自动计算应纳税额、自动判断申报资格或保证退税结果
- 赞踩反馈、消息复制/朗读/分享、Workspace、创建任务等非核心交互的后端能力
- 通用企业知识库、用户自助知识库管理后台和非 ATO 数据源
- 模型训练、微调和模型托管
- 账务系统双向同步

> ATO RAG 只读取项目负责人手工选择并导入的 ATO 官方公开资料。后续若要接入自动同步、用户附件、企业知识库、会计工具或生产账务系统，再单独进行生产级设计。

## 2. 关键假设与设计决策

1. 当前尚无登录与统一身份系统；MVP 使用开发环境 JWT，聊天后端只负责签发开发令牌和验证 JWT，不保存密码。开发令牌签发端点必须在预发布及生产环境禁用。
2. 会话、消息、生成、检索追踪、用量等**租户业务数据**都带 `tenant_id`，Demo 至少在应用层强制租户与用户条件；PostgreSQL RLS 保留为后续加固项。ATO 公共知识目录是平台级数据，不带 `tenant_id`，只由本地导入 CLI 修改。
3. 客户端到服务端的流式响应采用 **Server-Sent Events（SSE）**。聊天输出是单向流，SSE 比 WebSocket 更容易穿越网关、断线续传和观测。
4. 后端采用**模块化单体**起步，避免在业务量尚未明确时过早拆分微服务；耗时任务由独立 Worker 执行。
5. 消息正文以 PostgreSQL 为唯一事实来源；Redis 只保存短期状态、限流计数和取消信号，不作为永久存储。
6. LLM 通过统一接口接入，业务层不依赖任何单一模型厂商。
7. 金额使用定点小数或最小货币单位，时间统一以 UTC 存储，API 使用 ISO 8601，展示时再转换为用户时区。
8. 税务问卷属于 Restricted 数据；答案必须按租户和用户隔离，不写入日志、指标、Milvus 或错误响应。
9. “yes/no”等短回复必须结合持久化工作流状态解释，不能仅依赖 LLM 或最近文本猜测其含义。
10. 当前有限服务版本固定支持 2025–26；其他年度在有对应 manifest 来源前返回 `unsupported_tax_year`，不得跨年度复用材料。

### 2.1 已确认决策：身份与权限

- 身份系统：当前没有登录或外部身份提供商。
- MVP 认证方式：开发环境 JWT。
- 角色：仅 `user`，暂不实现管理员和审计员角色。
- 数据可见性：普通用户只能访问自己创建的会话和消息，不能查看同租户其他用户的聊天。
- JWT 最小 claims：
  - `sub`：用户唯一 ID。
  - `tenant_id`：租户唯一 ID。
  - `role`：固定为 `user`。
  - `iss`、`aud`、`iat`、`exp`、`jti`：用于签发方、受众、有效期和令牌追踪校验。
- 授权条件：请求中的可信身份必须来自已验证的 JWT；访问会话或消息时必须同时满足 `tenant_id` 和 `owner_user_id` 匹配。
- 越权响应：对不存在、跨租户或属于同租户其他用户的资源统一返回 `404`，避免暴露资源是否存在。
- 开发安全边界：开发 JWT 使用独立的本地密钥和短有效期，不得提交真实密钥，不得在预发布或生产环境开放任意身份的令牌签发能力。
- 已确认的开发 JWT 参数：
  - 仅在 `development` 和 `test` 环境挂载 `POST /api/v1/dev/token`。
  - 使用 HS256 和至少 32 字符的环境变量密钥。
  - 令牌有效期为 1 小时。
  - `user_id` 与 `tenant_id` 使用 UUID，由开发调用方在签发请求中指定。
  - MVP 不建立用户表；可信身份完全来自已验证的 JWT。

### 2.2 身份与权限开发状态

- [x] FastAPI 应用工厂与环境配置模型。
- [x] 开发 JWT 签发端点，生产和预发布环境不挂载该路由。
- [x] JWT 签名、签发方、受众、有效期、必需 claims 与固定角色校验。
- [x] Bearer 认证依赖与可信 `IdentityContext`。
- [x] 当前身份查询端点 `GET /api/v1/auth/me`。
- [x] 同时校验租户与所有者的资源授权函数，越权统一映射为 `404`。
- [x] 令牌与资源授权测试代码。
- [x] 在项目 Python 3.12 虚拟环境执行验证；截至 2026-10-02，完整套件 pytest 23 项通过，Ruff 格式与静态检查、mypy 严格检查均通过。

### 2.3 已确认决策：模型、数据区域与数据保留

#### Provider 策略

- MVP 实现统一 `LLMProvider` 接口，并提供三个实现：
  - `FakeProvider`：确定性、本地运行、无外部网络调用，供自动化测试和本地开发使用。
  - `OpenAIProvider`：基于 OpenAI 官方 Python SDK 的真实模型适配器，具体默认模型名称在编码前通过配置确定，不硬编码到业务层。
  - `QwenProvider`：通过 OpenAI-compatible API 接入 Qwen，主回答模型与轻量意图分类模型分别配置，但复用同一 Base URL 和 API Key。
- Provider 由环境变量选择；测试环境必须默认使用 `FakeProvider`，不得因配置缺失自动调用真实模型。
- `FakeProvider`、`OpenAIProvider` 与 `QwenProvider` 必须输出相同的领域事件和错误类型，使聊天编排层不依赖具体厂商。
- 模型失败时不得静默切换 Provider 或拼接另一个模型的输出；意图分类允许显式降级到版本化的确定性规则分类器，但必须记录降级来源，规则也无法安全判定时由聊天编排层返回明确、可重试的业务错误。
- 本地开发的默认 Provider 为 `FakeProvider`。选择 `OpenAIProvider` 或 `QwenProvider` 时必须显式设置模型环境变量；不在源代码中设置会随时间过期的真实模型名称。

#### 部署与数据区域

- 当前部署形态：仅本地开发。
- 开发阶段暂无数据区域限制。
- 生产部署区域、模型推理区域以及是否允许跨境处理均未确定，必须在生产启用真实 Provider 前重新评审。
- 本地开发和自动化测试禁止使用真实客户数据，只允许模拟数据或已经完成不可逆脱敏的数据。

#### 外部 AI Provider 数据使用要求

- 业务要求：发送给 LLM 或 Embedding Provider 的输入不得用于模型训练。
- 该要求不能仅由应用适配器保证。生产启用前必须根据各 Provider 当时的官方文档、账户类型、合同和数据控制设置完成核验并留存审批记录；未完成核验时不得发送真实或可识别数据。
- OpenAI API Key 只能通过环境变量或生产 Secret Manager 注入，不得出现在源代码、配置样例值、日志、追踪、测试快照或错误响应中。
- 开发环境没有 API Key 时，应用应继续支持 `FakeProvider`；只有显式选择 `OpenAIProvider` 时才要求 API Key，配置缺失必须启动失败或拒绝调用，不能回退到不安全默认值。

#### 脱敏日志

- 允许记录**脱敏后的**提示词和模型回答，用于本地调试与问题排查；禁止记录原始提示词、原始回答或完整上下文。
- 日志写入前必须经过统一脱敏器，至少处理身份证件号、税号、银行账号、邮箱、电话号码、API Key、JWT 和已定义的客户标识符。
- 脱敏失败时采取失败关闭：只记录请求 ID、租户 ID、用户 ID、模型、Token 用量、延迟、内容长度和内容哈希等元数据，不记录正文。
- 脱敏后的正文仍按敏感数据管理，采用结构化字段、长度上限、访问控制和独立保留策略；生产日志保留期在上线前确定。
- 日志中记录脱敏版本并不替代 PostgreSQL 中的正式聊天记录，也不得作为恢复聊天内容的数据源。

#### 聊天与审计数据保留

- 聊天记录默认保留 180 天；到期后物理删除会话及其消息正文。
- 用户主动删除会话时执行物理删除，不设置软删除恢复窗口；若存在活动生成任务，必须先取消并完成状态收敛，再在事务中删除会话及关联消息。
- 删除操作本身保留最少必要的审计事件，但审计事件不得复制已删除的提示词或回答正文。
- 审计记录保留期限暂不固定，生产上线前依据适用法规、客户合同和组织政策确定。
- 若未来发现法定留存义务与用户删除要求冲突，必须先调整产品规则和删除实现并完成合规评审，不能静默改变已确认的删除语义。

### 2.4 阶段 0 基线与 RAG 变更状态

- [x] 身份与权限契约已确认，并有可运行的开发 JWT 基础实现。
- [x] Provider、开发数据、区域、日志和保留策略已确认。
- [x] 变更前的聊天 API、SSE、错误信封及非功能目标已确认。
- [x] 变更前的 OpenAPI 3.1 草案已持久化到 `docs/openapi.yaml`。
- [x] 变更前的数据分类、环境约束、数据流、脱敏和删除规则已持久化到 `docs/data-classification.md`。
- [x] 变更前 OpenAPI YAML 可解析，9 个路径、13 个操作、68 个内部引用均通过完整性检查，`operationId` 无重复；检查已纳入 pytest 契约测试。
- [x] 原阶段 0 曾明确排除 RAG；2026-10-02 需求变更后，将限定范围的 ATO RAG 纳入 MVP，但仍排除用户附件、通用企业知识库、历史消息编辑、单条消息删除和任何会计写操作。
- [x] **阶段 0R 已完成：** 首批 `claim_type`/税务年度、本地文件格式、引用结构和检索错误已经确认，可进入 Demo 实现。
- [x] `docs/openapi.yaml`、`docs/data-classification.md` 和 ATO 来源 manifest 已更新；阶段 0R 基础契约与完整测试均通过。
- [x] **阶段 1R 已完成：** Milvus/RAG 模块、配置和 Compose 已补齐；截至 2026-10-08，Docker 已可通过 WSL 使用，Milvus 3.0.2、MinIO 和 etcd 容器健康，Compose 配置、`localhost:19530` 连接及应用 `pymilvus` adapter 均已真实验证。

### 2.5 需求变更：ATO 官方资料 RAG（有限服务 Demo 范围）

#### 目标与边界

- RAG 用于回答有限支持税务领域中“需要准备哪些证明文件、记录或材料”，并支撑后续税务总结中的事实性陈述。
- ATO 文件由项目负责人手工下载并放入本地导入目录；软件**不负责联网抓取、定时同步或监测 ATO 页面变化**。
- Demo 只导入人工选择的 ATO 官方 HTML、PDF、TXT 或 Markdown 文件，不接收聊天用户上传文件，也不导入真实客户税务资料。
- 每个本地文件必须在 manifest 中由项目负责人填写 ATO 原始 URL、标题、`claim_type`、适用税务年度和访问日期；导入器校验字段完整性、URL 主机为允许的 ATO 官方域名、文件存在、类型和大小，但不联网验证页面，也不代替人工判断内容真实性。
- 用户问题、检索查询和聊天正文不写入 Milvus；Milvus 只保存公共 ATO 文档 chunk、向量和引用元数据。
- RAG 只提供带来源的信息辅助，不能判定用户一定符合申报资格，也不能替代注册税务代理或 ATO 正式意见。

#### Demo 导入流程

```text
手工下载 ATO 文件
  → 放入 data/ato/raw/（默认加入 .gitignore，避免大型原始文件进入仓库）
  → 在 manifests/ato/sources.yaml 填写元数据
  → 运行一次性导入 CLI
  → 解析与分块
  → 生成 Embedding
  → 写入 Milvus
  → 运行示例查询检查结果
```

- 导入命令采用可重复执行的 CLI，例如 `python -m sortax.knowledge.ingest --manifest manifests/ato/sources.yaml`。
- Demo 使用单个 Milvus collection；重新导入时按 `document_id + content_hash` 跳过未变化文件，`--rebuild` 可清空并重建 Demo collection。
- 不实现 staging collection、alias 原子切换、审批工作流、自动撤回、定时任务、对象存储或复杂版本发布系统。
- 使用独立 `EmbeddingProvider` 接口和确定性 `FakeEmbeddingProvider`；真实 Provider 通过环境变量显式配置。
- 检索采用“`claim_type`/税务年度过滤 + 稠密向量相似度”的最小方案；问卷允许多选时，为每个已选 `claim_type` 分别执行现有单主题检索，再合并、去重和验证引用闭包。混合检索、稀疏召回和重排留作效果不足时的后续优化。

#### 回答与引用

- 无法确定 `claim_type` 或税务年度时先向用户澄清，不猜测具体材料清单。
- Document Checklist 的**每一个文件条目**都必须关联至少一个实际命中的 ATO 来源；引用包含 ordinal、标题、原始 URL、文档 ID、内容哈希、chunk ID、税务年度和 manifest 访问日期。
- Checklist 条目必须包含文件名称、为什么需要、如何取得/保留、基于哪一项问卷答案适用，以及 `citation_ordinals`。任一条目缺少引用时不得完成该消息。
- 税务总结复用已持久化的问卷答案、checklist 和 citation 快照；不得在生成总结时以当前 Milvus 重新检索后静默改变历史依据。
- 检索无结果、分数低于阈值或 Milvus/Embedding 不可用时，明确表示证据不足或返回可重试错误；不得让 LLM 凭记忆补齐文件清单。
- 消息保存引用快照，因此重新打开聊天时不需要重新查询 Milvus。

#### 现有契约影响

- 阶段 0R 已将 RAG 所需的消息 `citations`、检索错误、SSE 检索事件，以及本地 ATO 文件/Embedding/Milvus 数据流同步到 `docs/openapi.yaml` 和 `docs/data-classification.md`。
- 两层意图、普通聊天和 `completion_kind=general_chat` 属于阶段 5B 新增契约；现已同步更新 `docs/openapi.yaml` 并通过契约测试。
- Compose 只需增加可供本地 Demo 使用的 Milvus 及其必要依赖；不设计生产部署拓扑。

#### 阶段 0R 已确认

1. 有限服务 Demo 使用 `salary_wages`、`working_from_home`、`work_related_car`、`self_education`、`residential_rental_property`、`australian_bank_interest` 六个内部 `claim_type`，覆盖 2025–26 税务年度。
2. 本地输入同时支持 HTML 与 PDF；示例 manifest 覆盖两种格式。
3. Fake 与真实 Embedding Provider 均保留，自动化测试和本地契约工作默认使用确定性 Fake，真实 Provider 必须显式配置。
4. 新增的 `salary-wages-income-statement.pdf`、`rental-property-records.html`、`bank-accounts-and-income-bonds.pdf` 只有在补齐 ATO 原始 URL、标题、类别、年度和访问日期并进入 manifest、完成导入后才算受支持来源；文件仅存在于 `data/ato` 不代表在线检索已支持。

### 2.6 有限税务服务聊天工作流

后端必须持久化并执行以下状态机，前端只负责渲染服务端返回的结构化内容：

```text
awaiting_user_input
  → general_chat → awaiting_user_input
  → questionnaire_active
      → questionnaire_completed
      → retrieving_documents
      → checklist_ready
      → awaiting_summary_confirmation
          → summary_declined → awaiting_user_input
          → generating_summary → summary_completed → awaiting_user_input
```

- 创建会话后，客户端显式调用幂等的 start 端点；服务端创建内部 system trigger、调用 LLM 并持久化首次助手问候。不得因页面刷新重复生成或收费。
- 用户自由文本先路由为 `general_chat`、`tax_assistance` 或 `unsupported_tax_topic`。普通聊天直接流式回答；有限税务服务创建或恢复 `tax_intake_session`；明确超出范围的税务问题返回稳定的范围说明，不退回普通聊天生成无来源税务建议。
- 问卷版本 `limited-tax-2025-26-v1` 固定三步：首次报税情况、工作相关支出多选、收入类型多选。工作支出只支持居家办公、车辆、自我教育；收入只支持工资/PAYG、住宅租金、澳大利亚银行利息。
- 每道答案按 `question_key` 幂等覆盖；只有必答题全部完成后才能进入检索。页面刷新或重新登录后可通过 intake 查询端点恢复当前步骤和答案。
- 多选答案映射为零个或多个受支持 `claim_type`。若没有选择任何受支持主题，返回说明性结束消息，不创建 retrieval run。
- Checklist 完成后返回 `summary_confirmation` 结构化内容。只有用户明确提交 `requested=true` 才生成税务总结；`requested=false` 持久化拒绝状态并返回结束消息。
- 税务总结使用通俗语言区分“用户已回答的事实”“ATO 来源支持的材料要求”和“仍需会计师确认的事项”，不得计算最终税额、承诺退税或提交申报。

## 3. 技术栈

| 层级 | 选型 | 用途与理由 |
| --- | --- | --- |
| 语言 | Python 3.12 | AI/LLM 生态成熟，适合快速构建异步 API |
| Web 框架 | FastAPI + Uvicorn | 异步接口、OpenAPI、依赖注入与流式响应支持良好 |
| 数据校验 | Pydantic v2 | 请求、响应、配置及领域 DTO 校验 |
| ORM / 迁移 | SQLAlchemy 2.x Async + Alembic | 异步数据访问与可追踪的数据库迁移 |
| 主数据库 | PostgreSQL 16 | 会话、消息、引用、基础审计和用量等持久数据；支持事务 |
| 缓存/协调 | Redis 7 | 限流、取消信号、短期流状态、分布式锁 |
| 异步任务 | Celery + Redis | 标题摘要和保留清理；ATO Demo 导入由手工执行的 CLI 完成 |
| 流式协议 | HTTP SSE | Token 增量、完成、错误、心跳和断线恢复事件 |
| LLM 集成 | 统一 Provider 接口 + Fake Provider + OpenAI 官方 Python SDK | Fake 用于确定性开发测试；OpenAI 适配器屏蔽流式、错误码和用量差异 |
| RAG 向量库 | Milvus + 官方 Python SDK | 保存 ATO 文档 chunk、向量和过滤元数据，支持 Demo 语义检索 |
| Embedding | 统一 Embedding Provider + Fake Embedding | 模型可配置、可版本化；测试不调用外部服务 |
| 文档解析 | HTML/PDF 解析器（实现时锁定库版本） | 提取 ATO 页面正文、标题、列表、表格和来源元数据 |
| 鉴权 | 开发 JWT；预留 OAuth 2.0 / OIDC 适配 | MVP 本地签发和验证；生产前替换为外部身份系统与 JWKS 验签 |
| 可观测性 | 健康检查 + 结构化 JSON 日志 | 记录请求 ID、延迟和错误；OpenTelemetry/Prometheus 留作生产化扩展 |
| 测试 | pytest + pytest-asyncio + HTTPX | 单元、API 和必要的 Docker 依赖集成测试 |
| 质量工具 | Ruff + mypy + pre-commit | 格式、静态检查与类型检查 |
| 容器化 | Docker + Docker Compose | 启动本地 API、PostgreSQL、Redis、Worker 和 Milvus Demo 环境 |
| CI | GitHub Actions 或现有 CI 平台 | 检查、测试、镜像构建、迁移校验与安全扫描 |

版本在首次搭建时锁定到经过兼容性验证的具体小版本，并通过依赖更新机器人与回归测试升级。

## 4. 后端模块

### 4.1 API 与传输层 `api`

- REST 路由、SSE 流式端点、请求/响应模型
- 统一错误结构、请求 ID、API 版本 `/api/v1`
- CORS、正文大小、超时和连接生命周期配置
- 不包含业务规则，只负责协议转换与调用应用服务

### 4.2 身份与权限 `identity`

- 开发 JWT 签发与验证、用户及租户上下文解析
- MVP 仅支持 `user` 角色；保留后续 RBAC 扩展点，但不提前实现管理员和审计员权限
- 会话与消息资源级授权
- 禁止客户端自行指定可信的 `tenant_id` 或 `user_id`
- ATO 公共语料读取不按租户复制，但所有在线检索必须由已认证用户发起并关联其租户/用户追踪上下文
- MVP 不增加管理员/审核员 API 角色；ATO 文件由开发者在聊天系统之外手工选择，再通过本地 CLI 导入

### 4.3 会话管理 `conversations`

- 创建、列表、详情、重命名、归档会话
- 列表游标分页和排序
- 会话所有权、状态、用户主动物理删除与 180 天到期清理策略
- 异步生成默认标题
- 幂等 start 用例：为新会话创建内部 system trigger 和首次助手问候；同一 `client_request_id` 只生成一次

### 4.4 消息管理 `messages`

- 用户/助手/系统消息模型
- 消息创建、历史游标分页、重试关系和回复关系
- 客户端幂等键 `client_message_id`
- 消息状态：`pending`、`streaming`、`completed`、`failed`、`cancelled`
- 内容版本、级联物理删除和保留期限
- 持久化消息与 `retrieval_run`、引用快照的关系，使历史回答不依赖当前 Milvus 索引仍可展示当时引用
- 增加 `content_type`：`text`、`questionnaire`、`document_checklist`、`summary_confirmation`、`tax_summary`
- 增加可空 `structured_content`；只保存经过服务端 schema 校验的 JSON，不保存任意模型输出 JSON
- `completion_kind` 扩展为 `questionnaire`、`document_checklist`、`summary_confirmation`、`tax_summary`，历史查询与幂等重放必须保留原值

### 4.5 聊天编排 `chat`

- 一次聊天请求的事务边界与状态机
- 固定工作流：持久化触发消息 → 基础安全检查与查询最小化 → 意图处理 → 按普通聊天/有限税务工作流/明确不支持税务主题分支 → 调用问卷、检索或 LLM → 完成或失败收敛
- 第一层输出 `general_chat`、`tax_assistance` 或 `unsupported_tax_topic`；是否出现税务年度不得作为是否进入税务工作流的直接判断条件
- 税务工作流优先读取 `tax_intake_session.workflow_status`；短回复按当前状态解释，不能把总结确认的 “yes” 当作普通聊天
- 普通聊天直接调用 LLM，不创建 retrieval run，最终消息标记 `completion_kind=general_chat`、`grounded=false`、`citations=[]`
- 将经过验证的 ATO chunk 与引用作为独立证据区传给提示词层，不把来源文本提升为系统指令
- 非 ATO 文件要求类问题可走普通聊天链路；一旦判定为 ATO 文件要求类问题，检索不可用或证据不足时必须失败关闭或澄清
- 旧版直接文件问题仍可复用最近已完成历史补齐类别/年度；新版问卷和总结确认必须使用独立、持久化的 intake 状态，不依赖历史文本推断
- 将 Token 批量落库，避免每个 Token 写一次数据库
- 生成完成、失败、取消和断线后的状态收敛
- 同一会话并发策略：MVP 默认每个会话只允许一个活动生成任务

### 4.6 模型网关 `llm_gateway`

- 标准接口：`generate()`、`stream()`、`count_tokens()`
- 提供确定性的 `FakeProvider` 和基于官方 SDK 的 `OpenAIProvider`
- Provider 通过配置显式选择，测试环境默认 Fake，禁止隐式调用真实模型
- 厂商配置、模型选择、超时、有限重试和错误归一化
- Token 数、延迟、模型名和费用估算采集
- 禁止在日志中输出 API Key、原始提示词和原始回复；只允许记录经过统一脱敏和截断的正文

### 4.7 提示词与上下文 `prompting`

- 系统提示词模板和版本管理
- 会计助手边界：信息辅助、来源提示、不代替专业判断
- 上下文窗口预算、历史裁剪、长会话摘要接口
- 防止用户内容被错误拼接为系统指令
- 接收 RAG 输出的领域对象 `GroundingContext`，而不是 Milvus 原始结果；将证据文本、引用标识和不确定性规则放入独立且有边界的上下文区
- 要求模型仅依据提供证据生成文件要求，引用只能使用允许的 citation ID；生成后由编排层校验引用闭包
- 分离首次问候、普通聊天、checklist 通俗解释和税务总结四套提示词及版本；问卷题目、选项、状态迁移和支持范围不由 LLM 自由生成
- Checklist 与税务总结优先使用结构化输出 schema；服务端只接受检索候选中存在的 citation ordinal

### 4.8 安全与合规 `safety`

- 输入/输出长度限制、恶意内容与提示注入基础检测
- 银行账号、税号、身份证号等敏感信息脱敏策略
- 高风险请求拦截或要求人工确认：报税提交、付款、凭证入账等
- 180 天聊天保留期、用户物理删除请求与不含正文副本的删除审计
- API Key 只从环境变量读取；生产密钥管理和基础设施加密留作后续设计
- 在生成 Embedding 查询前执行数据最小化与脱敏，避免把不必要的个人税务信息发送给外部 Provider
- 将 ATO 文本视为不可信输入，执行来源白名单、内容净化、RAG Prompt Injection 防护和输出引用校验
- 问卷答案按 Restricted 数据处理；禁止记录原始答案、收入选择组合或税务总结正文到普通日志、追踪、指标和错误详情
- 对 `unsupported_tax_topic`、`unsupported_tax_year` 明确说明有限服务边界，禁止退化到无检索的税务建议

### 4.9 限流与配额 `quota`

- 限制单条消息长度和同一会话并发生成数
- 使用 Redis 实现简单的用户请求频率限制
- 记录 LLM 与 Embedding 基础用量；Demo 不实现月度预算、计费或复杂配额体系

### 4.10 审计与用量 `audit`

- 记录操作者、租户、动作、资源、模型、用量和结果
- 审计记录与应用日志分离，默认不保存完整聊天正文副本
- 费用估算、追踪 ID、模型响应 ID和提示词版本关联
- 记录 `retrieval_run_id`、collection/Embedding/检索配置、被引用的文档 ID 和失败原因，但不复制用户查询或 chunk 正文
- 记录导入批次、Embedding 模型、collection 名称和引用文档 ID，便于复现实验结果

### 4.11 数据访问与基础设施 `infrastructure`

- SQLAlchemy Repository、Unit of Work、Redis 客户端
- 配置加载、密钥引用、时钟和 ID 生成器
- 数据库连接池、超时、重试和迁移
- Milvus、本地文件系统与消息队列适配器
- 实现 `ConversationRepository`、`MessageRepository`、`TaxIntakeRepository`、`RetrievalRunRepository`、`KnowledgeCatalogRepository` 和 `VectorStore` 等应用端口；领域/应用模块不得导入具体 SDK

### 4.12 后台任务 `workers`

- 会话标题/摘要生成
- 中断任务状态修复、用量对账、超过 180 天聊天记录的物理清理
- 维护任务具备基础幂等和有限重试
- ATO 导入不经过 Worker；开发者按需执行 CLI，并在导入完成后查看汇总与失败文件列表

### 4.13 可观测性与运维 `observability`

- `/health/live`、`/health/ready`
- 使用请求 ID 关联 API 与 Provider 日志，不要求部署分布式追踪平台
- Demo 指标：LLM/Embedding/Milvus 调用成功率、检索延迟、引用数量和 Token 用量
- `/health/ready` 检查 PostgreSQL、Redis 和 Milvus 连通性；不构建多级 degraded/告警体系

### 4.14 ATO 本地知识导入 `knowledge`

- `knowledge/catalog` 读取人工维护的来源 manifest、`claim_type` 和税务年度元数据
- `knowledge/ingestion` 从本地目录读取 HTML/PDF/TXT/Markdown，执行正文抽取、分块、内容哈希和嵌入
- 采用简单的标题/段落加长度分块，chunk 保留来源 URL、标题层级、页码/章节和内容哈希
- 提供 `ingest`、`--dry-run` 和 `--rebuild` CLI；显示成功、跳过和失败数量
- 不提供抓取器、公开知识库管理 API、审批工作流或自动同步
- 有限服务 manifest 必须覆盖工资/PAYG、住宅租赁记录、澳大利亚银行利息及现有三类工作相关扣除；新增本地文件未进入 manifest 或未完成导入时不得宣称在线支持

### 4.15 Embedding 网关 `embedding_gateway`

- 标准接口：`embed_documents()`、`embed_query()`、批量大小和维度检查
- 提供确定性 `FakeEmbeddingProvider` 与可配置的真实 Provider
- 记录 provider、模型、维度和版本；模型变化必须重建新索引，禁止在同一索引混用不同维度/模型
- 对超时、配额、非法向量、批次部分失败进行统一错误归一化

### 4.16 RAG 检索 `rag`

- 接收旧版直接文件请求或已完成的税务问卷，将答案确定性映射为一个或多个 `claim_type` 和税务年度
- `Retriever.plan()` 接收当前查询和最近历史；当前消息优先，缺失字段才从最近相关用户消息补齐
- Milvus 元数据过滤、稠密向量 Top-K、去重、相关度阈值和上下文预算控制
- 仅返回当前 Demo collection 中与类别/年度匹配的 ATO chunk；生成可验证的引用对象
- 多选问卷对每个类别分别执行过滤检索，再按 `document_id + content_hash + chunk_id` 合并去重；不同类别的证据不可互相替代
- 输出 `ChecklistGroundingContext`，保留每个 checklist item 到 citation ordinal 的映射；不得只在消息级别附一个与具体文件无关的引用列表
- 对低相关度、无结果和索引不可用执行失败关闭，不允许 LLM 凭记忆补全文件清单
- 输出检索追踪信息：collection 名称、chunk ID、相关度、来源 URL 和检索耗时
- 对外只返回稳定的 `GroundingContext`、`CitationCandidate` 或 `ClarificationRequired`，不泄漏 Milvus 原始 schema

### 4.17 意图与工作流路由 `intent`

MVP 以链路跑通为目标，不引入置信度模型或复杂冲突处理。税务问卷和总结确认使用持久化工作流状态；无法识别但明显属于税务且超出有限范围的问题不得进入普通聊天生成事实性税务建议。

#### 第一层：任务意图

- 新增统一 `IntentClassifier` 接口，输入当前用户内容与最近已完成历史，输出稳定的 `IntentDecision`
- `IntentDecision.intent` 允许 `general_chat`、`tax_assistance`、`ato_document_requirements`（兼容旧直接文件请求）和 `unsupported_tax_topic`
- 开发与测试环境提供使用中英文确定性词表的 `FakeIntentClassifier`；ATO 文件要求通过费用/扣除类别与“材料、文件、记录、凭证”及对应英文表达识别
- 简短补充消息可结合上一轮 ATO 澄清历史继续判定为 `ato_document_requirements`，例如“汽车费用需要哪些记录？”之后回答“2025-26”
- 第一层不解析向量结果，也不因缺少税务年度把普通聊天误判为澄清
- 真实 Qwen 环境新增 `LLMIntentClassifier`：使用独立的轻量模型配置和非流式结构化输出，只允许返回上述稳定枚举及有限诊断元数据；不得让模型自由生成工作流动作、问卷答案或 `claim_type`
- 主回答模型和分类模型分别由 `SORTAX_LLM_MODEL`、`SORTAX_CLASSIFIER_MODEL` 选择；Qwen 场景复用 `SORTAX_QWEN_BASE_URL` 与 `SORTAX_QWEN_API_KEY`，不要求为分类模型申请第二把 Key
- 分类请求使用低输出上限、确定性采样和独立短超时；不携带 RAG chunk、完整问卷答案或无关长历史，只发送完成分类所需的当前消息、有限最近历史和当前工作流状态
- 分类响应必须先通过 `IntentDecision` schema、枚举白名单和版本校验；超时、Provider 错误或非法输出时调用版本化的 `FakeIntentClassifier` 规则作为 fallback，并在决定中标记 `classifier_source=rules_fallback` 与降级原因
- fallback 按“活动工作流状态 → 明确文件要求词 → 明确有限/不支持税务词 → 明确普通聊天”的保守顺序判断；模糊或未命中的税务输入不得默认归为 `general_chat`，规则也无法安全判断时返回可重试分类错误或范围澄清
- `FakeIntentClassifier` 同时作为普通 CI、离线开发、编排测试和真实分类器故障时的确定性 fallback；真实分类器仅在显式配置后启用，响应与日志必须区分 `llm` 和 `rules_fallback`，不得将关键词结果伪装成真实模型结果

#### 第二层：ATO 字段解析

- 仅在第一层输出 `ato_document_requirements` 后调用 `Retriever.plan()`
- 先解析当前消息，再从最近相关用户历史补齐 `claim_type` 或税务年度；当前消息中的明确值覆盖历史值
- 支持六个稳定类别代码及明确的 `YYYY-YY`、`YYYY/YYYY` 年度格式；有限服务工作流只接受 2025–26
- 字段仍不完整时返回 `ClarificationRequired`；字段完整时输出 `RetrievalPlan` 并进入现有检索链路

#### 代码与框架产出

| 位置/框架 | 计划修改 |
| --- | --- |
| `src/sortax/intent/` | 新增 `IntentDecision`、`IntentClassifier` 和 `FakeIntentClassifier` |
| `src/sortax/intent/` | 增加基于统一模型网关的 `LLMIntentClassifier`、版本化分类提示词及严格结构化响应解析 |
| `chat/service.py` | 注入分类器并增加普通聊天、ATO 澄清、ATO RAG 三条分支 |
| `rag/retriever.py` | `plan()` 增加最近历史参数并实现字段补全 |
| `prompting/builder.py` | 新增 `build_general_chat_request()` |
| `prompting/models.py` | `completion_kind` 增加 `general_chat` |
| `chat/events.py` | SSE 完成事件支持 `general_chat` |
| `chat/models.py` | 消息响应和 Chat session 使用持久化的 `completion_kind` |
| `messages/models.py` | `Message` 领域模型增加可空 `completion_kind` |
| `llm_gateway/fake.py` | 增加确定性的普通聊天输出 |
| `main.py` | 在应用工厂中注入 IntentClassifier，development/test 默认 Fake |
| `config.py`、`.env.example`、`compose.yaml` | 增加分类器实现、模型、超时和输出上限配置；Qwen 分类器复用已有 Base URL/API Key |
| `infrastructure/persistence/models.py`、`repositories.py` | `messages` 映射、写入并读取可空 `completion_kind` |
| `migrations/`（Alembic） | 增加 `messages.completion_kind` 迁移，保证历史与幂等重放不靠 citations 猜测类型 |
| FastAPI/SSE | API 路径和请求体不变，只扩展完成事件枚举 |
| `tests/intent/`、`tests/chat/`、pytest | 增加两层路由、多轮补全、普通聊天和重放测试 |
| `docs/openapi.yaml` | 扩展 `completion_kind` 枚举及普通聊天完成事件契约 |

### 4.18 税务问卷与工作流 `tax_intake`

- 维护版本化问卷模板、问题顺序、必答规则、选项白名单和选项到 `claim_type` 的确定性映射
- 持久化 `workflow_status`、当前步骤、答案、模板版本、税务年度和总结确认结果
- 对 `question_key` 使用幂等覆盖语义；拒绝未知题目、未知选项、重复互斥选项和跨会话/跨用户访问
- 负责 `questionnaire_active → questionnaire_completed → checklist_ready → awaiting_summary_confirmation → summary_completed` 状态迁移
- 不把原始问卷答案写入 Milvus、Redis 永久存储、普通日志或模型提示之外的外部系统

### 4.19 Checklist 与税务总结 `tax_guidance`

- 将多主题检索结果转换为结构化 `DocumentChecklist`，每个条目包含名称、通俗解释、取得/保留方式、适用原因和 citation ordinals
- 在持久化消息前验证逐项 citation 闭包；任何条目无来源、来源年度不符或来源不属于该主题时失败关闭
- Checklist 完成后创建 `SummaryConfirmation`；仅在显式确认后构造 `TaxSummary`
- 税务总结区分已知事实、来源支持的文件要求和待专业复核事项，并复用 checklist citation 快照
- 不计算最终税额、不判定最终资格、不生成可直接提交的正式申报，也不调用外部报税工具

本阶段不新增第三方依赖，不改变现有 Unit of Work、JWT、Redis、Milvus 或消息发送 API 的总体框架。

## 5. 模块依赖

依赖方向必须从外层指向应用/领域接口，基础设施实现接口，避免领域层反向依赖 FastAPI、SQLAlchemy 或具体模型 SDK。

```text
api
 ├─> identity
 ├─> conversations
 └─> chat application service
       ├─> messages
       ├─> intent classifier port
       ├─> tax_intake application service
       ├─> tax_guidance application service
       ├─> prompting  <── GroundingContext
       ├─> safety
       ├─> quota
       ├─> rag application port
       ├─> llm_gateway port
       └─> audit port

rag
 ├─> embedding_gateway port
 ├─> KnowledgeCatalogReadPort（只读已导入元数据）
 └─> VectorStore port

tax_intake
 ├─> TaxIntakeRepository port
 ├─> versioned questionnaire template
 └─> deterministic answer-to-claim-type mapping

tax_guidance
 ├─> tax_intake
 ├─> rag application port
 ├─> prompting / llm_gateway ports
 └─> messages / citations

knowledge
 ├─ catalog ─> KnowledgeCatalogRepository / LocalDocumentStore ports
 └─ ingestion
      ├─> LocalDocumentReader / Parser / Chunker ports
      ├─> embedding_gateway port
      └─> VectorStore port

conversations/messages/audit/quota/chat
 └─> 各自定义的 Repository / UnitOfWork / Cache ports

infrastructure（端口实现）
 ├─> PostgreSQL / Redis
 ├─> Milvus SDK
 ├─> 本地文件系统
 ├─> 具体 Embedding Provider SDK
 ├─> 具体 LLM Provider SDK
 └─> Celery Broker

workers
 └─> conversations / messages / audit 维护用例

observability 横切 api、workers、数据库、Redis、Milvus、embedding_gateway 和 llm_gateway
```

在线回答先经过 `api → chat → intent`，随后分流为 `prompting → llm_gateway → messages` 的普通聊天，或 `tax_intake → tax_guidance → rag → embedding_gateway/知识目录/VectorStore → prompting → llm_gateway → messages/citations` 的有限税务工作流；离线导入路径为 `手工 CLI → knowledge/ingestion → 本地文件 → embedding_gateway → Milvus collection`。在线请求不得触发文件解析、文档嵌入或 collection 重建。

### 5.1 关键依赖约束

- `api` 不得直接访问数据库或模型 SDK。
- `chat` 只依赖 `llm_gateway` 接口，不依赖具体厂商实现。
- `chat` 只依赖 `IntentClassifier` 接口；意图关键词和分类规则不得散落在 API 路由或数据库 Repository 中。
- `chat` 只依赖 `rag` 应用接口，不得直接查询 Milvus。
- `prompting` 不得依赖 VectorStore schema 或自行搜索；ATO grounded answer 必须接收经过 `rag` 验证和预算裁剪的 `GroundingContext`，普通聊天和澄清请求可以不携带 `GroundingContext`。
- `rag` 不得把类别或税务年度不匹配的 chunk 返回给聊天编排层。
- `knowledge` 负责本地文件导入；`rag` 只读 Demo collection，不能在用户请求路径触发文件导入或重建索引。
- `messages` 保存最终引用快照；`retrieval_runs` 保存检索执行元数据。二者不能依赖 Milvus 当前仍保留旧 collection 才能展示历史结果。
- `embedding_gateway` 与 `llm_gateway` 分离，二者可以使用不同 Provider、模型和配额。
- `identity` 生成可信请求上下文，其他模块不得使用请求正文中的身份字段。
- `messages` 负责消息事实与状态；`chat` 负责工作流，不能各自维护一套状态。
- `tax_intake` 是问卷答案与税务工作流状态的唯一事实来源；`chat` 不得通过扫描历史自然语言重建问卷状态。
- `tax_guidance` 只能消费 `tax_intake` 产生的受支持类别和 `rag` 验证后的证据；不得自行扩大服务范围或构造 citation。
- 问卷选项到 `claim_type` 的映射属于版本化业务配置，不得由 LLM 决定，也不得散落在前端组件中。
- Demo 的关键审计元数据与业务事务同库写入，不引入独立事件投递系统。
- `observability` 只能采集必要元数据，不能绕过脱敏策略记录消息正文。
- 具体 PostgreSQL、Redis、Milvus、文件解析、Embedding 和 LLM SDK 仅允许出现在 `infrastructure` 或网关适配实现中。

## 6. 建议数据模型

### `conversations`

- `id`（UUID/UUIDv7）、`tenant_id`、`owner_user_id`
- `title`、`status`（active/archived）
- `last_message_at`、`created_at`、`updated_at`、`expires_at`
- 索引：`(tenant_id, owner_user_id, last_message_at DESC, id)`

### `messages`

- `id`、`tenant_id`、`conversation_id`、`author_user_id`
- `role`、`content`、`status`、`content_type`
- `content_type` 使用 `text`、`questionnaire`、`document_checklist`、`summary_confirmation`、`tax_summary`
- `structured_content`（可空 JSONB；必须通过与 `content_type` 对应的服务端 schema 校验）
- `completion_kind`（可空；助手完成消息使用 `answer`、`clarification`、`general_chat`、`questionnaire`、`document_checklist`、`summary_confirmation` 或 `tax_summary`）
- `client_message_id`、`parent_message_id`、`retry_of_message_id`
- `model_provider`、`model_name`、`prompt_version`
- `input_tokens`、`output_tokens`、`error_code`
- `retrieval_run_id`（可空）、`grounded`、`citation_count`
- `created_at`、`completed_at`
- 唯一约束：`(tenant_id, author_user_id, client_message_id)`
- 索引：`(tenant_id, conversation_id, created_at, id)`

### `generation_runs`

- `id`、`tenant_id`、`conversation_id`
- `trigger_message_id`、`assistant_message_id`；trigger 可以是用户消息或首次问候使用的内部 system 消息
- `retrieval_run_id`（可空）
- `status`、`started_at`、`first_token_at`、`finished_at`
- `provider_request_id`、`cancel_requested_at`、`failure_reason`

### `retrieval_runs`

- `id`、`tenant_id`、`owner_user_id`、`conversation_id`、`user_message_id`、`assistant_message_id`
- `status`、`intent`、`claim_type`（兼容单主题）、`claim_types`（JSON 数组，用于问卷多选）、`tax_year`、`query_hash`；不额外保存未经脱敏的查询正文
- `embedding_provider`、`embedding_model`、`retrieval_config_version`、`collection_name`
- `top_k`、`score_threshold`、`candidate_count`、`selected_count`、`started_at`、`finished_at`、`failure_reason`
- 同一幂等消息重放复用已有 run；显式重试创建新 run，并记录当时解析到的索引版本

### `message_citations`

- `id`、`tenant_id`、`message_id`、`retrieval_run_id`、`ordinal`
- `document_id`、`content_hash`、`chunk_ids`
- `title_snapshot`、`url_snapshot`、`section_snapshot`、`tax_years_snapshot`、`source_accessed_at`
- 引用是回答生成时的不可变展示快照；文档后续更新或索引回滚不改写历史回答
- 唯一约束：`(tenant_id, message_id, ordinal)`；随会话物理删除级联删除

### `tax_intake_sessions`

- `id`、`tenant_id`、`owner_user_id`、`conversation_id`
- `template_version`、`tax_year`、`workflow_status`、`current_step`
- `answers`（JSONB；只允许模板声明的 `question_key` 和 option code）
- `summary_requested`（可空布尔）、`created_at`、`updated_at`、`completed_at`
- 同一会话最多一个非终态 intake；唯一/部分唯一约束防止并发创建两个活动问卷
- 删除会话时级联物理删除；不得在审计事件或日志中复制原始答案

### `message_checklist_items`

- `id`、`tenant_id`、`message_id`、`ordinal`
- `document_name`、`plain_language_explanation`、`how_to_obtain`、`applies_because`
- `citation_ordinals`（非空数组，仅能引用同一消息的 `message_citations.ordinal`）
- 唯一约束：`(tenant_id, message_id, ordinal)`；服务端提交事务前验证每一项引用闭包

### `usage_records`

- `id`、`tenant_id`（离线平台任务可空）、`user_id`（可空）
- `usage_type`（llm/embedding）、`generation_run_id`、`retrieval_run_id`、`import_run_id`（按类型关联）
- `provider`、`model_name`、`input_units`、`output_units`、`estimated_cost`
- `occurred_at`

### `audit_events`

- 审计事件记录主体、动作、资源、结果、时间、追踪 ID 和最少必要元数据

### `knowledge_documents`

- `id`、`source_url`、`title`、`local_path`、`content_type`
- `claim_types`、`tax_years`、`accessed_at`
- `content_hash`、`parser_version`、`embedding_model`、`imported_at`

### `claim_types`

- 稳定代码、显示名称和少量同义词，可先由配置文件维护；Demo 不构建分类管理后台

### `knowledge_import_runs`

- `id`、`manifest_hash`、`collection_name`、`status`、`started_at`、`finished_at`
- `documents_seen`、`documents_imported`、`documents_skipped`、`documents_failed`、`error_summary`

### Milvus collection `ato_knowledge_demo`

- 主键：`chunk_id`
- 向量：`dense_vector`
- 内容：`text`、`title`、`section_path`、`page_number`
- 来源：`document_id`、`source_url`、`content_hash`、`accessed_at`
- 过滤：`claim_types`、`tax_years`、`language`、`jurisdiction`

所有租户业务表必须包含 `tenant_id`，Repository 查询必须强制租户条件；RLS 可在 Demo 后再加入。ATO 公共知识表不带 `tenant_id`，只能由本地导入 CLI 写入。Milvus 中不得存储用户身份、聊天正文、问卷答案或租户私有数据。删除会话时同时物理删除其 `tax_intake_sessions`、`generation_runs`、`retrieval_runs`、`message_checklist_items`、`message_citations` 和正文；公共 ATO 文档与索引不因单个用户删除而删除。

## 7. 首期 API 契约

机器可读契约以 `docs/openapi.yaml` 为阶段 0 基线；本节用于解释关键语义。后续接口实现必须进行契约测试，若修改契约需同步更新两处。

通用约定：

- API 前缀为 `/api/v1`，健康检查除外。
- 使用 Bearer JWT 认证；资源 ID 使用 UUID，时间使用 UTC ISO 8601。
- 普通请求和响应使用 JSON；历史列表使用游标分页，默认 30 条、最大 100 条。
- 发送消息时以请求体中的 `client_message_id` 作为幂等键；首次问候、完成问卷和生成总结使用 `client_request_id` 作为各自幂等键。
- 同一会话最多允许一个活动生成任务；冲突时返回 `409 conversation_busy`。

| 方法与路径 | 功能 | 主要说明 |
| --- | --- | --- |
| `POST /api/v1/conversations` | 创建会话 | 可选初始标题 |
| `POST /api/v1/conversations/{id}/start` | 生成首次助手问候 | SSE；幂等创建内部 system trigger 和助手消息 |
| `GET /api/v1/conversations` | 会话列表 | 游标分页、状态筛选 |
| `GET /api/v1/conversations/{id}` | 会话详情 | 校验租户和资源权限 |
| `PATCH /api/v1/conversations/{id}` | 重命名/归档 | 使用版本号或 ETag 防止覆盖 |
| `DELETE /api/v1/conversations/{id}` | 物理删除会话 | 幂等返回 `204`；先取消活动生成，再删除会话和关联消息 |
| `GET /api/v1/conversations/{id}/messages` | 消息历史 | 游标分页，稳定排序；助手消息返回持久化的引用快照 |
| `POST /api/v1/conversations/{id}/messages` | 发送消息并流式回复 | `text/event-stream`，要求幂等键 |
| `GET /api/v1/tax-intakes/{id}` | 恢复问卷 | 返回模板版本、问题、已选答案、当前步骤和状态 |
| `PUT /api/v1/tax-intakes/{id}/answers/{question_key}` | 保存问卷答案 | 幂等覆盖；仅接受模板声明的 option code |
| `POST /api/v1/tax-intakes/{id}/complete` | 完成问卷并生成 checklist | SSE；校验必答题、执行多主题检索并返回逐项引用 |
| `POST /api/v1/tax-intakes/{id}/summary` | 接受/拒绝税务总结 | SSE；仅 `requested=true` 时生成总结，false 返回结束消息 |
| `POST /api/v1/generations/{id}/cancel` | 停止生成 | 幂等；已完成时返回当前最终状态 |
| `POST /api/v1/messages/{id}/retry` | 重试失败/已有回复 | 创建新 generation run，不覆盖旧消息 |
| `GET /health/live` | 存活检查 | 不检查外部依赖 |
| `GET /health/ready` | 就绪检查 | 检查数据库、Redis、必要配置和 Milvus 连通性 |

MVP 不提供编辑历史消息或单独删除一条消息的端点。用户可通过重新发送或重试创建新消息；删除操作以整个会话为边界。问卷答案是结构化 intake 状态，不属于历史消息编辑；完成问卷后答案不可通过通用消息端点修改。

会话删除采用防枚举语义：成功、重复删除、资源不存在或无权访问均返回 `204 No Content`。服务端仍需在内部区分结果并记录最少必要的安全审计元数据。

### 7.1 SSE 事件

- `generation.started`：生成 ID、助手消息 ID。
- `retrieval.started`：检索 run ID、解析出的类别数组/税务年度；不得包含原始查询、原始问卷答案或个人税务信息。
- `retrieval.completed`：检索状态、索引/配置版本、候选与入选数量；引用正文留到最终事件返回。
- `message.delta`：从 1 开始严格递增的 `seq` 与文本片段。
- `message.completed`：最终状态、`content_type`、`structured_content`、`completion_kind` 和持久化引用快照；支持 `general_chat`、`clarification`、`questionnaire`、`document_checklist`、`summary_confirmation`、`tax_summary` 和兼容旧链路的 `answer`
- `message.failed`：稳定错误码、是否可重试，不泄露供应商内部信息
- `heartbeat`：每 15 秒发送，用于长时间无 Token 时保持连接

每个事件包含 `id`。客户端重连可发送 `Last-Event-ID`；服务端至少能返回已持久化的当前文本和最终状态。MVP 不承诺无限期逐 Token 回放。

- SSE 建立前的错误使用普通 JSON 错误响应；建立后的错误使用 `message.failed` 事件。
- 客户端断开连接时请求取消模型生成，也可通过取消端点显式停止。
- 在检索阶段取消时，同时传播到 Embedding/Milvus 调用；不得继续启动 LLM。已经结束的外部调用仍需记录用量与最终取消状态。
- 取消后保留已经生成的部分回答，并将消息/生成任务标记为 `cancelled`，不得伪装成完整回答。
- 单次 SSE 生成最长 5 分钟；超时后发送失败事件并收敛持久化状态。
- ATO RAG 回答的 `message.completed` 必须包含带 `ordinal` 的 `citations` 数组；每项至少包含 `title`、`url`、`document_id`、`content_hash`、`chunk_ids`、适用税务年度和访问时间。
- `document_checklist` 的 `structured_content.items[*].citation_ordinals` 必须非空且只能引用同一完成事件中的 citation ordinal；服务端验证失败时发送 `message.failed`，不得返回部分无来源 checklist。
- `questionnaire` 完成事件必须包含 `tax_intake_id`、模板版本、税务年度、问题定义、当前步骤和已选答案；不得把原始答案复制到日志或检索事件。
- `tax_summary` 只能在 intake 状态为 `awaiting_summary_confirmation` 且请求明确 `requested=true` 时生成，并复用 checklist 已持久化的 citation 快照。
- 如果在首个回答 Token 前检索失败，返回普通 JSON 错误；流建立后检索/引用校验失败则发送 `message.failed`，不得退化成无来源的 ATO 文件清单。
- 需要补充 `claim_type` 或税务年度时，返回正常完成的助手澄清消息并标记 `completion_kind=clarification`，而不是伪装成系统错误；该消息不要求 ATO 文件清单引用。
- 普通聊天不创建 retrieval run，返回 `completion_kind=general_chat`、`grounded=false` 和空 `citations`。
- 网络重放同一 `client_message_id` 必须复用原消息、检索 run 和最终事件；用户显式 retry 则创建新 generation/retrieval run，使用当前 Demo collection，但不覆盖原回答及其引用。

### 7.2 错误响应

所有非 SSE 错误统一使用以下信封，后续身份模块现有的 `detail` 格式也必须迁移到该结构：

```json
{
  "error": {
    "code": "conversation_busy",
    "message": "This conversation already has an active generation.",
    "request_id": "00000000-0000-0000-0000-000000000000",
    "retryable": true,
    "retry_after_seconds": 3,
    "details": {}
  }
}
```

| HTTP 状态 | 稳定业务错误码 | 说明 |
| --- | --- | --- |
| `400` | `invalid_request` | 语义无效或不支持的请求 |
| `401` | `unauthorized` | 缺少或无效身份凭证 |
| `404` | `not_found` | 资源不存在或不可访问 |
| `409` | `conversation_busy` | 会话已有活动生成任务 |
| `409` | `idempotency_conflict` | 相同幂等键对应不同请求内容 |
| `413` | `message_too_large` | 消息超过大小限制 |
| `422` | `validation_error` | 字段或格式校验失败 |
| `429` | `rate_limited` | 请求频率过高 |
| `429` | `quota_exceeded` | 用户或租户配额耗尽 |
| `502` | `provider_error` | Provider 返回不可归一化的失败 |
| `503` | `provider_unavailable` | Provider 或必要依赖暂时不可用 |
| `504` | `provider_timeout` | Provider 首 Token 或完整响应超时 |
| `500` | `internal_error` | 未预期的服务端错误；不返回内部异常细节 |
| `503` | `retrieval_unavailable` | Milvus、Embedding 或 Demo collection 不可用 |
| `422` | `insufficient_evidence` | 当前已导入 ATO 资料不足以支持具体文件清单 |
| `409` | `invalid_workflow_state` | 当前 intake 状态不允许执行该操作 |
| `422` | `intake_incomplete` | 必答问卷未完成或答案不满足模板规则 |
| `422` | `unsupported_tax_topic` | 税务问题明确超出有限服务范围 |
| `422` | `unsupported_tax_year` | 请求年度没有对应的已审核知识来源 |

- `request_id` 必须同时出现在响应和结构化日志中。
- `retryable` 只能在服务端确认安全重试时设为 `true`；存在 `retry_after_seconds` 时客户端不得提前重试。
- 客户端错误不得包含堆栈、API Key、原始 Provider 错误、数据库细节或未脱敏内容。
- SSE 建立后的 `message.failed` 复用相同的 `code`、`message`、`request_id` 和 `retryable` 字段。

## 8. 模块搭建顺序与里程碑

以“本地可运行、可演示、引用可追溯”为目标，不实现生产级采集、发布、灾备和容量体系。

### 阶段 0R：Demo 契约确认（0.5–1 天，重新打开）

1. [x] 确认文件由项目负责人手工下载，软件不联网抓取。
2. [x] 确认首批 `claim_type`、2025–26 税务年度、HTML/PDF 文件格式和 Fake/真实 Embedding Provider 边界。
3. [x] 更新 OpenAPI 的 citations、retrieval SSE 事件和检索错误。
4. [x] 更新数据分类文档，说明本地 ATO 文件、查询 Embedding 和 Milvus 数据边界。
5. [x] 创建 `manifests/ato/sources.yaml` 示例和 8 个演示问题。

**出口条件：** 示例 manifest、API 引用结构和 Demo 数据流清晰可执行。

### 阶段 1R：本地 Milvus 与模块骨架（1–2 天）

1. [x] 保留现有 FastAPI、JWT、错误信封、日志、Celery 和 CI 骨架。
2. [x] 创建 `knowledge`、`rag`、`embedding_gateway` 和 Milvus adapter。
3. [x] 为 Milvus、Embedding 和本地 ATO 目录增加配置。
4. [x] Docker Compose 已扩展并通过结构契约测试；2026-10-08 已在 WSL/Docker 中验证 Milvus 3.0.2、MinIO 和 etcd 健康，并通过 `localhost:19530` 完成真实连接检查。
5. [x] 更新依赖锁、`.env.example` 和 README 启动说明。

**出口条件：** API 能连接本地 Milvus；测试可使用 Fake Embedding。

2026-10-08 已确认项目 Python 3.12 `.venv` 可用，准备了被 Git 忽略的本地 `.env`，并通过
应用 `pymilvus` adapter 完成 collection 创建、文档查询和向量检索。

### 阶段 2：聊天与 RAG 持久化（2–3 天）

1. [x] 完成会话、消息、generation run、retrieval run 和 citation 表、Alembic 迁移及 Repository。
2. [x] Repository 查询在应用层强制 `tenant_id + owner_user_id` 授权条件。
3. [x] 实现历史消息引用快照、幂等重放、显式重试关系和会话级物理级联删除。
4. [x] 增加 PostgreSQL、Redis 和 Milvus 基础健康检查。

**出口条件：** 会话、消息和引用可以保存、查询和删除；跨用户读取被拒绝。

代码级出口条件已通过 SQLite 事务、迁移升降级、跨用户拒绝和级联删除测试；Milvus 容器连通性已于 2026-10-08 验证。2026-10-09 已启动 PostgreSQL、Redis、Milvus、API 和 Worker 完整 Compose 栈并验证迁移与 readiness；但 Docker-in-WSL 冷启动时曾出现 Milvus 健康检查已通过、应用首次连接仍失败且 readiness 持续 503 的竞态，重启 API 后恢复。该冷启动场景的自动重试和集成回归仍待补充。

### 阶段 3：手工文件导入 CLI（2–3 天）

1. [x] 定义 manifest schema 和本地目录约定。
2. [x] 实现 PDF/HTML（按已确认格式）正文提取、分块、哈希和基础去重。
3. [x] 实现 Fake/真实 Embedding Provider 与向量维度检查。
4. [x] 实现 `ingest`、`--dry-run`、`--rebuild`，将 chunk 写入 `ato_knowledge_demo`。
5. [x] 输出导入、跳过和失败文件清单；重复导入未变化文件不得产生重复 chunk。

**出口条件：** 手工准备的小型 ATO 数据集可通过一条 CLI 命令导入并在 Milvus 中查询。

代码级导入、幂等、维度检查、失败隔离和 CLI dry-run 已通过自动化测试。2026-10-08
已将 manifest 声明的 4 个 PDF 实际导入 `ato_knowledge_demo`：居家办公 6 个 chunk、
自我教育资料 53 个 chunk、TR 2024/3 资料 97 个 chunk、汽车费用资料 36 个 chunk，
合计 192 个。重复执行导入时 4 个文档全部按内容哈希跳过且写入数为 0，环境级出口验收完成。

#### 阶段 3B：有限服务知识扩展（已完成）

1. [x] 为 `salary-wages-income-statement.pdf` 补齐官方 ATO URL、标题、`salary_wages`、2025–26 和访问日期并加入 manifest。
2. [x] 为 `rental-property-records.html` 补齐官方 ATO URL、标题、`residential_rental_property`、2025–26 和访问日期并加入 manifest。
3. [x] 为 `bank-accounts-and-income-bonds.pdf` 补齐官方 ATO URL、标题、`australian_bank_interest`、2025–26 和访问日期并加入 manifest。
4. [x] 扩展 manifest/导入契约测试，使六个 `claim_type`、PDF/HTML 和三份新增文件均受校验。
5. [x] 使用 `--rebuild` 重新导入 collection，记录每份新增文档的 chunk 数并人工检查正文没有导航模板、乱码或空内容。

**出口条件：** 三份新增文件已进入 manifest 和 Milvus，使用类别/年度过滤能够返回相应 ATO chunk；仅存在于本地目录但未导入的文件不计入支持范围。

2026-10-09 已使用 Fake Embedding 和 `--rebuild` 将 7 份 manifest 文档写入
`ato_knowledge_demo`，共 283 个 chunk；三份新增文档分别为：工资/招聘顾问资料 70 个、
住宅出租记录 5 个、澳大利亚银行利息 16 个。HTML 解析已限定到 ATO `content-body`
并移除站点导航模板，PDF 解析已清理嵌入控制字符。三个新增类别使用 `2025-26`
过滤的 Top-3 冒烟检索均只返回对应文档。`salary-wages-income-statement.pdf` 的实际
ATO 标题为 “Recruitment consultants - income and work-related deductions”，manifest
按实际内容登记，后续若需要面向所有职业的通用工资资料，应由维护者替换该本地文件并
同步更新 URL、标题和内容哈希。

### 阶段 4：在线检索（2–3 天）

1. [x] 将 `Retriever.plan()` 扩展为接收当前消息与最近已完成历史，优先使用当前消息，缺字段时从最近相关用户消息补齐。
2. [x] 解析 `claim_type` 和税务年度，信息不足时返回澄清请求；首期只支持三个既定类别和明确年度格式。
3. [x] 对用户查询进行最小化/脱敏后生成 Embedding。
4. [x] 实现连接真实 Milvus/Embedding/知识目录的 Retriever，使用类别/年度过滤和稠密向量 Top-K 检索，设置简单相关度阈值。
5. [x] 从真实导入的 ATO chunk 组装 `GroundingContext` 和 citations；无结果、低分或依赖不可用时失败关闭。
6. [ ] 用 5–10 个中英文演示问题人工检查单轮命中、多轮字段补全、澄清和真实 ATO 引用。

**出口条件：** 演示问题能稳定检索到正确类别/年度的 chunk，失败场景不会产生无来源清单。

阶段 4 的代码实现已启动并完成前五项：测试环境继续使用 Fake，development 在启用
Milvus 时注入在线 Retriever；检索运行会记录实际 collection、Embedding Provider、Top-K、
阈值及候选/入选数量。真实 collection 已导入，三个既定类别在 `2025-26` 的 adapter
检索冒烟均返回正确类别/年度的 Top-5，`2024-25` 严格返回空结果；第 6 项的 5–10 个
中英文问题人工内容与引用质量检查仍待完成。

#### 阶段 4B：问卷多主题检索（已完成）

1. [x] 扩展分类和字段映射，支持六个稳定 `claim_type` 的中英文词汇及问卷 option code。
2. [x] 根据多选答案生成多个单主题检索计划，分别执行类别/年度过滤检索。
3. [x] 合并并按文档、内容哈希和 chunk 去重，保留每个候选的原始类别。
4. [x] 组装 `ChecklistGroundingContext`，建立每个主题 evidence item 与 citation ordinal 的显式映射，供阶段 5D 生成并校验逐文件 checklist。
5. [x] 对任一无来源条目、错误年度、错误类别或不支持主题失败关闭。

**出口条件：** 工资、三类工作扣除、住宅租赁和澳大利亚银行利息可以在同一问卷提交中组合检索，且每个输出条目都有正确类别和年度的来源。

2026-10-09 已完成代码级与环境级验收：新增版本化六类 option-to-claim 映射、六类中英文
字段解析、每类独立的 Milvus 过滤检索、跨结果 chunk/citation 去重和主题级引用闭包。单元测试
覆盖未知 option、未支持年度、任一主题无来源、错误类别/年度及重复 chunk；显式 live smoke 在
`ato_knowledge_demo` 上一次组合检索全部六类并确认每个 item 均有 2025–26 citation ordinal。
问卷状态、最终逐文件 checklist 生成与持久化仍属于阶段 5D。

### 阶段 5：RAG 与有限税务服务聊天编排（分阶段 5A–5D）

1. 兼容旧流程：保存用户消息 → 第一层意图分类 → 普通聊天或 ATO 字段解析 → 检索/澄清 → 调用 LLM → SSE 输出 → 保存回答；阶段 5D 在其上增加持久化问卷、组合检索、checklist 和总结确认状态机。
2. 分离系统指令、用户内容、历史消息和 ATO 证据。
3. 增加 `retrieval.started`、`retrieval.completed` 和带 citations 的 `message.completed`。
4. 支持取消、失败重试、断线后的最终消息快照和引用恢复。
5. 校验文件要求类回答至少有一个实际检索引用。
6. 实现首 Token 超时、15 秒心跳、单次流最长 5 分钟和超时后的状态收敛。
7. 使用 Redis 传播多实例取消信号，并在检索阶段取消时阻止继续启动 LLM。

**出口条件：** Fake Provider 下端到端流程通过；配置真实 Provider 后可以完成一次受控 Demo。

#### 阶段 5A：Fake 编排先行（已完成代码级验收）

1. [x] 定义可替换的 `Retriever` 和 `LLMProvider` 接口，并实现确定性 Fake。
2. [x] 分离系统指令、用户内容、历史消息和检索证据，建立 Chat 状态机。
3. [x] 实现会话/消息 API 与 `generation.started`、检索、delta、完成/失败 SSE。
4. [x] 实现幂等重放、显式 retry、取消、断流取消和最终消息/引用快照恢复。
5. [x] 覆盖 grounded Fake、澄清、Provider 失败、跨用户拒绝、取消及断流测试。

阶段 5A 的 Fake citation 带有明确的测试标识，不代表 ATO 事实；Fake Provider 仅在
development/test 默认启用，staging/production 未注入真实实现时失败关闭。阶段 5
整体仍未完成：实际 Milvus 检索与 citation 已完成基础 adapter 冒烟，两层意图和普通聊天
链路已在阶段 5B 完成；共享 Redis 取消、首 Token/心跳超时及真实 Provider 受控 Demo
留待阶段 5C。

#### 阶段 5B：两层意图与普通聊天链路（已完成代码级验收）

1. [x] 新增 `IntentClassifier`、`IntentDecision` 和使用中英文确定性词表的 `FakeIntentClassifier`，第一层只区分 `general_chat` 与 `ato_document_requirements`。
2. [x] 在 `ChatCoordinator` 中先执行第一层分类：普通聊天直接构造无 evidence 的普通提示词，ATO 文件要求类请求进入现有检索/澄清流程。
3. [x] 为 `Retriever.plan()` 接入最近历史，实现“汽车费用需要哪些记录？”后仅补充“2025-26”即可开始检索。
4. [x] 扩展 `LLMRequest`、Fake LLM 和 `message.completed`，支持 `completion_kind=general_chat`。
5. [x] 为 `messages` 增加可空 `completion_kind` 及 Alembic 迁移；历史查询和幂等重放读取持久化类型，不再根据 citations 推断回答类型。
6. [x] 更新 OpenAPI，并完成普通聊天、字段澄清、多轮补全和完整 ATO RAG 四条端到端链路测试。

**出口条件：** “你好”走普通聊天；缺年度的 ATO 文件问题返回澄清；下一轮只补充年度能够进入检索；完整 ATO 问题保持带引用回答；三种完成类型均可持久化并幂等重放。

2026-10-08 已完成代码级验收：普通聊天不创建 retrieval run，三种完成类型均写入消息并在
历史查询和幂等重放中保持不变；完整测试、Ruff 和 mypy 通过。真实 Provider 与流式运行约束
仍按阶段 5C 处理。

#### 阶段 5C：真实 Provider 与流式运行约束（已完成）

1. [x] 实现基于官方 SDK 的 `OpenAIProvider` 及 OpenAI-compatible `QwenProvider`，补齐显式 Provider/模型/API Key 配置、流式错误归一化和最小用量记录。
2. [x] 在普通 CI 中继续使用 Fake；真实 Provider 仅通过显式配置执行受控冒烟测试，不因配置缺失隐式调用。
3. [x] 实现首 Token 超时、15 秒 SSE heartbeat、单次流最长 5 分钟及超时后的 `message.failed`/持久化状态收敛。
4. [x] 使用 Redis 共享取消信号；取消发生在规划或检索阶段时向下游传播，并确保不继续启动 LLM。
5. [x] 使用真实 Milvus 检索结果和真实 ATO 引用完成一次受控 Provider Demo，验证回答引用闭包和历史快照恢复。
6. [x] 增加 Fake 驱动的 heartbeat、首 Token 超时、总超时、跨实例取消测试，以及不进入普通 CI 的真实 Provider 最小冒烟测试。

**出口条件：** 阶段 5 的流式、取消和真实 Provider 要求均有明确实现与测试；配置真实 Provider 后能够基于阶段 4 的真实 ATO 检索结果完成一次带引用 Demo。

2026-10-09 已完成本阶段全部条目。自动化回归为 95 项通过、2 项 live 测试按默认策略跳过，
Ruff 与 mypy 均通过；显式启用的 Qwen live smoke 单独通过。受控 Demo 使用真实
`ato_knowledge_demo` 检索和 `qwen3.7-flash` 完成 grounded SSE 回答，事件包含检索、heartbeat、
delta 与完成，引用 `ato-car-expenses-toolkit`；相同幂等键重放返回同一消息，PostgreSQL 历史
快照恢复出相同 Provider、模型和 citation。OpenAI live smoke 因未配置 OpenAI 凭据继续按设计
跳过，不影响已选择 Qwen Provider 的阶段出口；该次验收时阶段 5D 尚未开始，现已于 2026-10-12 完成。

#### 阶段 5C.1：LLM 意图分类器与双模型配置（已完成，阶段 5D 前置）

1. [x] 扩展配置模型和 Compose 透传，增加 `SORTAX_INTENT_CLASSIFIER_PROVIDER`、`SORTAX_CLASSIFIER_MODEL`、`SORTAX_CLASSIFIER_TIMEOUT_SECONDS` 与 `SORTAX_CLASSIFIER_MAX_OUTPUT_TOKENS`；Qwen 分类器复用 `SORTAX_QWEN_BASE_URL` 和 `SORTAX_QWEN_API_KEY`。
2. [x] 实现 `LLMIntentClassifier`，通过非流式 Qwen 请求将当前消息、有限最近历史和持久化工作流状态映射为严格的 `IntentDecision`；分类提示词和 schema 均需版本化。
3. [x] 初始双模型方案固定为较强的 Qwen 主模型负责最终回答、轻量 Qwen 模型负责意图分类；具体模型 ID 只写入环境配置，不硬编码到业务模块，并在启动/冒烟测试中验证账户确实可访问。
4. [x] 分类模型只判断 `general_chat`、`tax_assistance`、`ato_document_requirements` 和 `unsupported_tax_topic`；问卷选项到 `claim_type`、税务年度校验、状态迁移和检索过滤继续使用确定性代码。
5. [x] 对分类输出执行 JSON/schema、枚举和长度校验；Provider 超时、限流、空响应或非法输出时显式调用版本化 `FakeIntentClassifier` fallback，只有 fallback 也无法安全判定时才返回稳定的可重试分类错误或范围澄清。
6. [x] 扩展 `IntentDecision` 的内部诊断元数据，记录 `classifier_source=llm|rules_fallback`、分类器版本和降级原因；不得把 fallback 结果伪装为 LLM 结果，也不得默认放行到普通聊天或无检索税务回答。
7. [x] 保留 `FakeIntentClassifier` 供普通 CI 和编排单测使用；增加受控 Qwen live smoke，验证中英文普通聊天、有限税务服务、直接文件请求和不支持税务主题四类输入，以及人为触发 Provider 故障后的 fallback 路由。
8. [x] 增加分类器单元与集成测试，覆盖提示词注入、模糊输入、短回复结合工作流状态、历史裁剪、超时、非法枚举、fallback 成功/fallback 不确定、同一 API Key 双模型调用和敏感日志扫描。
9. [x] 记录分类模型名、分类器/提示词版本、fallback 版本、延迟、Token 用量和错误类型，不记录 API Key、未经脱敏的用户正文、问卷答案或模型原始推理内容。

2026-10-11 已完成本阶段全部条目。受控 live smoke 使用同一 Qwen 凭据分别访问较强的
主回答模型和轻量分类模型，四类意图、强制 Provider 故障后的规则 fallback 以及双模型
独立访问共 6 项全部通过；模型 ID 仅保存在本地环境配置中，业务模块只读取配置字段。
普通 CI 继续使用 Fake Provider，不产生外部模型调用。

**出口条件：** 显式启用 Qwen 意图分类器后，四类意图均能以稳定 schema 路由；主回答模型与分类模型使用同一 Qwen 凭据独立选型；LLM 分类失败时可观测地降级到确定性规则，规则不确定时失败关闭，任何降级都不会把税务请求误放行到普通聊天；普通 CI 仍不产生外部模型调用。

#### 阶段 5D：有限税务问卷、Checklist 与税务总结（已完成，2026-10-12）

1. [x] 增加幂等会话 start 流程，创建内部 system trigger 并持久化首次助手问候。
2. [x] 增加 `tax_intake_sessions`、结构化消息/checklist 持久化、迁移、Repository 和租户授权。
3. [x] 实现版本化三步问卷、答案校验、断点恢复和确定性 option-to-claim-type 映射；答题、complete 和 summary 均使用 intake `version` 做原子条件更新并拒绝陈旧请求。
4. [x] 接入阶段 5C.1 的四类 LLM 意图结果，并以持久化工作流状态优先处理问卷回答和总结确认；不得重新用自由文本模型决定状态迁移。
5. [x] 完成问卷后执行阶段 4B 多主题检索，返回 `document_checklist` 和逐项 citation。
6. [x] 返回 `summary_confirmation`；显式确认后基于问卷、checklist 和引用快照生成 `tax_summary`，拒绝时不调用 LLM。
7. [x] 扩展 SSE、历史查询、幂等重放、取消和重试，使结构化消息在刷新后完整恢复；取消 checklist/summary 后状态收敛到可重试节点，新消息保留 `retry_of_message_id` 并复用持久化 citation 快照。
8. [x] 增加跨租户、非法状态迁移、并发提交、无来源条目、未支持类别/年度及删除级联测试；同时覆盖同租户跨用户、并发 complete、结构化取消/重试和 intake/checklist item 级联删除。

2026-10-12 最终验收：运行时模型已与 `docs/openapi.yaml` 0.3.0 的 5D 字段及必填集合建立自动对比测试；
问卷、checklist、summary 与 citation 的结构化内容已对齐，citation 快照持久化 `claim_type`。
完整后端测试为 148 passed、9 skipped，Ruff 通过，生产代码 `mypy src` 检查 77 个文件无错误。
前端 OpenAPI 类型漂移检查、TypeScript、ESLint、19 个单测和生产构建全部通过。`mypy src tests`
仍有本阶段开始前已记录的测试桩类型错误，不影响 5D 生产代码与运行时验收。

**出口条件（已满足）：** 从首次问候、自由输入、税务路由、版本化问卷、组合检索、带逐项引用 checklist、总结确认到带引用税务总结的完整链路可重复演示；普通聊天回归、结构化历史恢复、取消、重试、并发冲突和租户隔离均有自动测试覆盖。

### 阶段 6：Demo 验收与说明（已完成，2026-10-12）

1. [x] 测试导入、单/多主题检索、问卷恢复、状态迁移、逐项 citation、税务总结、无命中、Milvus 不可用、会话删除和跨用户访问。
2. [x] 检查日志不包含 API Key、JWT 或未脱敏的用户原文。
3. [x] 编写 README：启动服务、准备 manifest、导入文件、获取开发 JWT 和发起 RAG 聊天。
4. [x] 准备一组可重复演示的问题、预期引用和已知限制。

2026-10-12 完成环境与真实依赖验收：Docker 数据盘位于 D 盘，PostgreSQL、Redis、etcd、
MinIO 和 Milvus 五个服务均通过健康检查；Alembic 升级到 head。manifest 干跑确认 7 份文档、
283 个 chunk、0 失败，实际幂等导入确认 7 份均安全跳过且未重复写入。显式 Milvus live smoke
对六个支持类别全部通过。

使用随机开发身份、真实 PostgreSQL/Redis/Milvus 和 Fake LLM 完成完整本地 API Demo：幂等问候、
三步问卷保存与恢复、工资/居家办公/汽车费用三主题检索、3 个逐项 citation checklist、总结确认、
复用 citation 快照的税务总结、结构化历史恢复、同租户跨用户 404，以及会话、intake 和受限答案的
物理删除级联均通过。停用 Milvus 时发现 readiness 仅缓存启动状态，已改为每次请求动态探测依赖并
增加可用→不可用→恢复测试；实机复测为 liveness 200、readiness 503、SSE 只返回
`message.failed`，Milvus 恢复后 readiness 自动回到 200，没有生成无来源回答。

日志门禁新增 JWT 和请求正文不进入请求日志的自动测试，并与现有 API Key/分类器原文日志测试共同
覆盖本阶段要求。README 已补充低磁盘本机 API 启动路径、完整问卷 Demo、10 个中英文/边界演示问题、
预期 ATO document ID、Milvus 故障演练和已知限制。最终回归为后端 150 passed、9 skipped，
Ruff 检查与格式检查通过，`mypy src` 77 个生产文件无错误；前端 OpenAPI 漂移检查、TypeScript、
ESLint、19 个单测、生产构建和 6 个 Playwright E2E 全部通过。

**出口条件（已满足）：** 新开发者可以按照 README 启动本地依赖、迁移数据库、幂等导入 reviewed
ATO manifest，并完成一次带真实 ATO citation 的有限税务聊天演示；依赖故障会动态反映在
readiness 中并失败关闭。

### 工期与关键路径

- 阶段 3B 来源元数据和入库已确认；剩余关键不确定性为多主题检索效果、结构化输出稳定性和真实 Provider 联调。
- 关键路径中的 5C.1、5D 和阶段 6 Demo 验收与说明均已完成；后续生产化工作需另立计划。
- 不包含自动抓取、管理后台、生产部署、生产灾备、复杂混合检索或大规模性能优化。

## 9. 边界条件与处理策略

### 9.1 请求与幂等

- 用户双击发送、网络重试：同一 `client_message_id` 返回已有结果，不重复调用模型。
- 幂等请求已完成检索但生成尚未完成：复用同一 `retrieval_run` 和证据快照；不得因重连再次产生 Embedding 费用。
- 同一会话同时发送多条消息：MVP 返回 `409 conversation_busy`，或进入显式队列；不可静默改变上下文顺序。
- 请求体为空、全空白、超长或编码异常：在进入模型前返回可定位的 `4xx`。
- 客户端时间不可信：排序与审计只使用服务端时间。
- 首次问候、完成问卷和税务总结分别使用独立 `client_request_id`；同一键负载不同返回 `409 idempotency_conflict`，相同负载返回原结果。
- 同一 intake 并发提交两个答案或同时 complete：使用版本/状态条件更新；失败请求返回 `409 invalid_workflow_state`，不得重复检索或生成两份 checklist。

### 9.2 流式连接

- 首 Token 超时：终止 Provider 调用，消息标记失败并允许重试。
- 中途断流：保存已产生内容并标记失败或取消；不能误标 completed。
- 客户端断开：设置取消信号；若供应商无法取消，丢弃后续输出但仍对用量进行对账。
- 代理缓冲或空闲断开：发送心跳，关闭反向代理缓冲并设置合理空闲超时。
- 重连时事件已过期：返回当前消息快照和最终状态，客户端从快照恢复。
- 多实例取消：取消信号必须经 Redis 等共享介质传播。

### 9.3 数据一致性

- 用户消息已提交但模型调用未开始：后台修复任务将超时 run 收敛为 failed。
- 助手内容已生成但最终写库失败：有限重试；保留 generation run 和 Provider 请求 ID 供对账。
- Worker 重复执行：任务以业务幂等键保护，不能重复生成标题或审计记录。
- 会话删除时仍在生成：先取消活动 run 并等待状态收敛，再以事务物理删除会话和消息；删除请求必须幂等。
- 会话删除事务必须覆盖 retrieval run 与 citation 快照；删除后到达的异步回调只能完成最小对账，不得复活消息、引用或查询内容。
- 乐观锁冲突：返回 `409` 和最新版本，不静默覆盖标题或状态。
- 问卷答案写入、工作流状态迁移和对应结构化消息创建必须处于明确事务边界；不得出现状态为 `checklist_ready` 但 checklist 消息或 citation 不存在。
- Checklist item、message citation 和助手消息完成状态原子提交；逐项引用验证失败时整条消息失败，不保存伪完整 checklist。

### 9.4 上下文与模型

- 历史超过上下文窗口：按 Token 预算裁剪，保留系统提示和最近轮次；摘要必须标注版本。
- 单条消息本身超出窗口：拒绝并提示限制，不截断后继续造成语义误解。
- Provider 返回 429/5xx：仅对未产生可见 Token 的幂等请求做指数退避；产生 Token 后不自动换模型拼接答案。
- Provider 内容过滤：返回稳定业务错误，保留最少必要审计元数据。
- Provider 输出非法 UTF-8、空完成或重复分片：适配层归一化并按 `seq` 去重。
- 模型切换：记录模型和提示词版本，确保后续问题可追溯。

### 9.5 身份与多租户

- JWT 过期、撤销、时钟偏差或 JWKS 轮换：短期缓存 JWKS，轮换时刷新，使用有限时钟容差。
- URL 中资源属于其他租户：统一返回 `404`，避免枚举资源存在性。
- 用户离职或权限在长连接期间被撤销：限制单次流最长时长；敏感场景可在关键节点重新鉴权。
- 管理员审计访问：使用独立权限与审计事件，默认不可读取完整消息正文。

### 9.6 会计与合规

- 不同币种、小数精度和负数格式：不得用二进制浮点表示金额；展示与计算规则显式携带币种。
- 财年、时区和日界线：UTC 存储，组织时区与财年设置用于解释日期。
- 用户要求模型执行付款、报税或入账：MVP 只解释或生成草稿，不执行；明确提示需要专业复核。
- 模型幻觉或法规过期：界面/API 返回模型与知识时点元数据；涉及法规、税率和申报结论时要求来源与人工复核。
- 用户输入密钥、账号或个人信息：日志不得记录原文；正文只有通过统一脱敏器后才能写入受控日志。
- 数据删除与法定留存冲突：当前产品语义为立即物理删除；生产上线前如确认存在强制留存义务，必须完成合规评审并显式修订产品规则。
- 有限服务范围外的税务主题和年度：返回范围说明，禁止用模型常识补全；普通聊天不得被用作绕过 grounded 税务链路的后门。
- 税务总结必须标明它是基于用户问卷和有限 ATO 资料的信息摘要，不是完整申报、资格判断或注册税务代理意见。

### 9.7 容量与滥用

- 超大历史、热点租户和连接洪峰：游标分页、并发配额、连接数限制和背压。
- Redis 不可用：对生成请求采用失败关闭或降级到更严格的本地限制，不能无限放行。
- PostgreSQL 无法连接：就绪检查失败并快速返回错误，避免请求长期等待。
- 恶意 Prompt 注入：用户内容与系统指令结构化隔离；未来工具调用使用白名单、参数校验和最小权限。
- 离线摄取突发占满 CPU、网络、Embedding 配额或 Milvus 写资源：使用独立队列、并发池、速率预算和可暂停调度；在线检索优先，必要时停止摄取而不是拖垮聊天。

### 9.8 ATO RAG 与知识时效

- 是否进入 ATO RAG 先由第一层意图分类决定，不能以用户是否写出税务年度作为直接开关。
- 第一层无法识别为 ATO 文件要求类的问题在 Demo 中进入普通聊天；普通聊天不创建 retrieval run，也不返回 citations。
- 用户说“退税”但未说明申报/扣除类别或税务年度：先澄清，不能选择最相近类别后直接给出文件清单。
- ATO 澄清后的简短补充可从最近已完成的相关用户消息继承缺失类别或年度；当前消息中的明确值优先。
- 同一类别在不同税务年度要求不同：必须先按税务年度过滤；没有匹配年度的已导入资料时返回证据不足。
- 本地文件更新：修改 manifest 或替换文件后由开发者重新运行导入；软件不自动检查 ATO 网站是否变化。
- manifest 缺少 URL、类别、年度或访问日期：导入该文件失败并显示可定位错误，不使用不完整数据。
- 本地文件损坏、加密或解析结果为空：跳过该文件并在 CLI 汇总中报告，不写入空 chunk。
- 多个导入来源互相矛盾：回答中显示相关来源并提示需要人工确认，不生成确定性结论。
- 语义相近但类别不同：使用 `claim_type` 元数据过滤和演示问题防止把另一类别材料混入答案。
- 搜索低分或无命中：返回 `insufficient_evidence` 或澄清问题，不允许 LLM 使用参数记忆补齐清单。
- Milvus、Embedding 或 Demo collection 不可用：返回可重试错误，不降级成无 RAG 的税务回答。
- Embedding 模型或维度变化：使用 `--rebuild` 重建整个 Demo collection，禁止把不同维度混入同一 collection。
- 重复 chunk、网页模板和导航文本：按文档/内容哈希进行基础去重，避免单一文件刷屏。
- ATO 文档内包含类似指令的文字：一律作为引用数据处理，不能改变系统行为、调用工具或访问其他数据。
- 本地导入路径越过配置的 ATO 数据目录，或文件类型/大小超限：拒绝导入，防止任意文件读取。
- 用户在查询中包含个人税务信息：查询日志必须先脱敏；发送给 Embedding Provider 的内容遵守与 LLM 相同的数据控制要求。
- 新增本地文件未进入 manifest、未成功导入或没有人工确认来源元数据时，对应类别保持不支持状态。
- 多选检索某一类别证据不足：不得用其他类别的相似文档替代；可返回整体失败，或在结构化结果中明确标记该类别无法支持，但不得输出无 citation 的文件条目。
- 用户在总结确认状态回复其他自由文本时，不自动视为同意；只有结构化请求中的 `requested=true` 才允许生成税务总结。

## 10. 测试策略

### 单元测试

- 会话/消息状态机、上下文裁剪、Token 预算、配额算法
- Provider 错误映射、SSE 事件编码、脱敏器、权限规则
- `FakeIntentClassifier` 使用中英文确定性词表区分普通聊天与 ATO 文件要求；缺少税务年度不影响第一层 ATO 意图判断
- 普通消息中的年份不会单独触发 ATO RAG；最近一轮为 ATO 澄清时，简短年度回复继续进入 ATO 分支
- 英文基线问题 `What car records are needed for 2025-26?` 保持进入 ATO RAG；英文缺年度问题保持进入字段澄清而非普通聊天
- `Retriever.plan()` 覆盖当前消息字段完整、当前类别加历史年度、当前年度加历史类别以及字段仍不完整四种情况
- `claim_type`/税务年度解析、分块边界、内容哈希、元数据过滤、阈值和引用组装
- Fake Embedding 的确定性、向量维度校验和证据不足的失败关闭
- 三步问卷模板、必答规则、单选/多选互斥规则、未知 option 拒绝和 option-to-claim-type 映射
- 税务工作流全部合法迁移和非法迁移；在不同状态下正确解释 yes/no
- 六个有限 `claim_type` 的中英文分类、2025–26 年度限制和未支持主题/年度判定
- 多主题合并去重、逐 checklist item citation 闭包和错误类别/年度拒绝

### 集成测试

- PostgreSQL 事务、唯一约束与应用层跨租户/跨用户隔离
- Redis 限流、取消信号、锁过期
- SSE 正常完成、超时、中断、客户端断开和重连
- 普通聊天不调用 Retriever、不创建 retrieval run，最终返回 `general_chat`、`grounded=false` 和空 citations
- ATO 字段澄清不调用检索；下一轮补齐字段后只创建一次 retrieval run 并进入现有 grounded 链路
- `completion_kind` 随消息落库，历史查询和幂等重放保持 `answer`、`clarification`、`general_chat` 原值
- 本地 manifest 校验、HTML/PDF 解析、重复导入幂等和 `--rebuild`
- Milvus Demo collection 创建、写入、查询和清空重建
- Milvus/Embedding 超时、连接中断、索引不存在和维度不匹配
- 历史引用快照不依赖 Milvus 实时查询；会话删除级联清理检索与引用记录
- 首次问候幂等生成、问卷逐题保存/刷新恢复、并发 complete、总结接受/拒绝和结构化消息历史恢复
- 问卷答案、checklist、citations 与工作流状态的事务一致性及删除级联
- 三份新增 ATO 文件的 manifest、PDF/HTML 解析、真实类别过滤和组合检索

### 契约与端到端测试

- OpenAPI schema 快照与前端消费契约
- Fake Provider 的确定性、流式分片、故障、超时和取消端到端流程
- 端到端使用中英文输入覆盖普通聊天、ATO 字段澄清、多轮补全和完整 ATO RAG；验证各分支 SSE 事件顺序
- 真实 Provider 的最小冒烟测试，不在普通 CI 中暴露密钥或产生不可控费用
- LLM 意图分类器的 schema/枚举校验、超时与非法输出 fallback、fallback 来源标记及二次不确定时失败关闭；显式 live smoke 使用同一 Qwen Key 分别调用分类模型和主回答模型
- ATO RAG 回答的 `citations` 契约及 chunk/文档关联
- 5–10 个中英文演示问题覆盖正确命中、澄清和证据不足
- OpenAPI 覆盖 start、intake 查询/答题/完成、总结确认、结构化消息和逐项 citation
- 完整 E2E：问候 → 税务路由 → 三步问卷 → 多主题检索 → checklist → 总结确认 → 税务总结
- 不支持主题和年度必须以稳定错误/范围消息结束，且不会创建无来源税务回答

### 性能与安全测试

- 基础长连接、首 Token 延迟和消息落库测试；Demo 不进行大规模压测
- 小批量嵌入、Milvus 查询和 collection 重建冒烟测试
- JWT 篡改、IDOR、跨租户查询、提示注入、脱敏日志敏感信息扫描和脱敏失败关闭测试
- 本地路径越界、异常文件、超大文件和 RAG Prompt Injection 基础测试

## 11. 初始目录结构

```text
sortax/
├─ src/sortax/
│  ├─ main.py
│  ├─ api/
│  ├─ identity/
│  ├─ conversations/
│  ├─ messages/
│  ├─ chat/
│  ├─ intent/
│  ├─ tax_intake/
│  ├─ tax_guidance/
│  ├─ llm_gateway/
│  ├─ embedding_gateway/
│  ├─ knowledge/
│  │  ├─ catalog/
│  │  └─ ingestion/
│  ├─ rag/
│  │  ├─ retrieval/
│  │  └─ evaluation/
│  ├─ prompting/
│  ├─ safety/
│  ├─ quota/
│  ├─ audit/
│  ├─ infrastructure/
│  │  ├─ persistence/
│  │  ├─ vector_store/
│  │  └─ local_documents/
│  ├─ observability/
│  └─ workers/
├─ migrations/
├─ tests/
│  ├─ unit/
│  ├─ integration/
│  ├─ contract/
│  ├─ e2e/
│  └─ evaluation/
├─ manifests/
│  └─ ato/
├─ data/ato/raw/  # 本地导入目录，加入 .gitignore
├─ deploy/
├─ docs/
├─ pyproject.toml
├─ compose.yaml
├─ .env.example
└─ BACKEND_PLAN.md
```

## 12. 已确认的非功能目标

- 本地 Demo 在普通开发机和小型语料集下，Milvus 检索与引用组装应在约 2 秒内完成；真实 Provider 网络耗时单独观察，不设生产 SLO。
- 导入 CLI 对单个失败文件给出明确错误并继续处理其他文件。
- 完成状态的消息不可为空；生成状态最终必须收敛。
- 不允许跨租户或同租户跨用户读取聊天。
- SSE 心跳间隔为 15 秒。
- 单条用户消息不超过 16 KiB；单次流最长 5 分钟。
- 同一会话最多存在一个活动生成任务。
- 历史分页默认 30 条、最大 100 条。
- 日志、追踪和指标中不得出现 API Key、JWT、原始完整消息正文或未脱敏会计个人数据；脱敏正文字段必须截断并限制访问。
- ATO 文件要求类回答必须带至少一个实际检索引用；5–10 个演示问题需人工确认命中内容合理。
- Document Checklist 每个文件条目必须带至少一个同类别、同年度的实际检索引用和通俗解释；消息级存在 citation 但条目未关联仍视为验收失败。
- 问卷和总结确认状态在刷新后可以恢复；同一幂等键不会重复问候、重复检索或重复调用 LLM。
- 税务总结只在显式确认后生成，并复用 checklist 的问卷和引用快照。
- `/health/ready` 能反映 PostgreSQL、Redis 和 Milvus 是否可连接。

以下情况阻止 Demo 验收：

- 出现跨租户或同租户跨用户的数据访问。
- 日志出现 API Key、JWT、原始正文或未脱敏敏感数据。
- 重复请求产生重复消息或重复模型费用。
- 生成任务无法从 `pending`/`streaming` 收敛到最终状态。
- 用户删除后聊天正文仍可查询。
- 自动化测试意外调用真实 OpenAI Provider。
- ATO 文件清单没有引用、引用不来自 manifest 中的文档，或税务年度不匹配。
- Milvus/Embedding 不可用时系统仍生成无来源税务文件清单。
- 任一 checklist 文件条目没有 citation、citation 指向错误类别/年度，或使用未进入 manifest 的来源。
- 海外收入、政府补助或其他未支持主题被普通聊天链路生成事实性税务 checklist/总结。
- 页面刷新导致活动问卷丢失、重复创建 intake 或重复产生模型/Embedding 费用。

## 13. 验收清单

- [ ] 所有 API 都有认证、租户隔离、输入校验和稳定错误码。
- [ ] 重复发送不会产生重复用户消息或重复模型费用。
- [ ] SSE 支持开始、增量、完成、失败、心跳和中途取消。
- [ ] SSE 支持 `retrieval.started`/`retrieval.completed`，检索阶段取消不会继续调用 LLM。
- [x] “你好”等非 ATO 文件要求问题走普通聊天，不创建 retrieval run，完成事件为 `general_chat` 且没有 citations。
- [x] “汽车费用需要哪些记录？”识别为 ATO 文件要求并澄清税务年度，不因缺少年度退回普通聊天。
- [x] 澄清后的下一轮仅输入“2025-26”时可从最近历史补齐汽车类别并进入检索。
- [x] 完整 ATO 文件要求问题进入 RAG，最终事件为 `answer` 且至少包含一个持久化引用。
- [x] 英文普通聊天、英文 ATO 字段澄清、英文多轮补全和现有 `What car records are needed for 2025-26?` 完整链路均通过回归测试。
- [x] `answer`、`clarification`、`general_chat` 均保存到消息并在历史查询和幂等重放中保持不变。
- [x] 首次助手问候由幂等 start 端点生成、持久化并可重放，刷新页面不会重复调用 LLM。
- [x] 税务输入创建或恢复版本化三步问卷；普通聊天不创建 intake，明确未支持税务主题不会退回无来源普通回答。
- [x] 问卷答案可以逐题保存和刷新恢复，未知题目/选项、非法状态和跨用户访问被拒绝。
- [x] 六个有限 `claim_type` 均已进入 manifest、成功导入并通过 2025–26 类别过滤冒烟；三份新增文件仅在此条件满足后标记为支持。
- [x] 多选问卷只检索已选择的支持类别，结果按文档/内容/chunk 去重且不会跨类别替代证据。
- [x] `document_checklist` 每个文件条目都有通俗解释、适用原因和至少一个同类别同年度 citation ordinal。
- [x] Checklist 后只在结构化 `requested=true` 时生成税务总结；拒绝时不调用 LLM，确认状态可恢复。
- [x] `questionnaire`、`document_checklist`、`summary_confirmation`、`tax_summary` 在历史查询和幂等重放中保持结构化内容与原 citation 快照。
- [ ] 断线、超时、Provider 429/5xx 和数据库短暂故障后状态可收敛。
- [ ] 会话/消息分页在并发写入下不重复、不遗漏已确定范围的数据。
- [x] 日志和追踪通过敏感信息扫描。
- [x] 用户删除会话后正文被物理删除，重复删除保持幂等，审计事件不保留正文副本。
- [ ] 超过 180 天的会话和消息被清理，清理任务重复执行不会误删未到期数据。
- [x] 跨租户与越权测试是 CI 强制门禁。
- [ ] Token 用量、模型、提示词版本、追踪 ID 和生成结果可审计。
- [ ] Embedding 用量、检索配置、collection 名称、文档 ID 和内容哈希可追踪，且日志不复制查询或 chunk 正文。
- [x] ATO RAG 只检索 manifest 中已导入且税务年度匹配的文档，Milvus 中不存在聊天正文或用户私有数据。
- [x] 每个 ATO 文件要求类回答均带可点击 ATO 引用，并可追溯到 document ID、content hash 和 chunk ID。
- [x] 历史消息从 PostgreSQL 引用快照恢复，不依赖重新查询 Milvus。
- [x] 证据不足、来源冲突或 Milvus/Embedding 故障时失败关闭，不生成无来源清单。
- [x] 本地路径越界、文件缺失、超大文件和不支持的文件类型被导入 CLI 拒绝并明确报告。
- [x] 重复导入未变化文件不产生重复 chunk；Embedding 模型维度变化时可通过 `--rebuild` 重建 collection。
- [x] 会话物理删除同时清理 retrieval runs 和 citation 快照，但不删除全局 ATO 公共知识；迟到回调不会复活已删除记录。
- [x] 会话物理删除同时清理 tax intake、checklist item、总结状态及其 Restricted 答案；日志和审计不保留答案副本。
- [x] 5–10 个演示问题覆盖正确命中、澄清和无结果场景。
- [x] README 可以指导新开发者启动依赖、导入本地文件并完成一次带引用聊天。

## 14. 已解决决策与 Demo 开发前确认项

原聊天基线已采用保守默认值，RAG 需求使阶段 0R/1R 重新打开。本项目当前以本地可运行 Demo 为目标，不把生产部署、容量、灾备和正式合规审批作为开发范围。

1. ~~现有身份系统是什么，JWT 中哪个 claim 表示租户、用户和角色？~~ 已确认：开发 JWT；`sub`、`tenant_id`、固定 `user` 角色。
2. ~~首选 LLM 提供商、模型、数据处理区域和零数据保留要求是什么？~~ 已确认：本地默认 Fake，OpenAI 适配器按环境变量显式选择模型；Demo 禁止使用真实客户数据。
3. ~~聊天记录保留多久，用户是否可以彻底删除，是否存在法定留存要求？~~ 已确认：默认 180 天，用户主动操作立即物理删除；审计保留期限和生产法定留存要求待上线前确认。
4. ~~是否需要从第一版支持附件？~~ 已确认：MVP 不支持附件。
5. ~~首期是否需要企业知识库/RAG？~~ 需求已变更：MVP 支持限定的 ATO 官方资料 RAG，使用 Milvus；仍不支持通用企业知识库和用户自助知识库。
6. 容量目标：只要求单机本地 Demo 和小型 ATO 语料集，不做生产容量规划。
7. 目标部署环境：Docker Compose 本地开发；不进行生产平台选型。
8. ~~哪些会计请求属于高风险动作？~~ 已确认：MVP 可解释或生成草稿，但禁止执行付款、报税提交、凭证入账、修改总账或外部会计系统写操作。

RAG 开发前确认项已在阶段 0R 完成：

1. ~~首批 `claim_type` 及覆盖税务年度。~~ 已扩展确认六个有限类别和 2025–26：`salary_wages`、`working_from_home`、`work_related_car`、`self_education`、`residential_rental_property`、`australian_bank_interest`。
2. ~~优先支持 PDF、HTML，还是两者都支持。~~ 已确认两者都支持。
3. ~~Demo 使用 Fake Embedding、真实 Embedding Provider，或两者都提供。~~ 已确认两者都提供且默认 Fake；真实 Provider 仍须满足输入不用于训练和仅使用模拟/公开数据的要求。
4. ~~有限税务服务流程。~~ 已确认：首次问候 → 自由输入路由 → 三步问卷 → 多主题检索 → 逐项引用 checklist → 总结确认 → 带引用税务总结。
5. ~~不支持税务主题的处理。~~ 已确认：海外收入、政府补助、一般投资及其他未导入主题返回有限范围说明，不允许退回普通聊天生成事实性税务建议。

如果未来要上线生产，再另行制定生产化计划，包括外部身份系统、ATO 自动同步、正式来源审核、Milvus 高可用、备份恢复、容量、安全审计和法规合规。

## 15. 后续扩展路径

1. **附件模块：** 预签名上传、病毒扫描、解析、内容分块和访问控制。
2. **RAG 扩展：** 在 ATO 官方资料 MVP 稳定后，再评估其他政府来源、企业私有知识库和租户隔离 collection；不得直接混入现有公共 ATO collection。
3. **工具调用模块：** 只读会计查询优先；所有写操作使用白名单、参数校验、审批和幂等审计。
4. **模型路由：** 按任务、成本、延迟和数据区域选择模型，保持统一网关接口。
5. **独立服务拆分：** 仅当容量或团队边界证明必要时，再拆分模型网关、Worker 或审计服务。
