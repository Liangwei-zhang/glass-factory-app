# TODO: 100% 落实 sj.md

本文件是 `sj.md` 的执行清单，从现在开始作为项目开发基线使用。

勾选标准：
- `[x]` 代码已存在，且已经接入当前主路径，能力不是纯骨架或占位。
- `[ ]` 未完成、部分完成、仅有目录/文件、未接入主路径、未验证，一律不打勾。

即日起开发约束：
- 不再向 `/api/*` 兼容层新增功能；兼容层只允许修复阻断问题和做迁移兜底。
- 所有新功能优先落在 `/v1/*`、`domains/*`、`infra/*` 的正式路径上。
- 严格执行 Router -> Service -> Repository 分层；Router 不写业务逻辑，Repository 不调外部服务。
- 所有跨域副作用统一走 Outbox + EventBus，不再直接在兼容层或路由层拼接流程。
- 只有本文件对应项完成后，才允许声称“已经按 sj.md 落地”。

## 第一章 系统概述 / 三端架构

- [x] 已具备 Public API 和 Admin API 两个 FastAPI 入口。
- [x] 拆分 `/app`、`/platform`、`/admin` 为三个独立前端壳和独立导航。现状：已分别落到 `public/app.html`、`public/platform.html`、`public/admin.html` 与独立脚本入口。
- [ ] 让 `/app` 只承载客户端能力：在线下单、订单跟踪、物流跟踪、对账查询、历史订单、个人中心。
- [ ] 让 `/platform` 只承载业务操作端能力：订单录入、生产排产、库存管理、质检录入、发货安排、客户管理。
- [ ] 让 `/admin` 只承载管理端能力：用户权限、系统配置、数据看板、财务审核、运维监控、审计日志。
- [ ] 完成 `customer` / `customer_viewer` 外部用户模型的全权限矩阵与全链路边界。当前已完成 `users.customer_id`、token `customer_id` claim、`customer_viewer` 只读边界、admin users 的客户绑定可见性、`/v1/app` 的 orders/profile/credit/notifications 自助接口，以及 canonical role/scopes 派生与主路径响应透出。

## 第二章 架构设计

- [x] 已建立 `apps/`、`domains/`、`infra/`、`alembic/`、`ops/` 的模块化单体目录骨架。
- [x] 已有请求上下文、统一错误模型、统一响应 envelope、配置系统、日志模块。
- [x] 已有 PgBouncer 友好的 async SQLAlchemy session 配置。
- [x] 清理 `domains/workspace/legacy_api_service.py` 中的业务逻辑、序列化逻辑和兼容桥接逻辑。已将 `/v1/app` 与 `/v1/workspace` 主路径所需的会话、订单、客户、通知、设置、邮件日志与 UI 序列化能力全部迁入正式 helper/service，并删除已停止挂载的 legacy compatibility service 文件。
- [x] 从公共主路径移除 `/api/*` compatibility router，正式只保留 `/v1/*` 作为业务 API。
- [ ] 逐域审计分层边界，确保 Router 不写业务逻辑、Repository 不做外部 I/O、跨域副作用只走事件。
- [x] 已新增 `/v1/workspace/*` 正式操作端 API 面，平台端主路径已从 `/api/*` 迁出。
- [x] 已新增 `/v1/app/*` 正式客户端 API 面，客户端主路径不再依赖 `/api/*` 暴露面。

## 第三章 技术栈详解 / 第四章 项目目录结构

- [x] FastAPI、PostgreSQL、Redis、Kafka、ClickHouse、MinIO、Docker Compose、Makefile 已进入当前仓库。
- [x] File-backed secrets 已实现，配置支持 `*_FILE` 读取敏感值。
- [ ] 清理或归档 legacy Node 运行时 `backend/`，避免与 Python 主架构并行演进。
- [ ] 补齐 `ops/k8s/base/` 基线清单；当前目录为空。
- [ ] 按 `sj.md` 目录规范继续消化遗留路径，避免新功能再落回 legacy 目录。

## 第五章 核心领域模块设计

### 5.1 订单域

- [x] 已有 orders 的 `schema.py`、`repository.py`、`service.py`、错误定义、ORM 模型和 Alembic migration。
- [x] 已有 `/v1/orders` 的创建、列表、详情、取消、确认、时间线等端点。
- [ ] 对齐 `sj.md` 的完整订单状态机和状态转换约束，并补齐对应单元测试和集成测试。现状：已补 `OrderStatus` + transition matrix，收紧 `pending/confirmed/entered/in_production/completed/shipping/delivered/ready_for_pickup/picked_up/cancelled` 的主路径迁移约束，已明确拒绝 entered 后回退 confirm、生产启动后取消、未 entered 直接执行生产工序，并把重复 pickup approve 收口为 `ready_for_pickup` 幂等；物流正式写路径现在也会把订单态从 `completed/ready_for_pickup` 推进到 `shipping`，签收后推进到 `delivered`，且签收后财务建应收仍可继续；但 `sj.md` 中最终 completed 定义、客户端统一下单入口与更广覆盖仍待继续。
- [x] 让客户端真实下单链路切到 `/v1/orders`，不再经过 `/api/orders` 兼容路径。现状：`/app` 客户端表单提交现已改为直连正式 `/v1/orders` 创建，并在创建后按需走 `/v1/orders/{order_id}/drawing` 上传图纸；`/v1/app/orders` 保留为兼容桥接但不再是客户端主创建入口。
- [ ] 校验订单域对库存、通知、生产、分析的副作用是否全部通过事件链路闭环。

### 5.2 库存域

- [x] 已有 inventory 的 `schema.py`、`repository.py`、`service.py`、router、ORM 模型。
- [x] 用 Redis Lua + TTL 实现库存预扣减、确认扣减、回滚，替换当前数据库循环扣减实现。现状：已落到 Redis reservation store + DB reservation ledger + Outbox，订单创建/确认/取消/录入生产/改单数量都会驱动正式库存链路。
- [ ] 把库存同步 worker、缓存和事件回放真正接入库存主路径。现状：`inventory_sync` worker 已接入过期 reservation 释放与低库存告警，并补了 worker 级回归；缓存读路径与事件回放主收益仍待完成。
- [ ] 为库存竞争场景补齐并发测试、超时回滚测试和幂等测试。现状：已补重复创建幂等不重复预留、缺失 `Idempotency-Key` 明确拒绝、`RedisInventoryReservationStore` 的 reserve/confirm/release/restore store 级回归，以及过期 reservation worker 回归；并已补真实 Redis + DB integration 基座，覆盖真实并发 reserve 单赢家、rollback restore，以及 `OrdersService.create_order` / `cancel_order` 的正式 Postgres + Redis 主路径，更大规模竞争与 soak 仍待继续。

### 5.3 生产域

- [x] 已有 production 的 `schema.py`、`repository.py`、`service.py`、`scheduler_engine.py`、public/admin router 和 worker。
- [ ] 对齐 `sj.md` 的排产、工单、质检、验收、任务视图等全链路行为。
- [ ] 验证订单事件到排产生成、工单执行、产线配置变更的端到端闭环。

### 5.4 其他领域模块

- [x] 已有 customers、finance、logistics、notifications 的基础 domain 文件和 API 路由。
- [x] 客户域从“操作员视角”切换到“客户视角”，`profile` / `credit` 已真正绑定 customer identity，不再 fallback 到 `user.user_id`。
- [ ] 实现客户等级定价、客户中心和客户生命周期管理能力。
- [ ] 财务域补齐应收应付、自动对账、发票流转、财务审核流程。现状：已补 `create_receivable` / `record_payment` / `record_refund` 正式 service、`/v1/finance/receivables` 与 `/v1/workspace/orders/{order_id}/receivable` 等写接口，并在 workspace/direct e2e 覆盖应收创建、部分回款、全额回款、退款、超额回款拒绝与超额退款拒绝；response-level contract 现已进一步覆盖“应收金额不得低于已回款金额”、`Receivable not found`，以及 direct/workspace finance 写接口缺失 `Idempotency-Key` 的错误 envelope；自动对账、审核流和更完整 settlement 审计仍待继续。
- [ ] 物流域补齐发货计划、配送流程、签收确认、异常跟踪流程。现状：已补 `create_shipment` / `deliver_shipment` 正式 service、`/v1/logistics/shipments` 与 `/v1/workspace/orders/{order_id}/shipment` 等写接口，并在 workspace/direct e2e 覆盖发货、签收与重复签收幂等语义；订单主状态也已在正式物流写路径上推进到 `shipping/delivered`；异常跟踪与计划排线仍待继续。
- [ ] 通知域补齐模板、渠道、事件订阅、送达状态和已读闭环。

## 第六章 数据库设计

- [x] 已有 Alembic 环境、核心 ORM 模型和多条初始化/演进 migration。
- [ ] 逐表核对 `sj.md` 的 DDL、字段、索引和 ER 关系，补齐缺失项。
- [ ] 对审计、分析、设置、附件、通知等非核心表做一次文档对齐核查并落 migration。
- [ ] 把“目录已存在但结构仍偏旧”的数据模型整理成明确的数据库差异清单。

## 第七章 缓存设计

- [x] 已有 Redis client、order/customer/inventory cache helper、cache-after-commit hook 机制。
- [ ] 将 order/customer/inventory cache 真正接入读路径；当前 helper 存在，但还没有形成主路径收益。
- [ ] 按 `sj.md` 建立 TTL 策略矩阵，并落实到代码和文档。
- [ ] 补齐缓存穿透、击穿、雪崩防护：negative cache、互斥重建、随机过期等策略。
- [ ] 统一缓存更新入口，所有写后缓存刷新都走 after-commit hook。

## 第八章 事件驱动设计

- [x] 已有 Outbox、topics、broker、dispatcher 和 event pipeline worker 骨架。
- [x] 已有 order timeout、inventory sync、production scheduler、notification dispatch、analytics sink、retention、cold storage worker 入口。
- [ ] 为每个跨域事件补齐发布点、订阅处理器和端到端验证。
- [ ] 确保跨域流程不是 service 直接串调用，而是发布事件后由订阅者处理。
- [ ] 让 analytics sink 和下游查询真正使用 ClickHouse / 事件流，而不是只查 OLTP 表。

## 第九章 API 设计规范

- [x] 已实现统一成功响应 envelope。
- [x] 公共 API 和管理 API 的 `/v1/*` 路由骨架基本齐全。
- [x] 已有 JWT、refresh token、RBAC helper、幂等校验、FastAPI rate limit 等基础设施。
- [x] 前端主路径已迁移到 `/v1/*`：`/platform` 使用 `/v1/workspace/*`，`/app` 使用 `/v1/app/*`，`/admin` 使用 `/v1/admin/*`。
- [x] 删除 `/api/*` bridge 后再视为 API 对齐完成。
- [ ] 对齐 `sj.md` 的分页、筛选、错误码、健康检查路径和接口语义。
- [ ] 将当前 `office` / `worker` / `supervisor` 角色体系迁移到 `sj.md` 的角色层级和 scope 模型。当前已完成 canonical role/scopes 派生、public/admin guard 对 canonical role 的兼容判断，以及 `/platform` 主 UI 按 scopes 控权；数据库持久角色与全域业务权限仍待继续收口。
- [x] 已补齐客户端 `customer` / `customer_viewer` 登录、授权与只读边界，`/v1/app` 提供 bootstrap、orders、profile、credit、notifications 与客户自助下单路径。

## 第十章 高并发保障

- [x] `/v1/orders` 已有 FastAPI 层限流和幂等校验。现状：`/v1/orders`、`/v1/workspace` 与 `/v1/app` 的正式写路径都已接入 `Idempotency-Key` 校验，并对缺失 header 的写请求补了拒绝回归测试。
- [ ] 落地 Nginx + FastAPI + 业务层三级限流，并覆盖真实下单主路径。
- [x] 落地 Redis Lua 库存预扣减，补上高并发下单设计中的关键原子步骤。
- [ ] 增加客户维度下单频控和限额保护。
- [ ] 把 load test 从健康检查扩展到真实下单热路径；当前 `tests/load/locustfile.py` 已支持可选的 `/v1/workspace` 登录、订单列表、创建并取消订单热路径，并可在 manager/admin 账号下通过 `LOCUST_WORKSPACE_FULL_LIFECYCLE` 跑完整订单生命周期；同时已新增 10 分钟稳定 baseline 命令、场景权重控制，以及 CSV/HTML/summary 归档出口，并已在本机对 `http://localhost:18000` 用 `supervisor@glass.local` 跑过两次 10 分钟 authenticated baseline，最新结果固化在 `reports/load/baseline-real-20260410-221813.*`，为 8729 requests、peak 30.5 req/s、aggregated p95 20s、`GET /v1/workspace/orders` p95 1.8s、error rate 0.02%（2 次 `RemoteDisconnected`）；订单创建链路的业务 `409` 冲突已清零，但写路径长尾和极少量连接中断仍未完全消除，因此稳定性与指标仍未达标。
- [ ] 记录并验证 5000 TPS 目标下的池化、延迟、错误率和回滚行为。

## 第十一章 可观测性

- [x] 已有 metrics、tracing、runtime probe 模块和运行时接口。
- [ ] 补齐 Prometheus 告警规则、SLO/SLA 指标和 worker 业务告警。
- [ ] 让 runtime alerts、admin analytics 接入真实监控/告警/分析数据，而不是停留在基础聚合。
- [ ] 为下单、排产、库存、通知、分析链路补齐 trace 和业务指标。

## 第十二章 安全设计

- [x] 已有 JWT auth、refresh、session cache、file-backed secrets、幂等、RBAC、rate limit 基础设施。
- [ ] 对齐 `sj.md` 的角色层级与 scope 体系。当前已 live 验证 `office -> operator`、`worker -> operator`、`supervisor -> manager` 的 canonical bridge 与 scope 派生。
- [x] 已建立客户端 customer 登录、授权、只读角色和访问边界，并已 live 验证 `customer_viewer` 无法创建订单。
- [ ] 对上传文件、对象存储、SMTP、后台管理接口做一次权限和密钥安全审计。

## 第十三章 测试策略

- [x] 已有 `tests/unit`、`tests/integration`、`tests/contract`、`tests/e2e`、`tests/load` 目录和 QA workflow。
- [x] 当前已有一批关键回归测试通过。现状：已覆盖 `/v1/orders` 与 `/v1/workspace/orders` 的创建/改单/录入生产/取消库存闭环，并把 `/v1/orders` 与 `/v1/workspace/orders` 都拉到录入生产、四道工序完成、取货审批/提醒/签名的完整主链路；`/v1/workspace` 与 direct `/v1/logistics` / `/v1/finance` 现已进一步覆盖发货创建、签收、应收创建、回款、退款、重复签收与重复提货签名的正式写路径/异常流，pickup 完成后的物流/财务读链路也已有回归。重复下单幂等不重复预留、缺失幂等 header 拒绝，以及 `/v1/app/orders` 的客户创建、重复提交幂等与 `customer_viewer` 只读边界也已覆盖；`/v1/orders` create/list/detail/timeline/update/cancel/confirm/entered/steps/pickup/approve/signature/drawing upload/drawing download/export、`/v1/orders/{order_id}/pickup/send-email`、`/v1/workspace/orders` create/list/detail/update/cancel/entered/steps/drawing/export、`/v1/workspace/orders/{order_id}/pickup/approve`、`/v1/workspace/orders/{order_id}/pickup/send-email`、`/v1/workspace/orders/{order_id}/pickup/signature`、`/v1/workspace/orders/{order_id}/shipment`、`/v1/workspace/shipments/{shipment_id}/deliver`、`/v1/workspace/orders/{order_id}/receivable`、`/v1/workspace/receivables/{receivable_id}/payments`、`/v1/workspace/receivables/{receivable_id}/refunds`、`/v1/customers` list、`/v1/workspace/customers` read/create/update、`/v1/workspace/settings/glass-types` read/create/update、`/v1/workspace/settings/notification-templates/{template_key}` read/update、`/v1/workspace/email-logs`、`/v1/app/orders`、`/v1/app/orders/{order_id}`、`/v1/app/credit`、`/v1/app/notifications`、`/v1/app/notifications/read`、`/v1/auth`、`/v1/inventory`、`/v1/workspace/auth/login`、`/v1/workspace/me`、`/v1/workspace/bootstrap`、`/v1/workspace/shipments`、`/v1/workspace/receivables`、`/v1/app/bootstrap`、`/v1/health`、`/v1/logistics/shipments`、`/v1/logistics/tracking/{no}`、`/v1/finance/receivables`、`/v1/finance/invoices`、`/v1/finance/statements`、customers、notifications、workspace settings/notifications、finance/workspace finance 的关键 settlement error envelope，以及 admin health live/ready、runtime probe/health/alerts、users/operators/acceptance/audit 与 `/v1/admin/audit` alias 的关键 success/error envelope 也已纳入 response-level contract；`inventory_sync` worker 与 `RedisInventoryReservationStore` 也已补单测。本机最新全量验证为 `146 passed, 4 skipped, 1 warning`。
- [ ] 将 unit 覆盖率提升到 `sj.md` 目标，重点补齐状态机、排产、价格、事件逻辑测试。
- [ ] 将 integration test 提升到 DB + Redis + service 的真实交互覆盖。现状：除现有 harness integration 外，已新增 opt-in 的真实 Postgres + Redis integration 基座，并已覆盖真实并发预留、rollback restore，以及 `OrdersService` create/cancel 主路径；更广域的 service/HTTP 正式 infra 覆盖仍待继续。
- [ ] 将 contract test 扩展到全部 Public/Admin API，而不是只覆盖部分端点。现状：已把 Public contract 扩到 `/v1/workspace` 生命周期、物流/财务正式写接口、客户/设置/通知等正式暴露面，并新增 `/v1/orders` create/list/detail/timeline/update/cancel/confirm/entered/steps/pickup/approve/signature/drawing upload/drawing download/export、`/v1/orders/{order_id}/pickup/send-email`、`/v1/workspace/orders` create/list/detail/update/cancel/entered/steps/drawing/export、`/v1/workspace/orders/{order_id}/pickup/approve`、`/v1/workspace/orders/{order_id}/pickup/send-email`、`/v1/workspace/orders/{order_id}/pickup/signature`、`/v1/workspace/orders/{order_id}/shipment`、`/v1/workspace/shipments/{shipment_id}/deliver`、`/v1/workspace/orders/{order_id}/receivable`、`/v1/workspace/receivables/{receivable_id}/payments`、`/v1/workspace/receivables/{receivable_id}/refunds`、`/v1/customers` list、`/v1/workspace/customers` read/create/update、`/v1/workspace/settings/glass-types` read/create/update、`/v1/workspace/settings/notification-templates/{template_key}` read/update、`/v1/workspace/email-logs`、`/v1/app/orders` create 主路径，以及 `/v1/app/orders/{order_id}`、`/v1/app/notifications/read`、`/v1/workspace/shipments`、`/v1/workspace/receivables`，以及物流写接口、财务回款/退款语义、结算异常语义、finance/workspace finance 写接口缺失幂等键与 not-found 错误语义、`/v1/search`、`/v1/production/work-orders`、`/v1/production/schedule`、`/v1/auth`、`/v1/inventory`、`/v1/workspace/auth/login`、`/v1/workspace/me`、`/v1/workspace/bootstrap`、`/v1/app/bootstrap`、`/v1/app/credit`、`/v1/app/notifications`、`/v1/health`、`/v1/logistics/shipments`、`/v1/logistics/tracking/{no}`、`/v1/finance/receivables`、`/v1/finance/statements`、`/v1/finance/invoices`、customers、notifications、workspace settings/notifications 与 admin users 的 response-level contract；Admin contract 也已扩到 health live/ready、operators、acceptance、audit logs 与 `/v1/admin/audit` alias、runtime probe/health/alerts、analytics、tasks、production lines、production schedule 成功/异常响应，以及 `/v1/admin/users/bulk` 的 success/error 语义等已上线路由，但仍未覆盖全部端点的逐响应语义。
- [ ] 将 E2E 扩展到完整链路：下单 -> 排产 -> 发货 -> 结算。现状：`/v1/workspace` 与 direct `/v1/logistics` / `/v1/finance` 已覆盖下单、排产工序、取货审批、发货创建/签收、应收创建、部分回款、全额回款、退款、超额回款拒绝、超额退款拒绝以及重复签收/重复提货签名等关键异常流；更完整 settlement 审计、撤销语义和跨域事件闭环仍待继续。
- [ ] 将 load test 扩展到真实下单链路并稳定压测 10 分钟。现状：已新增强制 workspace 登录热路径的 10 分钟 baseline 命令、可调场景权重，以及 CSV/HTML/summary 报告导出；并已完成最新一轮真实 10 分钟 run，结果固化在 `reports/load/baseline-real-20260410-221813.*`，当前 aggregated p95 为 20s、业务 `409` 冲突已清零、错误率降到 0.02%（2 次 `RemoteDisconnected`），`GET /v1/workspace/orders` p95 也已从先前的 71s 级长尾降到 1.8s，但写路径的极端长尾与偶发连接中断仍需继续优化。
- [ ] 让 CI 与 `sj.md` 的 lint + qa-ci + 负载导入校验要求一致。

## 第十四章 部署方案

- [x] 已有 Dockerfile、Docker Compose、Makefile、Nginx、PgBouncer、Kafka、ClickHouse、MinIO、runbooks。
- [ ] 核对并补齐 `make ops-stack-up`、端口、文档入口与 `sj.md` 的一致性。
- [ ] 补齐 `ops/k8s/base/` 的 baseline manifests；当前为空目录。
- [ ] 为 Public API、Admin API、Scheduler、Workers 明确健康检查和启动顺序。

## 第十五章 开发规范

- [ ] 从现在开始，所有新功能必须按 `sj.md` 第 15 章 checklist 落地：domain + model + router + migration + tests + docs 一起提交。
- [ ] 所有新增跨域能力必须同步补 `topics.py`、Outbox 发布、subscriber 和回归测试。
- [ ] 所有新读路径必须先给出 TTL、缓存刷新和失效策略，不能后补。
- [ ] 将 branch strategy / review gate 固化到实际协作流程中，而不是只写在文档里。

## 第十六章 性能优化 Checklist

- [x] 已落地部分基础优化：PgBouncer 友好 session、after-commit hooks、outbox skeleton、file-backed secrets。
- [ ] 把 `sj.md` 第 16 章的额外优化点逐项编码落地并验证。
- [ ] 将常见陷阱转成自动化测试、静态检查或代码审查规则，避免回归。

## 第一批执行顺序（必须先做）

- [x] P0.1 前端三端拆分：独立 `/app`、`/platform`、`/admin` 前端壳，先切清职责边界。
- [x] P0.2 前端 API 迁移：把平台端主路径从 `/api/*` 切到 `/v1/workspace/*`，并补齐 `/v1/app/*` 与 `/v1/admin/*` 前端入口。
- [x] P0.3 兼容层退场：`/v1/app` 与 `/v1/workspace` 已脱离 legacy helper，公共 API 已停止挂载 `/api/*`，未再暴露的 compatibility router/service/wrapper 也已删除，业务 API 对外统一收口到 `/v1/*`。
- [ ] P0.4 身份模型对齐：补 `customer` / `customer_viewer` 体系，清理 `office` / `worker` / `supervisor` 对客户端的侵入。当前已完成客户只读边界、canonical role/scopes bridge、`/platform` 基于 scopes 的主路径权限切换、`/v1/auth` + `/v1/app` + `/v1/workspace` live user payload 的 canonical role 化、dev demo users 持久角色收口，以及 `/v1/orders` 工序动作与 `/v1/admin/users` stage 维护对 canonical operator 的兼容。
- [ ] P0.5 库存并发重做：当前已完成 Redis Lua 预扣减/确认/回滚、reservation ledger、订单创建/确认/取消/录入生产/改单数量的库存闭环，以及幂等/超时回滚的一批回归；`RedisInventoryReservationStore` 的 store 级语义回归也已补上，并已补真实 Postgres + Redis 基础设施专项测试，覆盖真实并发预留、rollback restore，以及 `OrdersService` create/cancel 正式主路径，但更高压力竞争与更多正式路径专项测试仍待补齐。
- [ ] P0.6 测试与压测补齐：当前已把 `/v1/orders`、`/v1/workspace/orders`、`/v1/app/orders` 的关键真实下单链路拉进 integration / e2e，并补了 `/v1/orders` 与 `/v1/workspace/orders` 从录入生产、四道工序完成到取货签收，再到发货/签收/应收/部分回款/全额回款/退款的正式生命周期回归；pickup 后的物流/财务读接口也已纳入 e2e，Public contract 也已把 `/v1/orders` create/list/detail/timeline/update/cancel/confirm/entered/steps/pickup/approve/signature/drawing upload/drawing download/export、`/v1/orders/{order_id}/pickup/send-email`、`/v1/workspace/orders` create/list/detail/update/cancel/entered/steps/drawing/export、`/v1/workspace/orders/{order_id}/pickup/approve`、`/v1/workspace/orders/{order_id}/pickup/send-email`、`/v1/workspace/orders/{order_id}/pickup/signature`、`/v1/workspace/orders/{order_id}/shipment`、`/v1/workspace/shipments/{shipment_id}/deliver`、`/v1/workspace/orders/{order_id}/receivable`、`/v1/workspace/receivables/{receivable_id}/payments`、`/v1/workspace/receivables/{receivable_id}/refunds`、`/v1/customers` list、`/v1/workspace/customers` read/create/update、`/v1/workspace/settings/glass-types` read/create/update、`/v1/workspace/settings/notification-templates/{template_key}` read/update、`/v1/workspace/email-logs`、`/v1/app/orders`、`/v1/app/orders/{order_id}`、`/v1/app/credit`、`/v1/app/notifications`、`/v1/app/notifications/read`、`/v1/auth`、`/v1/inventory`、`/v1/workspace/auth/login`、`/v1/workspace/me`、`/v1/workspace/bootstrap`、`/v1/workspace/shipments`、`/v1/workspace/receivables`、`/v1/app/bootstrap`、`/v1/health`、`/v1/logistics/shipments`、`/v1/logistics/tracking/{no}`、`/v1/finance/receivables`、`/v1/finance/statements`、`/v1/finance/invoices`、物流写接口、财务回款/退款语义、结算异常语义，以及 `search` / `production` 读接口和 customers/notifications/settings/users 推进到 response-level 校验，Admin contract 也进一步覆盖了 health live/ready、runtime probe/health/alerts、users/operators/acceptance/audit/analytics/tasks/production lines、production schedule 成功/异常响应、`/v1/admin/users/bulk` success/error 与 `/v1/admin/audit` alias 的响应语义，load 脚本也已支持 manager/admin 账号下的可选完整生命周期热路径，并新增 10 分钟 baseline 报告命令、可调场景权重与 summary 归档模板；本机已完成最新一轮 10 分钟 authenticated baseline（`reports/load/baseline-real-20260410-221813.*`），订单创建业务冲突已修复、读路径长尾明显下降，但仍残留 2 次连接级 `RemoteDisconnected` 和写路径极端长尾，稳定压测达标结果仍待继续。

## 第二批执行顺序（按依赖重排）

说明：
- 原章节顺序继续保留为范围清单；以下顺序作为真实排期、并行拆分和验收卡点使用。
- 原则：先立执行护栏和权限边界，再收口主业务链路，再让缓存/事件/分析真正产生主路径收益，最后做压测、观测、部署和流程固化。
- `P0.4`、`P0.5`、`P0.6` 仍是最高优先级，但实际推进时按下面依赖拆开执行。

- [ ] S0 执行护栏先落地：从现在开始严格执行第 15 章 checklist；冻结 legacy `backend/` 新功能入口；按 `sj.md` 目录规范继续消化遗留路径；所有新增跨域能力必须同步补 `topics.py` / Outbox / subscriber / 回归测试，所有新读路径必须先定义 TTL、缓存刷新和失效策略。
- [ ] S1 身份与产品面收口（对应 `P0.4`）：完成 `customer` / `customer_viewer` 全权限矩阵；继续把 `office` / `worker` / `supervisor` 持久角色收口到 canonical role/scope；完成 `/app`、`/platform`、`/admin` 三个产品面的职责边界；逐域审计 Router / Service / Repository / 事件分层边界。
- [ ] S2 订单主链路收口：对齐订单状态机与状态迁移约束；当前已收紧主路径状态守卫，补上 entered/production/pickup 关键非法迁移回归，并把物流发货/签收对订单态的 `shipping/delivered` 推进接到正式主路径；客户端真实下单创建也已切到 `/v1/orders`；确认订单域对库存、通知、生产、分析的副作用全部经由事件链路闭环。
- [ ] S3 数据与运行时基础设施接主路径（承接 `P0.5` 剩余）：逐表核对 `sj.md` 的 DDL / 字段 / 索引 / ER 并补 migration；把 inventory sync、缓存读路径、事件回放真正接入库存主路径；将 order/customer/inventory cache 接入正式读路径，并落实 TTL 矩阵、negative cache、互斥重建、随机过期与统一 after-commit 刷新入口。
- [ ] S4 业务域能力面补齐：production 对齐排产 / 工单 / 质检 / 验收 / 任务视图全链路；customers 补齐等级定价、客户中心、生命周期管理；finance 补齐自动对账、发票流转、审核流；logistics 补齐发货计划、异常跟踪；notifications 补齐模板、渠道、事件订阅、送达状态和已读闭环。
- [ ] S5 事件、分析与查询收益收口：为每个跨域事件补齐发布点、订阅处理器和端到端验证；确保跨域流程不是 service 直接串调；让 analytics sink 和下游查询真正使用 ClickHouse / 事件流，而不是继续只查 OLTP。
- [ ] S6 测试与性能达标（对应 `P0.6`）：优先补状态机 / 排产 / 价格 / 事件逻辑的 unit；扩 integration 到 DB + Redis + service 正式交互；补全 Public/Admin contract；把 E2E 拉到“下单 -> 排产 -> 发货 -> 结算”；继续清零压测长尾和 `RemoteDisconnected`，再落 Nginx + FastAPI + 业务层三级限流、客户频控 / 限额保护，并验证 5000 TPS 指标。
- [ ] S7 观测、安全、部署收口：补 Prometheus 告警、SLO / SLA、worker 业务告警；为下单 / 排产 / 库存 / 通知 / 分析链路补 trace 和业务指标；完成上传文件、对象存储、SMTP、后台接口安全审计；核对 `make ops-stack-up`、端口、文档入口和启动顺序；补齐 `ops/k8s/base/` baseline manifests。
- [ ] S8 工程流程固化与回归防线：让 CI 与 `sj.md` 的 lint + qa-ci + 负载导入校验要求一致；将 branch strategy / review gate 固化到实际协作流程；把第 16 章额外优化点逐项编码落地，并将常见陷阱转成自动化测试、静态检查或代码审查规则。
- [ ] S9 回填章节勾选与完成定义：在 `S0` 到 `S8` 完成后，统一回填各章节未勾选项，确认 `/app`、`/platform`、`/admin` 真正成为三个独立产品面，并清零完成定义剩余项。

## 完成定义

以下条件同时满足后，才能把“100% 按 sj.md 开发”从口号改为事实：

- [x] 用户真实主路径已经不依赖 `/api/*` 兼容层。
- [ ] `/app`、`/platform`、`/admin` 已经是三个独立产品面。
- [x] 库存并发链路已经是 Redis Lua + DB + Outbox 的正式实现。
- [ ] 缓存、事件、分析、告警、测试、部署都已按 `sj.md` 接入主路径而不是停留在骨架层。
- [ ] `todo.md` 中所有未勾选项已清零。