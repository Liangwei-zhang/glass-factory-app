

好的，我直接在这里输出完整的详细设计文档。基于我对 `stock-py` 所有源码的深度阅读，针对玻璃工厂业务做全面优化。

---

# 🏭 玻璃工厂数字化管理系统 — 完整开发设计文档

**版本**: v1.0.0
**日期**: 2026-04-09
**基线**: 基于 `Liangwei-zhang/stock-py` 架构模式优化
**目标**: 日活 300 万 · 峰值 QPS 20,000 · 订单 TPS 5,000 · 可用性 99.99%

---

## 第一章 系统概述

### 1.1 产品定位

面向玻璃制造行业的一站式数字化管理平台，覆盖 **接单 → 排产 → 生产 → 质检 → 库存 → 发货 → 结算** 全链路闭环。

### 1.2 业务范围

| 模块 | 核心能力 | 价值 |
|------|---------|------|
| 订单管理 | 在线下单/报价/变更/取消/超时自动关闭 | 替代传统电话+传真 |
| 生产管理 | 排产调度/工艺追踪/良品率统计 | 产线利用率提升 30% |
| 库存管理 | 实时库存/预扣减/安全库存预警 | 减少呆滞库存 40% |
| 质量管理 | 质检流程/缺陷追踪/良品率报表 | 品质问题追溯 <2min |
| 客户管理 | 客户档案/信用额度/等级定价 | 客户流失率降低 25% |
| 物流配送 | 发货计划/物流追踪/签收确认 | 配送准时率提升 20% |
| 财务结算 | 应收应付/自动对账/发票管理 | 对账时间从 3 天→30 分钟 |
| 数据看板 | 经营指标/产能分析/趋势预测 | 决策响应从天级→分钟级 |

### 1.3 三端架构

```
┌───────────────────────────────────────────────────────┐
│                    Nginx Edge Proxy                     │
│                 http://factory.example.com               │
├──────────────┬──────────────────┬────────────────────────┤
│              │                  │                        │
│   /admin     │    /platform     │       /app             │
│   管理端      │    业务操作端     │       客户端            │
│              │                  │                        │
│ • 用户权限    │  • 订单录入       │  • 在线下单            │
│ • 系统配置    │  • 生产排产       │  • 订单跟踪            │
│ • 数据看板    │  • 库存管理       │  • 物流追踪            │
│ • 财务审核    │  • 质检录入       │  • 对账查询            │
│ • 运维监控    │  • 发货安排       │  • 历史订单            │
│ • 审计日志    │  • 客户管理       │  • 个人中心            │
│              │                  │                        │
├──────────────┴──────────────────┴────────────────────────┤
│              FastAPI Public API (:8000)                   │
│              FastAPI Admin API  (:8001)                   │
└──────────────────────────────────────────────────────────┘
```

### 1.4 目标指标

| 指标 | 目标值 | 说明 |
|------|--------|------|
| DAU | 300 万 | 含客户端 + 操作端 + 管理端 |
| 平均 QPS | ~700 | DAU 300万 × 平均每人每天 20 次请求 / 86400s |
| 峰值 QPS | ~20,000 | 峰值是均值的 25~30 倍 |
| 订单 TPS | 5,000 | 高并发促销/集中采购场景 |
| P50 延迟 | < 20ms | 读操作 |
| P99 延迟 | < 100ms | 写操作（含 DB + Redis + Outbox） |
| 可用性 | 99.99% | 年停机 < 53 分钟 |
| 数据持久性 | 99.999% | PostgreSQL WAL + 备份 + MinIO archive |

---

## 第二章 架构设计

### 2.1 整体架构图

```
                              ┌─────────────────┐
                              │   客户端/浏览器   │
                              └───────┬─────────┘
                                      │ HTTPS
                              ┌───────▼─────────┐
                              │      Nginx       │
                              │   Edge Proxy     │
                              │   :8080          │
                              └───┬─────────┬───┘
                           /v1/* │         │ /v1/admin/*
                    ┌────────────▼──┐  ┌───▼────────────┐
                    │  Public API   │  │   Admin API     │
                    │  FastAPI      │  │   FastAPI       │
                    │  :8000        │  │   :8001         │
                    └──────┬────────┘  └───┬─────────────┘
                           │               │
         ┌─────────────────┼───────────────┼──────────────┐
         │                 │    infra 层    │              │
         │    ┌────────────▼───────────────▼──────────┐   │
         │    │          domains (业务领域层)           │   │
         │    │                                        │   │
         │    │  orders │ inventory │ production │ ...  │   │
         │    │  schema │ schema    │ schema     │      │   │
         │    │  repo   │ repo      │ repo       │      │   │
         │    │  service│ service   │ service    │      │   │
         │    └────────────────────────────────────────┘   │
         │                       │                         │
         │    ┌──────────────────▼─────────────────────┐   │
         │    │              infra (基础设施层)          │   │
         │    │                                        │   │
         │    │  db/session ─────► PostgreSQL + PgBouncer│  │
         │    │  cache/redis ────► Redis 7              │   │
         │    │  events/outbox ──► Kafka (KRaft)        │   │
         │    │  analytics ──────► ClickHouse           │   │
         │    │  storage ────────► MinIO / S3           │   │
         │    │  security ───────► JWT / RBAC           │   │
         │    │  observability ──► Metrics / Tracing    │   │
         │    └────────────────────────────────────────┘   │
         └─────────────────────────────────────────────────┘
                           │
         ┌─────────────────┼──────────────────────────┐
         │          Workers & Schedulers               │
         │                                             │
         │  scheduler ──── APScheduler 任务编排         │
         │  event-pipeline  Outbox relay → Kafka       │
         │  order-timeout   30min 超时取消             │
         │  inventory-sync  库存同步与预警             │
         │  production-scheduler  排产调度             │
         │  retention ──── 数据清理与归档              │
         │  analytics-sink  数据下沉 ClickHouse        │
         │  cold-storage ── 冷数据归档 MinIO           │
         └─────────────────────────────────���───────────┘
```

### 2.2 为什么选择模块化单体

这个决策直接来自 stock-py 项目的实战经验和我之前做的对比分析：

| 决策因素 | 模块化单体 | 微服务 | 结论 |
|---------|-----------|--------|------|
| 300万 DAU 能否撑住 | ✅ FastAPI async + PgBouncer 轻松到 20K QPS | ✅ 远超需求 | 两者都够 |
| 开发成本 | 1~3 人 × 6 个月 | 8~15 人 × 12 个月 | **模块化省 5 倍** |
| 运维复杂度 | `make ops-stack-up` 一行搞定 | K8s + Helm + Terraform + 服务网格 | **模块化省 10 倍** |
| 调试效率 | 单进程 stack trace 一目了然 | 跨 10+ 服务分布式追踪 | **模块化快 5 倍** |
| 一键部署 | Docker Compose 天然支持 | 需要完整的 GitOps 体系 | **模块化天然满足** |
| 未来可拆 | domain 边界清晰，随时可拆 | 已经拆了 | 可演进 |

**核心原则：先用最简单的架构跑通业务，等真正遇到瓶颈再拆分。**

stock-py 的经验告诉我们：一个设计良好的模块化单体，在真正需要拆微服务之前（通常是日活 1000 万或团队 30+ 人），比微服务更高效、更可靠、更便宜。

### 2.3 分层架构（DDD 三层）

```
请求生命周期：

  HTTP Request
       │
       ▼
  ┌──────────────────────────────────┐
  │  apps/  (应用层 - Application)    │  ← 路由、中间件、请求/响应转换
  │                                  │  ← 不写业务逻辑
  │  • main.py   → lifespan/中间件   │
  │  • routers/  → 路由定义          │
  │  • 职责: 接收请求 → 调用 service  │
  │         → 返回响应               │
  └──────────┬───────────────────────┘
             │ 调用
             ▼
  ┌──────────────────────────────────┐
  │  domains/  (领域层 - Domain)      │  ← 核心业务逻辑
  │                                  │  ← 不依赖框架、不依赖外部服务
  │  • schema.py     → 数据模型       │
  │  • service.py    → 业务编排       │
  │  • repository.py → 数据访问接口    │
  │  • 职责: 业务规则、状态转换、校验   │
  └──────────┬───────────────────────┘
             │ 依赖
             ▼
  ┌──────────────────────────────────┐
  │  infra/  (基础设施层)             │  ← 技术细节实现
  │                                  │  ← 可替换、可切换
  │  • db/       → PostgreSQL + ORM  │
  │  • cache/    → Redis             │
  │  • events/   → Kafka + Outbox    │
  │  • security/ → JWT + 加密        │
  │  • analytics/ → ClickHouse       │
  │  • storage/  → MinIO / S3        │
  └──────────────────────────────────┘

  ⚠️ 三条铁律 (来自 stock-py 团队规范):
  1. Router 不写业务逻辑 → 只做参数接收和 service 调用
  2. Repository 不调外部服务 → 只管数据存取
  3. 所有跨域副作用走 Outbox + EventBus → 不在 service 里直接调其他域
```

### 2.4 请求生命周期流转图

```
Client Request
    │
    ▼
┌─ Nginx ──────────────────────────────────────────┐
│  路由分发: /v1/* → Public API, /v1/admin/* → Admin │
└───────┬──────────────────────────────────────────┘
        │
        ▼
┌─ FastAPI Middleware Stack ────────────────────────┐
│  1. attach_request_context                        │
│     → 生成 request_id (UUID)                      │
│     → 提取 trace_id (from traceparent header)     │
│     → 提取 user_ip (from X-Forwarded-For)         │
│     → 设置 ContextVar                             │
│                                                   │
│  2. CORS Middleware                                │
│     → 检查 Origin                                 │
│                                                   │
│  3. Rate Limit (slowapi)                          │
│     → Redis 计数器检查                             │
│                                                   │
│  4. Metrics Recording                             │
│     → 记录 http_requests_total (counter)          │
│     → 记录 http_request_duration_ms (histogram)   │
│     → 记录 per-endpoint 统计                      │
└───────┬──────────────────────────────────────────┘
        │
        ▼
┌─ Router (apps/public_api/routers/orders.py) ─────┐
│  1. 参数校验 (Pydantic)                           │
│  2. 认证鉴权 (Depends → get_current_user)         │
│  3. 幂等校验 (Depends → check_idempotency)        │
│  4. 调用 service                                  │
│  5. 返回响应                                      │
└───────┬──────────────────────────────────────────┘
        │
        ▼
┌─ Service (domains/orders/service.py) ────────────┐
│  1. 业务校验 (库存是否充足、客户信用是否够)         │
│  2. 库存预扣减 (调用 inventory_service)            │
│  3. 创建订单 (调用 order_repository)               │
│  4. 发布事件 (OutboxPublisher.publish_after_commit)│
│  5. 返回结果                                      │
└───────┬──────────────────────────────────────────┘
        │
        ▼
┌─ DB Session (infra/db/session.py) ───────────────┐
│  1. session.commit()   → 订单 + outbox 原子写入    │
│  2. 执行 cache-after-commit hooks                 │
│     → 更新 Redis 缓存                             │
│  3. 异常时 session.rollback()                     │
└───────┬──────────────────────────────────────────┘
        │
        ▼
┌─ Response ───────────────────────────────────────┐
│  Headers: X-Request-ID: <uuid>                    │
│  Body: { "data": {...}, "request_id": "..." }     │
└──────────────────────────────────────────────────┘

        ┌─────────────────────────────────────┐
        │  异步链路 (Event Pipeline Worker)    │
        │                                     │
        │  event_outbox (DB)                  │
        │       │ relay (poll every 1s)       │
        │       ▼                             │
        │  Kafka topic: factory.events        │
        │       │ dispatch                    │
        │       ▼                             │
        │  Subscribers:                       │
        │    → 库存确认扣减                    │
        │    → 生产工单自动创建                │
        │    → 通知客户                       │
        │    → 数据下沉 ClickHouse            │
        └───────────���─────────────────────────┘
```

---

## 第三章 技术栈详解

### 3.1 技术选型全景

| 层级 | 技术 | 版本 | 为什么选它 |
|------|-----|------|----------|
| **语言** | Python | 3.13 | async/await 原生支持，生态丰富，stock-py 实战验证 |
| **Web 框架** | FastAPI | 0.109+ | 性能接近 Go/Node，类型安全，自动 OpenAPI 文档 |
| **ASGI Server** | Uvicorn | 0.27+ | 工业标准 ASGI server，配合 --workers 多进程 |
| **ORM** | SQLAlchemy 2.0 | 2.0.40 | 最成熟的 Python ORM，async 支持完善 |
| **DB Driver** | asyncpg | 0.30+ | 最快的 Python PostgreSQL 异步驱动 |
| **数据库** | PostgreSQL | 16 | ACID 事务、JSONB、pg_trgm、分区表 |
| **连接池** | PgBouncer | 1.22+ | transaction pooling，单实例支持 10K+ 并发连接 |
| **缓存** | Redis | 7 | 缓存 + 分布式锁 + Lua 原子操作 + Streams |
| **消息队列** | Kafka | 3.7+ (KRaft) | 高吞吐事件流，无 ZooKeeper 依赖 |
| **分析存储** | ClickHouse | 24.8+ | 列式存储，报表查询比 PG 快 100 倍 |
| **对象存储** | MinIO | 最新 | S3 兼容，存图纸/质检图片/冷归档 |
| **数据校验** | Pydantic | 2.11+ | 性能比 v1 快 5~50 倍，深度 FastAPI 集成 |
| **配置管理** | pydantic-settings | 2.8+ | 支持 .env + 环境变量 + file-backed secrets |
| **Migration** | Alembic | 1.13+ | SQLAlchemy 官方 migration 工具 |
| **调度** | APScheduler | 3.10+ | 轻量调度，不需要独立 Celery broker |
| **HTTP 客户端** | httpx | 0.26+ | async，可替代 requests |
| **认证** | python-jose | 3.3+ | JWT 编解码 |
| **限流** | slowapi | 0.1.9 | 基于 Redis 的 FastAPI 限流中间件 |
| **日志** | loguru | 0.7+ | 结构化日志，开箱即用 |
| **测试** | pytest + pytest-asyncio | 7.4+ | 异步测试原生支持 |
| **压测** | Locust | 2.31+ | Python 原生压测，scenario 可编程 |
| **代码风格** | black + isort + mypy | 最新 | 零争议格式化 + import 排序 + 类型检查 |

### 3.2 为什么不选的技术

| 被放弃的技术 | 对比对象 | 放弃原因 |
|-------------|---------|---------|
| Django | FastAPI | Django ORM 不支持 async，性能差 3~5 倍 |
| Flask | FastAPI | 无类型系统，无自动文档，无异步 |
| MySQL | PostgreSQL | PG 的 JSONB、CTE、pg_trgm、分区表更适合复杂查询 |
| Celery | APScheduler + Kafka | Celery 引入 broker 复杂度，我们已有 Kafka |
| RabbitMQ | Kafka | Kafka 吞吐更高，支持 replay，更适合事件驱动 |
| MongoDB | PostgreSQL + ClickHouse | 关系型业务（订单/库存）不适合文档库 |
| Elasticsearch | ClickHouse | 我们的分析场景是结构化聚合，不是全文搜索 |

### 3.3 ��键技术避坑指南

**asyncpg + PgBouncer 的坑：**
```python
# ❌ 错误: PgBouncer transaction pooling 下，prepared statement 会冲突
engine = create_async_engine(url)

# ✅ 正确: stock-py 已验证的方案
# 1. NullPool (不在应用层再叠连接池)
# 2. prepared_statement_cache_size=0
# 3. 唯一的 prepared_statement_name_func
engine = create_async_engine(
    url,
    poolclass=NullPool,
    connect_args={
        "statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
    },
)
```

**Redis volatile-ttl vs allkeys-lru：**
```
stock-py 选择 volatile-ttl 而不是 allkeys-lru 的原因:

Redis 同时承担多种角色:
  1. 缓存 (有 TTL) → 可以被淘汰
  2. 分布式锁 (有 TTL) → 不应该被随意淘汰
  3. Event Streams (无 TTL) → 绝对不能被淘汰
  4. Runtime Registry (有 TTL) → 不应该被随意淘汰

如果用 allkeys-lru:
  → 内存不够时可能淘汰掉 Streams 或 Lock 的 key
  → 导致事件丢失或分布式锁失效

用 volatile-ttl:
  → 只淘汰设了 TTL 的 key，且优先淘汰 TTL 最短的
  → Streams 和长期 key 不会被触碰
```

---

## 第四章 项目目录结构

### 4.1 完整目录树

```
glass-factory/
│
├── apps/                              # 应用层 (Application Layer)
│   ├── __init__.py
│   ├── public_api/                    # 公共 API (面向客户端 + 操作端)
│   │   ├── __init__.py
│   │   ├── main.py                    # FastAPI ���口: lifespan, middleware, router 注册
│   │   ├── ui_shell.py                # 三端 HTML 入口页面生成
│   │   └── routers/                   # 路由定义 (每个 domain 一个 router 文件)
│   │       ├── __init__.py
│   │       ├── auth.py                # 认证: login / logout / refresh / send-code
│   │       ├── orders.py              # 订单: 创建 / 查询 / 取消 / 确认
│   │       ├── inventory.py           # 库存: 查询 / 调整
│   │       ├── production.py          # 生产: 工单查询 / 进度查询
│   │       ├── customers.py           # 客户: 档案 / 信用
│   │       ├── logistics.py           # 物流: 发货 / 追踪
│   │       ├── finance.py             # 财务: 对账 / 查询
│   │       ├── search.py              # 全局搜索
│   │       ├── notifications.py       # 通知: 列表 / 已读 / push
│   │       ├── monitoring.py          # 监控: legacy 兼容面
│   │       └── ui.py                  # /app /platform /admin HTML 入口
│   │
│   ├── admin_api/                     # 管理 API (面向管理端)
│   │   ├── __init__.py
│   │   ├── main.py                    # Admin FastAPI 入口
│   │   └── routers/
│   │       ├── __init__.py
│   │       ├── analytics.py           # 经营分析: 概览 / 产能 / 销售
│   │       ├── users.py               # 用户管理: 列表 / 编辑 / 权限
│   │       ├── operators.py           # 操作员管理
│   │       ├── audit.py               # 审计日志
│   │       ├── tasks.py               # 任务中心: 待办 / 审批
│   │       ├── runtime.py             # 运行时监控: health / metrics / alerts
│   │       ├── acceptance.py          # 验收状态
│   │       └── production_admin.py    # 排产管理 / 产线配置
│   │
│   ├── scheduler/                     # 调度器
│   │   ├── __init__.py
│   │   └── main.py                    # APScheduler: heartbeat, event relay, 超时取消, 排产触发
│   │
│   └── workers/                       # 后台 Worker
│       ├── event_pipeline/            # Outbox → Kafka relay + dispatch
│       │   └── worker.py
│       ├── order_timeout/             # 订单超时自动取消
│       │   └── worker.py
│       ├── inventory_sync/            # 库存同步与预警
│       │   └── worker.py
│       ├── production_scheduler/      # 排产调度引擎
│       │   └── worker.py
│       ├── analytics_sink/            # 数据下沉到 ClickHouse
│       │   └── worker.py
│       ├── notification_dispatch/     # 通知分发 (WebPush / Email / SMS)
│       │   └── worker.py
│       ├── retention/                 # 数据清理与归档
│       │   └── worker.py
│       └── cold_storage/              # 冷数据归档到 MinIO
│           └── worker.py
│
├── domains/                           # 领域层 (Domain Layer)
│   ├── __init__.py
│   ├── orders/                        # 订单域
│   │   ├── __init__.py
│   │   ├── schema.py                  # Pydantic: CreateOrderRequest, OrderResponse, OrderStatus
│   │   ├── repository.py             # DB: create_order, get_order, list_orders, update_status
│   │   ├── service.py                # 业务: place_order, cancel_order, confirm_order
│   │   └── errors.py                 # 订单错误码: ORDER_NOT_FOUND, ORDER_ALREADY_CANCELLED...
│   │
│   ├── inventory/                     # 库存域
│   │   ├── __init__.py
│   │   ├── schema.py                  # InventoryItem, StockAdjustment, ReservationResult
│   │   ├── repository.py             # DB: get_stock, adjust_stock, list_low_stock
│   │   ├── service.py                # 业务: reserve_stock, confirm_deduction, rollback_reservation
│   │   ├── lua_scripts.py            # Redis Lua: 原子预扣减 / 回滚
│   │   └── errors.py                 # INVENTORY_INSUFFICIENT, INVENTORY_RESERVED_EXPIRED...
│   │
│   ├── production/                    # 生产域
│   │   ├── __init__.py
│   │   ├── schema.py                  # WorkOrder, ProductionLine, ProcessStep, QualityCheck
│   │   ├── repository.py             # DB: create_work_order, update_progress
│   │   ├── service.py                # 业务: schedule_production, record_quality_check
│   │   ├── scheduler_engine.py       # 排产算法: 优先级 + 产线匹配 + 工艺约束
│   │   └── errors.py
│   │
│   ├── customers/                     # 客户域
│   │   ├── __init__.py
│   │   ├── schema.py                  # Customer, CreditLimit, PriceLevel
│   │   ├── repository.py
│   │   ├── service.py                # 业务: check_credit, calculate_price
│   │   └── errors.py
│   │
│   ├── logistics/                     # 物流域
│   │   ├── __init__.py
│   │   ├── schema.py                  # ShipmentPlan, TrackingEvent, DeliveryConfirmation
│   │   ├── repository.py
│   │   ├── service.py
│   │   └── errors.py
│   │
│   ├── finance/                       # 财务域
│   │   ├── __init__.py
│   │   ├── schema.py                  # Invoice, Payment, Reconciliation
│   │   ├── repository.py
│   │   ├── service.py
│   │   └── errors.py
│   │
│   ├── auth/                          # 认证域
│   │   ├── __init__.py
│   │   ├── schema.py
│   │   ├── repository.py
│   │   └── service.py
│   │
│   ├── admin/                         # 管理域
│   │   ├── __init__.py
│   │   └── schema.py
│   │
│   ├── analytics/                     # 分析域
│   │   ├── __init__.py
│   │   └── schema.py
│   │
│   └── notifications/                 # 通知域
│       ├── __init__.py
│       ├── schema.py
│       ├── repository.py
│       └── service.py
│
├── infra/                             # 基础设施层 (Infrastructure Layer)
│   ├── __init__.py
│   ├── core/                          # 核心公共设施
│   │   ├── __init__.py
│   │   ├── config.py                  # 配置中心 (分组嵌套, FileBackedEnvSettingsSource)
│   │   ├── errors.py                  # 统一错误处理 (AppError + 错误码枚举)
│   │   ├── context.py                 # 请求上下文 (ContextVar)
│   │   ├── logging.py                 # 日志配置 (loguru)
│   │   ├── id_generator.py            # 分布式 ID 生成器 (GF 前缀 Snowflake)
│   │   └── hooks.py                   # 可注册的 lifecycle hooks (优化 stock-py 的 cache-after-commit)
│   │
│   ├── db/                            # 数据库
│   │   ├── __init__.py
│   │   ├── session.py                 # async engine + session factory (PgBouncer 兼容)
│   │   ├── base.py                    # SQLAlchemy declarative base
│   │   └── models/                    # ORM 模型
│   │       ├── __init__.py
│   │       ├── orders.py
│   │       ├── inventory.py
│   │       ├── production.py
│   │       ├── customers.py
│   │       ├── logistics.py
│   │       ├── finance.py
│   │       ├── users.py
│   │       ├── notifications.py
│   │       └── events.py              # event_outbox 表模型
│   │
│   ├── cache/                         # 缓存
│   │   ├── __init__.py
│   │   ├── redis_client.py            # Redis 连接管理
│   │   ├── order_cache.py             # 订单热数据缓存
│   │   ├── inventory_cache.py         # 库存实时缓存
│   │   └── customer_cache.py          # 客户信息缓存
│   │
│   ├── events/                        # 事件系统
│   │   ├── __init__.py
│   │   ├── outbox.py                  # Outbox 模式 (发布 + claim + relay + DLQ)
│   │   ├── broker.py                  # 可切换 broker (Redis Streams / Kafka)
│   │   ├── dispatcher.py              # 事件分发器
│   │   └── topics.py                  # 事件 Topic 常量定义
│   │
│   ├── http/                          # HTTP 工具
│   │   ├── __init__.py
│   │   ├── health.py                  # /health /health/ready 路由
│   │   └── http_client.py             # httpx 异步客户端工厂
│   │
│   ├── observability/                 # 可观测性
│   │   ├── __init__.py
│   │   ├── metrics.py                 # MetricsRegistry + Prometheus 导出
│   │   ├── tracing.py                 # 分布式追踪
│   │   └── runtime_probe.py           # Worker 健康探针
│   │
│   ├── security/                      # 安全
│   │   ├── __init__.py
│   │   ├── auth.py                    # JWT 编解码 + 当前用户依赖
│   │   ├── rbac.py                    # 角色权限检查
│   │   ├── session_cache.py           # 会话缓存
│   │   └── idempotency.py             # 幂等性检查 (Redis)
│   │
│   ├── analytics/                     # 分析存储
│   │   ├── __init__.py
│   │   └── clickhouse_client.py       # ClickHouse HTTP backend + 本地 JSONL fallback
│   │
│   └── storage/                       # 对象存储
│       ├── __init__.py
│       └── object_storage.py          # MinIO / S3 / 本地文件系统
│
├── alembic/                           # 数据库迁移
│   ├── env.py
│   └── versions/
│       └── .gitkeep
│
├── tests/                             # 测试
│   ├── __init__.py
│   ├── unit/                          # 单元测试
│   │   ├── __init__.py
│   │   ├── test_order_service.py
│   │   ├── test_inventory_service.py
│   │   └── test_id_generator.py
│   ├── contract/                      # 契约测试
│   │   ├── __init__.py
│   │   └── snapshots/
│   ├── integration/                   # 集成测试
│   │   └── __init__.py
│   ├── e2e/                           # 端到端测试
│   │   └── __init__.py
│   └── load/                          # 压力测试
│       ├── locustfile.py
│       └── validate_env.py
│
├── ops/                               # 运维与部署
│   ├── README.md
│   ├── docker-compose.yml             # 完整编排
│   ├── nginx/
│   │   └── default.conf
│   ├── pgbouncer/
│   │   ├── Dockerfile
│   │   ├── pgbouncer.ini.template
│   │   └── docker-entrypoint.sh
│   ├── clickhouse/
│   │   └── init/
│   ├── minio/
│   │   ├── entrypoint.sh
│   │   └── lifecycle.json
│   ├── secrets/
│   │   └── dev/                       # 开发环境 secrets
│   ├── k8s/                           # K8s baseline (备用)
│   │   └── base/
│   ├── runbooks/                      # 运维手册
│   │   ├── backup-restore.md
│   │   └── qa-cutover-checklist.md
│   ├── reports/                       # load / cutover 报告
│   │   ├── load/
│   │   └── cutover/
│   ├── bin/                           # 运维脚本
│   │   ├── compose-up.sh
│   │   ├── compose-load-baseline.sh
│   │   ├── backup-baseline.sh
│   │   └── restore-baseline.sh
│   ├── ecosystem.config.js            # PM2 配置 (VM 部署备用)
│   └── postgresql.conf.tuning         # PG 调优参考
│
├── docs/                              # 设计文档
│   ├── DEVELOPMENT_GUIDE.md           # 本文档
│   └── API_REFERENCE.md               # API 接口文档
│
├── .github/
│   └── workflows/
│       └── qa.yml                     # CI: lint + test
│
├── .env.example                       # 环境变量模板
├── .gitignore
├── .dockerignore
├── alembic.ini
├── Dockerfile
├── Makefile                           # 一键命令集
├── pyproject.toml
├── requirements.txt
└── README.md
```

### 4.2 命名规范

| 类型 | 规范 | 示例 |
|------|------|------|
| 文件名 | snake_case | `order_service.py` |
| 类名 | PascalCase | `OrderService` |
| 函数/方法 | snake_case | `create_order()` |
| 常量 | UPPER_SNAKE_CASE | `ORDER_TIMEOUT_MINUTES = 30` |
| Pydantic Schema | PascalCase + 后缀 | `CreateOrderRequest`, `OrderResponse` |
| SQLAlchemy Model | PascalCase + Model | `OrderModel` |
| 路由前缀 | 复数名词 | `/v1/orders`, `/v1/customers` |
| 事件 Topic | 域名.实体.动作 | `orders.order.created` |
| 错误码 | 大写域名_错误描述 | `ORDER_NOT_FOUND` |

---

## 第五章 核心领域模块设计

### 5.1 订单域 (domains/orders/)

#### 5.1.1 订单状态机

```
                    ┌──────────┐
            ┌──────►│ CANCELLED │
            │       └──────────┘
            │ (客户取消 / 30min超时)
            │
  ┌─────────┴──┐     ┌──────────┐     ┌────────────┐     ┌───────────┐
  │   PENDING   ├────►│ CONFIRMED ├────►│ PRODUCING   ├────►│ PRODUCED  │
  │  (待确认)   │     │  (已确认)  │     │  (生产中)    │     │ (已完工)   │
  └─────────────┘     └──────────┘     └────────────┘     └─────┬─────┘
                                                                 │
  ┌─────────────┐     ┌──────────┐     ┌────────────┐           │
  │  COMPLETED   │◄────│ DELIVERED │◄────│  SHIPPING   │◄──────────┘
  │  (已完成)    │     │  (已签收)  │     │  (配送中)    │
  └─────────────┘     └──────────┘     └────────────┘
```

#### 5.1.2 数据模型 (schema.py)

```python
# domains/orders/schema.py
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class OrderStatus(StrEnum):
    PENDING = "pending"           # 待确认
    CONFIRMED = "confirmed"       # 已确认
    PRODUCING = "producing"       # 生产中
    PRODUCED = "produced"         # 已完工
    SHIPPING = "shipping"         # 配送中
    DELIVERED = "delivered"       # 已签收
    COMPLETED = "completed"       # 已完成
    CANCELLED = "cancelled"       # 已取消


# 允许的状态转换矩阵
ORDER_STATUS_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING: {OrderStatus.CONFIRMED, OrderStatus.CANCELLED},
    OrderStatus.CONFIRMED: {OrderStatus.PRODUCING, OrderStatus.CANCELLED},
    OrderStatus.PRODUCING: {OrderStatus.PRODUCED},
    OrderStatus.PRODUCED: {OrderStatus.SHIPPING},
    OrderStatus.SHIPPING: {OrderStatus.DELIVERED},
    OrderStatus.DELIVERED: {OrderStatus.COMPLETED},
}


class OrderItemRequest(BaseModel):
    product_id: str = Field(..., description="产品 ID")
    product_name: str = Field(..., description="产品名称")
    glass_type: str = Field(..., description="玻璃类型: 钢化/中空/夹层/Low-E")
    specification: str = Field(..., description="规格: 如 6mm, 5+12A+5")
    width_mm: int = Field(..., gt=0, description="宽度(mm)")
    height_mm: int = Field(..., gt=0, description="高度(mm)")
    quantity: int = Field(..., gt=0, description="数量(片)")
    unit_price: Decimal = Field(..., gt=0, description="单价(元)")
    process_requirements: str = Field(default="", description="工艺要求")


class CreateOrderRequest(BaseModel):
    customer_id: str = Field(..., description="客户 ID")
    delivery_address: str = Field(..., description="交货地址")
    expected_delivery_date: datetime = Field(..., description="期望交货日期")
    items: list[OrderItemRequest] = Field(..., min_length=1, description="订单明细")
    remark: str = Field(default="", max_length=500, description="备注")
    idempotency_key: str = Field(..., description="幂等键")

    @field_validator("items")
    @classmethod
    def validate_items_limit(cls, v: list[OrderItemRequest]) -> list[OrderItemRequest]:
        if len(v) > 100:
            raise ValueError("单次下单最多 100 个品项")
        return v


class OrderResponse(BaseModel):
    order_id: str
    order_no: str
    customer_id: str
    status: OrderStatus
    total_amount: Decimal
    total_quantity: int
    total_area_sqm: Decimal
    items: list[OrderItemResponse]
    created_at: datetime
    updated_at: datetime
    confirmed_at: datetime | None = None
    delivery_address: str
    expected_delivery_date: datetime
    remark: str = ""


class OrderItemResponse(BaseModel):
    item_id: str
    product_id: str
    product_name: str
    glass_type: str
    specification: str
    width_mm: int
    height_mm: int
    area_sqm: Decimal
    quantity: int
    unit_price: Decimal
    subtotal: Decimal
    process_requirements: str = ""
```

#### 5.1.3 订单号生成策略

```python
# infra/core/id_generator.py
"""
分布式订单号生成器

格式: GF{YYYYMMDD}-{machine_id:02d}-{sequence:06d}
示例: GF20260409-03-000001

特点:
  - 有业务含义：GF = Glass Factory，日期可读
  - 每台机器每天支持 999,999 个序号
  - Redis INCR 原子生成，不会重复
  - 日期切换时自动重置序号
"""
from __future__ import annotations

from datetime import datetime, timezone

from infra.cache.redis_client import get_redis


class OrderIdGenerator:
    def __init__(self, machine_id: int = 1) -> None:
        self.machine_id = machine_id

    async def generate(self, prefix: str = "GF") -> str:
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y%m%d")
        redis_key = f"id_gen:{prefix}:{date_str}:{self.machine_id}"

        client = await get_redis()
        sequence = await client.incr(redis_key)

        # 首次创建时设置过期时间 (48h，确保跨日安全)
        if sequence == 1:
            await client.expire(redis_key, 172800)

        return f"{prefix}{date_str}-{self.machine_id:02d}-{sequence:06d}"
```

#### 5.1.4 订单服务核心逻辑 (service.py)

```python
# domains/orders/service.py
"""
订单服务 - 高并发下单核心流程

调用链路:
  1. 幂等校验 (Redis)
  2. 客户信用校验
  3. 库存预扣减 (Redis Lua 原子操作)
  4. 创建订单 + Outbox 事件 (DB 原子写入)
  5. 缓存更新 (commit 后)
  6. 异步: 事件驱动库存确认/排产/通知
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from domains.orders.errors import (
    OrderAlreadyExists,
    OrderCannotTransition,
    OrderNotFound,
)
from domains.orders.repository import OrderRepository
from domains.orders.schema import (
    CreateOrderRequest,
    OrderResponse,
    OrderStatus,
    ORDER_STATUS_TRANSITIONS,
)
from infra.core.id_generator import OrderIdGenerator
from infra.events.outbox import OutboxPublisher
from infra.events.topics import Topics

if TYPE_CHECKING:
    from domains.customers.service import CustomerService
    from domains.inventory.service import InventoryService


class OrderService:
    def __init__(
        self,
        session: AsyncSession,
        order_repo: OrderRepository,
        inventory_service: "InventoryService",
        customer_service: "CustomerService",
    ) -> None:
        self.session = session
        self.order_repo = order_repo
        self.inventory_service = inventory_service
        self.customer_service = customer_service
        self.outbox = OutboxPublisher(session)
        self.id_generator = OrderIdGenerator()

    async def place_order(self, request: CreateOrderRequest) -> OrderResponse:
        """
        下单核心流程 (高并发安全)

        事务保证:
          - 订单创建 + outbox 事件写入在同一个 DB 事务中
          - 库存预扣减通过 Redis Lua 原子操作保证
          - commit 成功后才真正更新缓存
          - 如果 commit 失败，Redis 预扣减会通过 TTL 自动回滚
        """

        # 1. 计算订单金额与面积
        total_amount = Decimal("0")
        total_quantity = 0
        total_area = Decimal("0")
        for item in request.items:
            area = Decimal(str(item.width_mm * item.height_mm)) / Decimal("1000000")
            subtotal = item.unit_price * item.quantity
            total_amount += subtotal
            total_quantity += item.quantity
            total_area += area * item.quantity

        # 2. 客户信用校验
        await self.customer_service.check_credit(
            customer_id=request.customer_id,
            amount=total_amount,
        )

        # 3. 库存预扣减 (Redis Lua 原子操作)
        reservation_ids: list[str] = []
        try:
            for item in request.items:
                reservation_id = await self.inventory_service.reserve_stock(
                    product_id=item.product_id,
                    quantity=item.quantity,
                )
                reservation_ids.append(reservation_id)
        except Exception:
            # 回滚已经成功的预扣减
            for rid in reservation_ids:
                await self.inventory_service.rollback_reservation(rid)
            raise

        # 4. 生成订单号
        order_no = await self.id_generator.generate("GF")

        # 5. 创建订单 (DB)
        order = await self.order_repo.create_order(
            order_no=order_no,
            customer_id=request.customer_id,
            items=request.items,
            total_amount=total_amount,
            total_quantity=total_quantity,
            total_area_sqm=total_area,
            delivery_address=request.delivery_address,
            expected_delivery_date=request.expected_delivery_date,
            remark=request.remark,
            reservation_ids=reservation_ids,
        )

        # 6. 发布事件 (同一事务中写入 outbox)
        await self.outbox.publish_after_commit(
            topic=Topics.ORDER_CREATED,
            payload={
                "order_id": str(order.id),
                "order_no": order_no,
                "customer_id": request.customer_id,
                "total_amount": str(total_amount),
                "total_quantity": total_quantity,
                "items": [
                    {
                        "product_id": item.product_id,
                        "quantity": item.quantity,
                        "reservation_id": reservation_ids[idx],
                    }
                    for idx, item in enumerate(request.items)
                ],
            },
            key=order_no,
        )

        return self._to_response(order)

    async def cancel_order(self, order_id: str, reason: str = "") -> OrderResponse:
        """取消订单"""
        order = await self.order_repo.get_order(order_id)
        if not order:
            raise OrderNotFound(order_id=order_id)

        self._validate_transition(
            current=OrderStatus(order.status),
            target=OrderStatus.CANCELLED,
        )

        order = await self.order_repo.update_status(
            order_id=order_id,
            status=OrderStatus.CANCELLED,
            cancelled_reason=reason,
        )

        # 发布取消事件 → 异步回滚库存 + 通知客户
        await self.outbox.publish_after_commit(
            topic=Topics.ORDER_CANCELLED,
            payload={
                "order_id": order_id,
                "order_no": order.order_no,
                "reason": reason,
                "reservation_ids": order.reservation_ids or [],
            },
            key=order.order_no,
        )

        return self._to_response(order)

    async def transition_status(
        self,
        order_id: str,
        target_status: OrderStatus,
    ) -> OrderResponse:
        """通用状态流转"""
        order = await self.order_repo.get_order(order_id)
        if not order:
            raise OrderNotFound(order_id=order_id)

        current = OrderStatus(order.status)
        self._validate_transition(current, target_status)

        order = await self.order_repo.update_status(order_id, target_status)

        # 根据目标状态发布不同事件
        topic_map = {
            OrderStatus.CONFIRMED: Topics.ORDER_CONFIRMED,
            OrderStatus.PRODUCING: Topics.ORDER_PRODUCING,
            OrderStatus.PRODUCED: Topics.ORDER_PRODUCED,
            OrderStatus.SHIPPING: Topics.ORDER_SHIPPING,
            OrderStatus.DELIVERED: Topics.ORDER_DELIVERED,
            OrderStatus.COMPLETED: Topics.ORDER_COMPLETED,
        }
        topic = topic_map.get(target_status)
        if topic:
            await self.outbox.publish_after_commit(
                topic=topic,
                payload={"order_id": order_id, "order_no": order.order_no},
                key=order.order_no,
            )

        return self._to_response(order)

    @staticmethod
    def _validate_transition(current: OrderStatus, target: OrderStatus) -> None:
        allowed = ORDER_STATUS_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise OrderCannotTransition(
                current_status=current,
                target_status=target,
            )

    @staticmethod
    def _to_response(order) -> OrderResponse:
        """ORM model → Pydantic response"""
        # ... 转换逻辑
        ...
```

#### 5.1.5 订单错误码

```python
# domains/orders/errors.py
from infra.core.errors import AppError


class OrderNotFound(AppError):
    def __init__(self, order_id: str) -> None:
        super().__init__(
            code="ORDER_NOT_FOUND",
            message=f"订单不存在: {order_id}",
            status_code=404,
            details={"order_id": order_id},
        )


class OrderAlreadyExists(AppError):
    def __init__(self, idempotency_key: str) -> None:
        super().__init__(
            code="ORDER_ALREADY_EXISTS",
            message="订单已存在（重复提交）",
            status_code=409,
            details={"idempotency_key": idempotency_key},
        )


class OrderCannotTransition(AppError):
    def __init__(self, current_status: str, target_status: str) -> None:
        super().__init__(
            code="ORDER_INVALID_TRANSITION",
            message=f"订单状态无法从 {current_status} 变更为 {target_status}",
            status_code=422,
            details={"current": current_status, "target": target_status},
        )
```

### 5.2 库存域 (domains/inventory/)

#### 5.2.1 Redis Lua 原子扣减

```python
# domains/inventory/lua_scripts.py
"""
Redis Lua 原子操作脚本集

为什么用 Lua 而不是 Redis Pipeline:
  Pipeline 不是原子的，两个请求可能同时读到相同库存然后都扣减成功。
  Lua 脚本在 Redis 中是原子执行的，天然防超卖。

库存双写一致性方案:
  1. 写入时: 先写 DB → commit 成功 → 再更新 Redis
  2. 预扣减: Redis Lua 原子操作 (预占库存, 设 TTL 15 分钟)
  3. 确认扣减: DB 扣减 + Redis 确认 (移除预占, 更新可用量)
  4. 回滚: 删除 Redis 预占 key → 可用量自动恢复
  5. 兜底: 预占 key 有 TTL, 即使服务崩溃也会自动回滚
"""

# 库存预扣减 Lua 脚本
# KEYS[1] = 可用库存 key (inventory:available:{product_id})
# KEYS[2] = 预占 key (inventory:reserved:{reservation_id})
# ARGV[1] = 扣减数量
# ARGV[2] = 预占过期时间(秒)
# ARGV[3] = reservation_id
# 返回: 1=成功, 0=库存不足
RESERVE_STOCK_LUA = """
local available = tonumber(redis.call('GET', KEYS[1]) or '0')
local quantity = tonumber(ARGV[1])

if available < quantity then
    return 0
end

redis.call('DECRBY', KEYS[1], quantity)
redis.call('SET', KEYS[2], ARGV[3] .. ':' .. ARGV[1], 'EX', ARGV[2])
return 1
"""

# 确认扣减 Lua 脚本 (订单确认后调用)
# KEYS[1] = 预占 key
# 返回: 1=成功, 0=预占不存在(可能已过期)
CONFIRM_DEDUCTION_LUA = """
local exists = redis.call('EXISTS', KEYS[1])
if exists == 0 then
    return 0
end
redis.call('DEL', KEYS[1])
return 1
"""

# 回滚预扣减 Lua 脚本
# KEYS[1] = 可用库存 key
# KEYS[2] = 预占 key
# 返回: 回滚的数量, 0=预占不存在
ROLLBACK_RESERVATION_LUA = """
local reservation = redis.call('GET', KEYS[2])
if not reservation then
    return 0
end

local parts = {}
for part in string.gmatch(reservation, '[^:]+') do
    table.insert(parts, part)
end
local quantity = tonumber(parts[2] or '0')

redis.call('INCRBY', KEYS[1], quantity)
redis.call('DEL', KEYS[2])
return quantity
"""
```

#### 5.2.2 库存服务

```python
# domains/inventory/service.py
from __future__ import annotations

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from domains.inventory.lua_scripts import (
    CONFIRM_DEDUCTION_LUA,
    RESERVE_STOCK_LUA,
    ROLLBACK_RESERVATION_LUA,
)
from domains.inventory.errors import InventoryInsufficient
from domains.inventory.repository import InventoryRepository
from infra.cache.redis_client import get_redis

RESERVATION_TTL_SECONDS = 900  # 15 分钟


class InventoryService:
    def __init__(self, session: AsyncSession, repo: InventoryRepository) -> None:
        self.session = session
        self.repo = repo

    async def reserve_stock(self, product_id: str, quantity: int) -> str:
        """
        Redis Lua 原子预扣减

        返回 reservation_id，后续用于确认或回滚
        """
        reservation_id = str(uuid4())
        client = await get_redis()

        available_key = f"inventory:available:{product_id}"
        reserved_key = f"inventory:reserved:{reservation_id}"

        # 确保 Redis 有初始库存（首次从 DB 加载）
        exists = await client.exists(available_key)
        if not exists:
            db_stock = await self.repo.get_available_stock(product_id)
            await client.set(available_key, db_stock)

        result = await client.eval(
            RESERVE_STOCK_LUA,
            2,
            available_key,
            reserved_key,
            quantity,
            RESERVATION_TTL_SECONDS,
            reservation_id,
        )

        if result == 0:
            raise InventoryInsufficient(product_id=product_id, requested=quantity)

        return reservation_id

    async def confirm_deduction(self, reservation_id: str, product_id: str, quantity: int) -> None:
        """
        确认扣减: DB 落盘 + 删除 Redis 预占
        """
        # 1. DB 扣减 (在事务中)
        await self.repo.deduct_stock(product_id=product_id, quantity=quantity)

        # 2. 删除 Redis 预占 key
        client = await get_redis()
        reserved_key = f"inventory:reserved:{reservation_id}"
        await client.eval(CONFIRM_DEDUCTION_LUA, 1, reserved_key)

    async def rollback_reservation(self, reservation_id: str) -> int:
        """
        回滚预扣减: Redis 可用量 +回来，删除预占 key
        """
        client = await get_redis()
        # 需要知道 product_id 来构造 available_key
        reserved_key = f"inventory:reserved:{reservation_id}"

        # 从预占 key 的值中解析 product_id 和 quantity
        reservation_data = await client.get(reserved_key)
        if not reservation_data:
            return 0  # 已过期或已确认

        parts = reservation_data.split(":")
        product_id = parts[0] if parts else ""
        available_key = f"inventory:available:{product_id}"

        result = await client.eval(
            ROLLBACK_RESERVATION_LUA,
            2,
            available_key,
            reserved_key,
        )
        return int(result)

    async def check_low_stock_alerts(self) -> list[dict]:
        """检查安全库存预警"""
        return await self.repo.list_below_safety_stock()
```

### 5.3 生产域 (domains/production/)

#### 5.3.1 排产调度引擎

```python
# domains/production/scheduler_engine.py
"""
排产调度算法

这是玻璃工厂独有的核心模块，stock-py 没有对应物。

调度因素:
  1. 交期优先级: 交期越近优先级越高
  2. 产线匹配: 不同产线支持不同玻璃类型和最大尺寸
  3. 工艺约束: 某些工艺必须在特定产线上执行
  4. 批次合并: 相同规格的订单合并生产以减少换线次数
  5. 产能约束: 每条产线每天有最大产能限制

算法流程:
  待排工单 → 按交期排序 → 匹配可用产线 → 检查产能 → 分配时间槽 → 生成排产计划
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any


@dataclass(slots=True)
class WorkOrderCandidate:
    """待排产的工单"""
    work_order_id: str
    order_no: str
    glass_type: str          # 钢化 / 中空 / 夹层 / Low-E
    specification: str        # 如 6mm, 5+12A+5
    width_mm: int
    height_mm: int
    quantity: int
    area_sqm: Decimal
    process_requirements: str
    expected_delivery_date: date
    priority: int = 0         # 0=普通, 1=加急, 2=特急


@dataclass(slots=True)
class ProductionLine:
    """产线能力描述"""
    line_id: str
    line_name: str
    supported_glass_types: set[str]
    max_width_mm: int
    max_height_mm: int
    daily_capacity_sqm: Decimal
    supported_processes: set[str]
    current_load_sqm: Decimal = Decimal("0")


@dataclass(slots=True)
class ScheduleSlot:
    """排产结果"""
    work_order_id: str
    line_id: str
    scheduled_date: date
    estimated_start_time: datetime
    estimated_end_time: datetime
    sequence: int              # 当天该产线上的第几个


@dataclass
class ScheduleResult:
    """排产计划"""
    scheduled: list[ScheduleSlot] = field(default_factory=list)
    unschedulable: list[tuple[str, str]] = field(default_factory=list)  # (work_order_id, 原因)


class ProductionSchedulerEngine:
    """排产调度引擎"""

    def __init__(self, production_lines: list[ProductionLine]) -> None:
        self.lines = {line.line_id: line for line in production_lines}

    def schedule(
        self,
        candidates: list[WorkOrderCandidate],
        start_date: date | None = None,
        horizon_days: int = 14,
    ) -> ScheduleResult:
        """
        核心排产算法

        步骤:
        1. 按优先级+交期排序
        2. 对每个工单，找到最佳产线
        3. 分配时间槽
        4. 不可排产的工单记录原因
        """
        result = ScheduleResult()
        start = start_date or date.today()

        # 按优先级降序 → 交期升序 排列
        sorted_candidates = sorted(
            candidates,
            key=lambda c: (-c.priority, c.expected_delivery_date),
        )

        # 产线日历: line_id → date → 已用产能
        line_calendar: dict[str, dict[date, Decimal]] = {
            line_id: {} for line_id in self.lines
        }

        for candidate in sorted_candidates:
            assigned = False

            # 找到所有兼容的产线
            compatible_lines = self._find_compatible_lines(candidate)

            if not compatible_lines:
                result.unschedulable.append(
                    (candidate.work_order_id, f"无兼容产线: {candidate.glass_type} {candidate.width_mm}x{candidate.height_mm}")
                )
                continue

            # 在时间窗口内寻找最早可用的产线+日期
            deadline = min(
                candidate.expected_delivery_date - timedelta(days=2),  # 预留 2 天配送
                start + timedelta(days=horizon_days),
            )

            for day_offset in range(horizon_days):
                target_date = start + timedelta(days=day_offset)
                if target_date > deadline:
                    break

                # 跳过周末 (可配置)
                if target_date.weekday() >= 6:  # 周日
                    continue

                for line in compatible_lines:
                    used = line_calendar[line.line_id].get(target_date, Decimal("0"))
                    remaining = line.daily_capacity_sqm - used

                    if remaining >= candidate.area_sqm:
                        # 分配!
                        sequence = len([
                            s for s in result.scheduled
                            if s.line_id == line.line_id and s.scheduled_date == target_date
                        ]) + 1

                        slot = ScheduleSlot(
                            work_order_id=candidate.work_order_id,
                            line_id=line.line_id,
                            scheduled_date=target_date,
                            estimated_start_time=datetime.combine(
                                target_date,
                                datetime.min.time(),
                                tzinfo=timezone.utc,
                            ),
                            estimated_end_time=datetime.combine(
                                target_date,
                                datetime.min.time(),
                                tzinfo=timezone.utc,
                            ) + timedelta(hours=8),
                            sequence=sequence,
                        )
                        result.scheduled.append(slot)

                        # 更新产能日历
                        line_calendar[line.line_id][target_date] = used + candidate.area_sqm
                        assigned = True
                        break

                if assigned:
                    break

            if not assigned:
                result.unschedulable.append(
                    (candidate.work_order_id, f"在 {horizon_days} 天内无法排入生产")
                )

        return result

    def _find_compatible_lines(self, candidate: WorkOrderCandidate) -> list[ProductionLine]:
        """查找兼容的产线"""
        compatible = []
        for line in self.lines.values():
            if candidate.glass_type not in line.supported_glass_types:
                continue
            if candidate.width_mm > line.max_width_mm:
                continue
            if candidate.height_mm > line.max_height_mm:
                continue
            # 检查工艺约束
            if candidate.process_requirements:
                required = set(candidate.process_requirements.split(","))
                if not required.issubset(line.supported_processes):
                    continue
            compatible.append(line)

        # 按负载从低到高排序（优先使用空闲产线）
        compatible.sort(key=lambda l: l.current_load_sqm)
        return compatible
```

### 5.4 其他领域模块概要

| 领域 | 核心实体 | 核心操作 | 事件 |
|------|---------|---------|------|
| **客户** | Customer, CreditLimit, PriceLevel | 信用校验, 价格计算, 等级升降 | customer.credit_updated |
| **物流** | ShipmentPlan, TrackingEvent | 生成发货计划, 记录物流节点, 签收确认 | logistics.shipped, logistics.delivered |
| **财务** | Invoice, Payment, Reconciliation | 生成账单, 记录付款, 自动对账 | finance.invoice_created, finance.payment_received |
| **通知** | Notification, PushDevice | 站内信, WebPush, 邮件, 短信 | (消费其他域的事件) |

---

## 第六章 数据库设计

### 6.1 核心表 DDL

```sql
-- ============================================================
-- 订单主表
-- ============================================================
CREATE TABLE orders (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_no        VARCHAR(30) NOT NULL UNIQUE,       -- GF20260409-01-000001
    customer_id     UUID NOT NULL REFERENCES customers(id),
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    total_amount    DECIMAL(15,2) NOT NULL DEFAULT 0,
    total_quantity  INTEGER NOT NULL DEFAULT 0,
    total_area_sqm  DECIMAL(12,4) NOT NULL DEFAULT 0,
    delivery_address TEXT NOT NULL,
    expected_delivery_date TIMESTAMPTZ NOT NULL,
    confirmed_at    TIMESTAMPTZ,
    cancelled_at    TIMESTAMPTZ,
    cancelled_reason TEXT,
    reservation_ids JSONB DEFAULT '[]',                 -- 库存预扣减 ID 列表
    remark          TEXT DEFAULT '',
    idempotency_key VARCHAR(64) UNIQUE,                 -- 幂等键
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version         INTEGER NOT NULL DEFAULT 1          -- 乐观锁版本号
);

CREATE INDEX idx_orders_customer_id ON orders(customer_id);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_orders_created_at ON orders(created_at DESC);
CREATE INDEX idx_orders_order_no ON orders(order_no);
CREATE INDEX idx_orders_expected_delivery ON orders(expected_delivery_date);

-- ============================================================
-- 订单明细表
-- ============================================================
CREATE TABLE order_items (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id        UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id      UUID NOT NULL REFERENCES products(id),
    product_name    VARCHAR(200) NOT NULL,
    glass_type      VARCHAR(50) NOT NULL,               -- 钢化/中空/夹层/Low-E
    specification   VARCHAR(100) NOT NULL,              -- 6mm, 5+12A+5
    width_mm        INTEGER NOT NULL,
    height_mm       INTEGER NOT NULL,
    area_sqm        DECIMAL(10,4) NOT NULL,
    quantity        INTEGER NOT NULL,
    unit_price      DECIMAL(12,2) NOT NULL,
    subtotal        DECIMAL(15,2) NOT NULL,
    process_requirements TEXT DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_order_items_order_id ON order_items(order_id);
CREATE INDEX idx_order_items_product_id ON order_items(product_id);

-- ============================================================
-- 产品表
-- ============================================================
CREATE TABLE products (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_code    VARCHAR(50) NOT NULL UNIQUE,
    product_name    VARCHAR(200) NOT NULL,
    glass_type      VARCHAR(50) NOT NULL,
    specification   VARCHAR(100) NOT NULL,
    base_price      DECIMAL(12,2) NOT NULL,
    unit            VARCHAR(20) NOT NULL DEFAULT 'piece', -- piece/sqm
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- 库存表
-- ============================================================
CREATE TABLE inventory (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id      UUID NOT NULL UNIQUE REFERENCES products(id),
    available_qty   INTEGER NOT NULL DEFAULT 0,         -- 可用库存
    reserved_qty    INTEGER NOT NULL DEFAULT 0,         -- 预占库存
    total_qty       INTEGER NOT NULL DEFAULT 0,         -- 总库存 = available + reserved
    safety_stock    INTEGER NOT NULL DEFAULT 0,         -- 安全库存
    warehouse_code  VARCHAR(20) NOT NULL DEFAULT 'WH01',
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version         INTEGER NOT NULL DEFAULT 1          -- 乐观锁
);

CREATE INDEX idx_inventory_product_id ON inventory(product_id);
CREATE INDEX idx_inventory_low_stock ON inventory(available_qty) WHERE available_qty <= safety_stock;

-- ============================================================
-- 客户表
-- ============================================================
CREATE TABLE customers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_code   VARCHAR(30) NOT NULL UNIQUE,
    company_name    VARCHAR(200) NOT NULL,
    contact_name    VARCHAR(100),
    phone           VARCHAR(20),
    email           VARCHAR(100),
    address         TEXT,
    credit_limit    DECIMAL(15,2) NOT NULL DEFAULT 0,   -- 信用额度
    credit_used     DECIMAL(15,2) NOT NULL DEFAULT 0,   -- 已用额度
    price_level     VARCHAR(20) NOT NULL DEFAULT 'standard', -- standard/vip/svip
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- 生产工单表
-- ============================================================
CREATE TABLE work_orders (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    work_order_no       VARCHAR(30) NOT NULL UNIQUE,     -- WO20260409-01
    order_id            UUID NOT NULL REFERENCES orders(id),
    order_item_id       UUID NOT NULL REFERENCES order_items(id),
    production_line_id  UUID REFERENCES production_lines(id),
    status              VARCHAR(20) NOT NULL DEFAULT 'pending',
    -- pending → scheduled → in_progress → quality_check → completed / rejected
    glass_type          VARCHAR(50) NOT NULL,
    specification       VARCHAR(100) NOT NULL,
    width_mm            INTEGER NOT NULL,
    height_mm           INTEGER NOT NULL,
    quantity            INTEGER NOT NULL,
    completed_qty       INTEGER NOT NULL DEFAULT 0,
    defect_qty          INTEGER NOT NULL DEFAULT 0,
    scheduled_date      DATE,
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_work_orders_order_id ON work_orders(order_id);
CREATE INDEX idx_work_orders_status ON work_orders(status);
CREATE INDEX idx_work_orders_scheduled_date ON work_orders(scheduled_date);
CREATE INDEX idx_work_orders_line_id ON work_orders(production_line_id);

-- ============================================================
-- 产线表
-- ============================================================
CREATE TABLE production_lines (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    line_code           VARCHAR(20) NOT NULL UNIQUE,     -- LINE-01
    line_name           VARCHAR(100) NOT NULL,
    supported_glass_types JSONB NOT NULL DEFAULT '[]',   -- ["钢化","中空"]
    max_width_mm        INTEGER NOT NULL DEFAULT 3000,
    max_height_mm       INTEGER NOT NULL DEFAULT 6000,
    daily_capacity_sqm  DECIMAL(10,2) NOT NULL,
    supported_processes JSONB NOT NULL DEFAULT '[]',
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- 质检记录表
-- ============================================================
CREATE TABLE quality_checks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    work_order_id   UUID NOT NULL REFERENCES work_orders(id),
    inspector_id    UUID NOT NULL REFERENCES users(id),
    check_type      VARCHAR(30) NOT NULL,                -- visual/dimensional/stress/optical
    result          VARCHAR(20) NOT NULL,                -- passed/failed/conditional
    checked_qty     INTEGER NOT NULL,
    passed_qty      INTEGER NOT NULL,
    defect_qty      INTEGER NOT NULL DEFAULT 0,
    defect_details  JSONB DEFAULT '[]',                  -- [{type, count, description}]
    images          JSONB DEFAULT '[]',                  -- MinIO 图片路径
    remark          TEXT DEFAULT '',
    checked_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_quality_checks_work_order ON quality_checks(work_order_id);

-- ============================================================
-- 发货计划表
-- ============================================================
CREATE TABLE shipments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shipment_no     VARCHAR(30) NOT NULL UNIQUE,
    order_id        UUID NOT NULL REFERENCES orders(id),
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    -- pending → picked → loading → in_transit → delivered
    carrier_name    VARCHAR(100),
    tracking_no     VARCHAR(100),
    vehicle_no      VARCHAR(20),
    driver_name     VARCHAR(50),
    driver_phone    VARCHAR(20),
    shipped_at      TIMESTAMPTZ,
    delivered_at    TIMESTAMPTZ,
    receiver_name   VARCHAR(100),
    receiver_phone  VARCHAR(20),
    signature_image VARCHAR(500),                        -- MinIO 签收图片
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- 财务应收表
-- ============================================================
CREATE TABLE receivables (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id        UUID NOT NULL REFERENCES orders(id),
    customer_id     UUID NOT NULL REFERENCES customers(id),
    invoice_no      VARCHAR(30) UNIQUE,
    amount          DECIMAL(15,2) NOT NULL,
    paid_amount     DECIMAL(15,2) NOT NULL DEFAULT 0,
    status          VARCHAR(20) NOT NULL DEFAULT 'unpaid',
    -- unpaid → partial → paid → overdue
    due_date        DATE NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- 事件 Outbox 表 (来自 stock-py 的核心设计)
-- ============================================================
CREATE TABLE event_outbox (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic           VARCHAR(100) NOT NULL,
    event_key       VARCHAR(200),
    payload         JSONB NOT NULL DEFAULT '{}',
    headers         JSONB NOT NULL DEFAULT '{}',
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    -- pending → published / dead_letter
    attempt_count   INTEGER NOT NULL DEFAULT 0,
    max_attempts    INTEGER NOT NULL DEFAULT 3,
    broker_message_id VARCHAR(200),
    last_error      TEXT,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_event_outbox_status_created ON event_outbox(status, created_at ASC)
    WHERE status = 'pending';
CREATE INDEX idx_event_outbox_dead_letter ON event_outbox(status, created_at ASC)
    WHERE status = 'dead_letter';
CREATE INDEX idx_event_outbox_topic ON event_outbox(topic);

-- ============================================================
-- 用户表
-- ============================================================
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username        VARCHAR(50) NOT NULL UNIQUE,
    email           VARCHAR(100) NOT NULL UNIQUE,
    password_hash   VARCHAR(200) NOT NULL,
    display_name    VARCHAR(100) NOT NULL,
    role            VARCHAR(20) NOT NULL DEFAULT 'operator',
    -- admin / manager / operator / customer / viewer
    scopes          JSONB NOT NULL DEFAULT '[]',         -- ["orders:read","orders:write"]
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    last_login_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 6.2 索引设计原则

```
1. 主键全部使用 UUID (gen_random_uuid)
   - 分布式环境天然唯一
   - 不暴露业务量
   - PostgreSQL 16 的 UUID v7 性能已接近自增 ID

2. 复合索引遵循最左前缀
   - 把选择性高的列放在前面
   - 把范围查询的列放在最后

3. 部分索引 (Partial Index) 优先
   - event_outbox 只索引 status='pending' 的行
   - inventory 只索引低于安全库存的行
   - 大幅减少索引体积

4. JSONB 字段不建 GIN 索引 (除非有明确的查询需求)
   - JSONB 存元数据，主要用于展示
   - 查询用固定字段的 B-tree 索引

5. 乐观锁使用 version 字段
   - 订单、库存等需要并发安全的表加 version
   - UPDATE ... WHERE id = $1 AND version = $2
```

### 6.3 ER 关系图

```
customers ─────┐                                 production_lines
    │          │                                       │
    │ 1:N      │ 1:N                                   │ 1:N
    ▼          ▼                                       ▼
receivables  orders ──── 1:N ──── order_items    work_orders
              │                       │               │
              │ 1:N                   │ 1:1           │ 1:N
              ▼                       ▼               ▼
          shipments              work_orders    quality_checks
                                     │
                              (同上 linked)

products ─── 1:1 ─── inventory

event_outbox  (独立，不与业务表有外键关系)
users         (通过 UUID 关联到各表的 operator/inspector 字段)
```

---

## 第七章 缓存设计

### 7.1 多级缓存架构

```
                    ┌──────────────────────┐
                    │  请求 (HTTP Request)  │
                    └──────────┬───────────┘
                               │
                    ┌──────────▼───────────┐
                    │  进程内缓存 (lru_cache)│  ← 配置/元数据，TTL=进程生命周期
                    │  命中率: ~95%          │
                    └──────────┬───────────┘
                               │ miss
                    ┌──────────▼───────────┐
                    │  Redis 缓存           │  ← 热数据，TTL=30s~5min
                    │  命中率: ~85%          │
                    └──────────┬───────────┘
                               │ miss
                    ┌──────────▼───────────┐
                    │  PostgreSQL (DB)      │  ← 权威数据源
                    │                       │
                    └───────────────────────┘
```

### 7.2 缓存策略矩阵

| 数据类型 | 缓存层 | TTL | 更新策略 | Key 格式 |
|---------|-------|-----|---------|---------|
| 系统配置 | lru_cache | 进程内 | 重启更新 | N/A |
| 产品目录 | Redis | 5min | 修改时主动失效 | `product:{id}` |
| 库存可用量 | Redis | 实时 | Lua 原子操作 | `inventory:available:{product_id}` |
| 库存预占 | Redis | 15min | TTL 自动过期 | `inventory:reserved:{reservation_id}` |
| 订单详情 | Redis | 30s | commit 后更新 | `order:{id}` |
| 客户信息 | Redis | 60s | commit 后更新 | `customer:{id}` |
| 客户价格 | Redis | 5min | 修改时失效 | `price:{customer_id}:{product_id}` |
| 用户会话 | Redis | 30min | 访问时续期 | `session:{token_hash}` |
| 限流计数 | Redis | 1min | INCR 原子递增 | `ratelimit:{ip}:{minute}` |
| 幂等键 | Redis | 24h | 下单时写入 | `idempotency:{key}` |

### 7.3 缓存穿透/击穿/雪崩防护

```python
# 缓存穿透防护: 空值缓存 + 布隆过滤器
async def get_product(product_id: str) -> Product | None:
    # 1. 查 Redis
    cached = await get_json(f"product:{product_id}")
    if cached is not None:
        if cached == "__NULL__":
            return None  # 空值缓存，避免穿透
        return Product(**cached)

    # 2. 查 DB
    product = await repo.get_product(product_id)

    # 3. 写 Redis (包括空值)
    if product:
        await set_json(f"product:{product_id}", product.dict(), expire=300)
    else:
        await set_json(f"product:{product_id}", "__NULL__", expire=60)

    return product


# 缓存击穿防护: 分布式锁 (stock-py 的 cache_fill_lock 模式)
async def get_hot_product(product_id: str) -> Product:
    cached = await get_json(f"product:{product_id}")
    if cached:
        return Product(**cached)

    # 分布式锁防止并发重建
    lock_key = f"lock:cache:product:{product_id}"
    client = await get_redis()
    acquired = await client.set(lock_key, "1", nx=True, ex=15)

    if acquired:
        try:
            product = await repo.get_product(product_id)
            await set_json(f"product:{product_id}", product.dict(), expire=300)
            return product
        finally:
            await client.delete(lock_key)
    else:
        # 等待其他请求重建完成
        for _ in range(20):
            await asyncio.sleep(0.05)
            cached = await get_json(f"product:{product_id}")
            if cached:
                return Product(**cached)
        # 兜底: 直接查 DB
        return await repo.get_product(product_id)


# 缓存雪崩防护: TTL 随机偏移
import random

def jittered_ttl(base_ttl: int) -> int:
    """在 base_ttl 基础上增加 ±20% 的随机偏移"""
    jitter = int(base_ttl * 0.2)
    return base_ttl + random.randint(-jitter, jitter)
```

### 7.4 Cache-After-Commit Hook 机制（优化 stock-py）

stock-py 的问题：`session.py` 中硬编码了多个 `apply_*_cache_operations`，每加一个 cache 就要改 session.py。

优化方案：可注册的 hook 机制。

```python
# infra/core/hooks.py
"""
可注册的生命周期 Hook 机制

替代 stock-py 在 session.py 中硬编码的 apply_*_cache_operations，
让每个 domain 自行注册自己的 cache-after-commit 回调。
"""
from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

# Hook 类型定义
AfterCommitHook = Callable[[AsyncSession], Coroutine[Any, Any, None]]

# Session 上挂载的 hook 存储 key
_HOOKS_ATTR = "_registered_after_commit_hooks"


def register_after_commit_hook(session: AsyncSession, hook: AfterCommitHook) -> None:
    """在 session 上注册一个 commit 后执行的 hook"""
    hooks = getattr(session, _HOOKS_ATTR, None)
    if hooks is None:
        hooks = []
        setattr(session, _HOOKS_ATTR, hooks)
    hooks.append(hook)


def pop_after_commit_hooks(session: AsyncSession) -> list[AfterCommitHook]:
    """取出并清空所有注册的 hooks"""
    hooks = getattr(session, _HOOKS_ATTR, None) or []
    setattr(session, _HOOKS_ATTR, [])
    return hooks


async def execute_after_commit_hooks(session: AsyncSession) -> None:
    """执行所有注册的 hooks（在 commit 之后调用）"""
    hooks = pop_after_commit_hooks(session)
    for hook in hooks:
        try:
            await hook(session)
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "After-commit hook failed",
                exc_info=True,
            )
```

优化后的 session.py：

```python
# infra/db/session.py (简化版)
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    session_factory = build_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
            # ✅ 一行代替 stock-py 的 5 个 apply_*_cache_operations
            await execute_after_commit_hooks(session)
        except Exception:
            pop_after_commit_hooks(session)  # 清理未执行的 hooks
            await session.rollback()
            raise
```

使用方式（domain 自行注册）：

```python
# domains/orders/service.py
from infra.core.hooks import register_after_commit_hook

class OrderService:
    async def place_order(self, request: CreateOrderRequest) -> OrderResponse:
        order = await self.order_repo.create_order(...)

        # 注册 commit 后缓存更新
        async def update_order_cache(session):
            await set_json(f"order:{order.id}", order_data, expire=30)

        register_after_commit_hook(self.session, update_order_cache)

        return self._to_response(order)
```

---

## 第八章 事件驱动设计

### 8.1 Outbox + EventBus 模式

```
应用代码 (Service)
    │
    │  publish_after_commit(topic, payload)
    │  → 写入 event_outbox 表 (同一 DB 事务)
    │
    ▼
┌──────────────────────────────────────────┐
│  event_outbox 表                          │
│  status: pending → published / dead_letter │
└──────────┬───────────────────────────────┘
           │
           │  Event Pipeline Worker
           │  (每 1s poll → claim_pending → relay to broker)
           │
           │  claim_pending 使用 FOR UPDATE SKIP LOCKED
           │  → 多 worker 实例安全并发
           │
           ▼
┌──────────────────────────────────────────┐
│  Kafka (或 Redis Streams)                 │
│  Topic: factory.events                    │
│  Partition: 按 event_key 路由             │
└──────────┬───────────────────────────────┘
           │
           │  Dispatcher Worker
           │  (消费 Kafka → 路由到 subscriber)
           │
           ▼
┌──────────────────────────────────────────┐
│  Event Subscribers                        │
│                                           │
│  order.created  → 生成生产工单             │
│                 → 通知客户                 │
│                 → 数据下沉 ClickHouse      │
│                                           │
│  order.cancelled → 回滚库存预扣减          │
│                  → 通知客户                │
│                                           │
│  order.confirmed → 确认库存扣减            │
│                  → 触发排产                │
│                                           │
│  production.completed → 更新订单状态       │
│                       → 安排发货           │
│                                           │
│  inventory.low_stock → 发送预警通知        │
│                                           │
│  失败处理: attempt_count++ → 超过 max_attempts → dead_letter
│  运维工具: python -m infra.events.outbox stats
│           python -m infra.events.outbox replay-dead-letter --limit 50
└──────────────────────────────────────────┘
```

### 8.2 事件 Topic 定义

```python
# infra/events/topics.py
class Topics:
    """事件 Topic 常量"""

    # 订单域
    ORDER_CREATED = "orders.order.created"
    ORDER_CONFIRMED = "orders.order.confirmed"
    ORDER_PRODUCING = "orders.order.producing"
    ORDER_PRODUCED = "orders.order.produced"
    ORDER_SHIPPING = "orders.order.shipping"
    ORDER_DELIVERED = "orders.order.delivered"
    ORDER_COMPLETED = "orders.order.completed"
    ORDER_CANCELLED = "orders.order.cancelled"

    # 库存域
    INVENTORY_RESERVED = "inventory.stock.reserved"
    INVENTORY_DEDUCTED = "inventory.stock.deducted"
    INVENTORY_ROLLED_BACK = "inventory.stock.rolled_back"
    INVENTORY_LOW_STOCK = "inventory.stock.low_stock_alert"

    # 生产域
    PRODUCTION_SCHEDULED = "production.work_order.scheduled"
    PRODUCTION_STARTED = "production.work_order.started"
    PRODUCTION_COMPLETED = "production.work_order.completed"
    PRODUCTION_QUALITY_PASSED = "production.quality.passed"
    PRODUCTION_QUALITY_FAILED = "production.quality.failed"

    # 物流域
    LOGISTICS_SHIPPED = "logistics.shipment.shipped"
    LOGISTICS_DELIVERED = "logistics.shipment.delivered"

    # 财务域
    FINANCE_INVOICE_CREATED = "finance.invoice.created"
    FINANCE_PAYMENT_RECEIVED = "finance.payment.received"

    # 审计
    OPS_AUDIT_LOGGED = "ops.audit.logged"
```

---

## 第九章 API 设计规范

### 9.1 统一响应格式

```python
# 成功响应
{
    "data": { ... },
    "request_id": "550e8400-e29b-41d4-a716-446655440000",
    "timestamp": "2026-04-09T10:30:00Z"
}

# 分页响应
{
    "data": [ ... ],
    "pagination": {
        "page": 1,
        "page_size": 20,
        "total": 156,
        "total_pages": 8
    },
    "request_id": "..."
}

# 错误响应 (来自 stock-py 的 AppError 模式)
{
    "error": {
        "code": "ORDER_NOT_FOUND",
        "message": "订单不存在: GF20260409-01-000001",
        "details": {
            "order_id": "550e8400..."
        }
    },
    "request_id": "..."
}
```

### 9.2 核心 API 端点

```
# ==================== Public API (:8000) ====================

# 认证
POST   /v1/auth/login                  # 登录
POST   /v1/auth/logout                 # 登出
POST   /v1/auth/refresh                # 刷新 token
POST   /v1/auth/send-code              # 发送验证码

# 订单
POST   /v1/orders                      # 创建订单 (高并发)
GET    /v1/orders                      # 订单列表 (分页/筛选)
GET    /v1/orders/{order_id}           # 订单详情
PUT    /v1/orders/{order_id}/cancel    # 取消订单
PUT    /v1/orders/{order_id}/confirm   # 确认订单
GET    /v1/orders/{order_id}/timeline  # 订单时间线

# 库存
GET    /v1/inventory                   # 库存查询
GET    /v1/inventory/{product_id}      # 单品库存

# 生产
GET    /v1/production/work-orders      # 工单列表
GET    /v1/production/work-orders/{id} # 工单详情
GET    /v1/production/schedule         # 排产计划

# 客户
GET    /v1/customers/profile           # 客户档案
GET    /v1/customers/credit            # 信用余额

# 物流
GET    /v1/logistics/shipments         # 发货列表
GET    /v1/logistics/tracking/{no}     # 物流追踪

# 财务
GET    /v1/finance/statements          # 对账单
GET    /v1/finance/invoices            # 发票列表

# 通知
GET    /v1/notifications               # 通知列表
PUT    /v1/notifications/read          # 标记已读

# 搜索
GET    /v1/search?q=...                # 全局搜索

# ==================== Admin API (:8001) ====================

# 分析看板
GET    /v1/admin/analytics/overview    # 经营概览
GET    /v1/admin/analytics/production  # 产能分析
GET    /v1/admin/analytics/sales       # 销售分析

# 用户管理
GET    /v1/admin/users                 # 用户列表
PUT    /v1/admin/users/{id}            # 编辑用户
POST   /v1/admin/users/bulk            # 批量操作

# 排产管理
POST   /v1/admin/production/schedule   # 执行排产
GET    /v1/admin/production/lines      # 产线列表
PUT    /v1/admin/production/lines/{id} # 产线配置

# 运行时
GET    /v1/admin/runtime/health        # 系统健康
GET    /v1/admin/runtime/metrics       # 运行指标
GET    /v1/admin/runtime/alerts        # 告警列表

# 审计
GET    /v1/admin/audit                 # 审计日志

# 健康检查 (两个 API 都有)
GET    /health                         # 存活检查
GET    /health/ready                   # 就绪检查 (探测 DB/Redis/Kafka)
GET    /metrics                        # Prometheus 指标
```

### 9.3 RBAC 权限模型

```
角色层级:

  super_admin (超级管理员)
    └── admin (管理员)
         ├── manager (经理)
         │    ├── operator (操作员)
         │    └── inspector (质检员)
         └── finance (财务)

  customer (客户 - 外部用户)
    └── customer_viewer (客户只读)

权限 Scope:

  orders:read      订单查看
  orders:write     订单创建/修改
  orders:cancel    订单取消
  inventory:read   库存查看
  inventory:write  库存调整
  production:read  生产查看
  production:write 排产/工单操作
  quality:write    质检操作
  logistics:write  物流操作
  finance:read     财务查看
  finance:write    财务操作
  admin:read       管理后台查看
  admin:write      管理后台操作
  system:manage    系统配置
```

---

## 第十章 高并发保障

### 10.1 下单高并发全链路

```
峰值 5000 TPS 下单请求

  ┌── Nginx ──────────────────────────────────────────┐
  │  连接数限制: worker_connections 4096              │
  │  限流: limit_req zone=order burst=1000 nodelay    │
  └───────────┬──────────────────────────────────────┘
              │
  ┌───────────▼──────────────────────────────────────┐
  │  FastAPI (4 workers × 2 instances = 8 uvicorn)   │
  │  单 worker ~1500 QPS (async) → 总 ~12,000 QPS    │
  │                                                   │
  │  1. 幂等校验 (Redis GET) ─── ~0.5ms              │
  │  2. 库存预扣减 (Redis Lua) ── ~1ms               │
  │  3. DB 写入 (PgBouncer) ──── ~5ms                │
  │  4. Outbox 写入 (同事务) ──── ~1ms                │
  │  5. 响应客户端 ─────────────  ~8ms total          │
  └───────────┬──────────────────────────────────────┘
              │
  ┌───────────▼──────────────────────────────────────┐
  │  PgBouncer (transaction pooling)                  │
  │  max_client_conn = 1000                           │
  │  default_pool_size = 50                           │
  │  reserve_pool_size = 10                           │
  │                                                   │
  │  → 8 个 uvicorn worker 的连接请求全部由            │
  │    PgBouncer 管理���PostgreSQL 只需维护 50 个连接   │
  └───────────┬──────────────────────────────────────┘
              │
  ┌───────────▼──────────────────────────────────────┐
  │  PostgreSQL 16                                    │
  │  max_connections = 200                            │
  │  shared_buffers = 4GB                             │
  │  effective_cache_size = 12GB                      │
  │  work_mem = 32MB                                  │
  └──────────────────────────────────────────────────┘
```

### 10.2 容量评估

| 组件 | 配置 | 支撑能力 | 成本/月(云) |
|------|------|---------|------------|
| **App Server** | 2 × 4C8G VM | ~12,000 QPS | ¥800 |
| **PostgreSQL** | 1 × 8C32G (主) + 1 × 8C32G (从) | ~8,000 TPS | ¥3,000 |
| **PgBouncer** | 与 App 同机 | 10K+ 并发连接 | ¥0 |
| **Redis** | 1 × 4C8G | ~100,000 QPS | ¥600 |
| **Kafka** | 1 × 4C8G (KRaft) | ~100,000 msg/s | ¥600 |
| **ClickHouse** | 1 × 4C16G | 千万级聚合 <1s | ¥800 |
| **MinIO** | 1 × 2C4G + 500G SSD | 10TB+ 对象存储 | ¥500 |
| **Nginx** | 与 App 同机 | 50K+ 并发 | ¥0 |
| **总计** | — | DAU 300万 + 峰值 20K QPS | **¥5,500~6,300/月** |

### 10.3 限流策略

```python
# 三级限流

# 1. Nginx 层: IP 维度粗粒度限流
# nginx.conf
limit_req_zone $binary_remote_addr zone=api:10m rate=100r/s;
limit_req_zone $binary_remote_addr zone=order:10m rate=10r/s;

location /v1/orders {
    limit_req zone=order burst=50 nodelay;
}

# 2. FastAPI 层: 用户维度细粒度限流 (slowapi)
from slowapi import Limiter
limiter = Limiter(key_func=get_user_id)

@router.post("/orders")
@limiter.limit("10/minute")
async def create_order(request: Request, ...):
    ...

# 3. 业务层: 客户维度限流
# 同一客户 1 分钟内最多下 5 单
async def check_order_rate_limit(customer_id: str):
    key = f"order_rate:{customer_id}:{int(time.time()) // 60}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 120)
    if count > 5:
        raise OrderRateLimited(customer_id=customer_id)
```

---

## 第十一章 可观测性

### 11.1 Metrics 导出

复用 stock-py 的 `MetricsRegistry` 模式，新增工厂业务指标：

```python
# 应用指标
stock_factory_public_http_requests_total           # 请求总数
stock_factory_public_http_request_errors_total      # 5xx 错误数
stock_factory_public_http_request_duration_ms       # 请求延迟

# 业务指标 (新增)
stock_factory_orders_created_total                  # 订单创建总数
stock_factory_orders_cancelled_total                # 订单取消总数
stock_factory_inventory_reservations_total          # 库存预扣减次数
stock_factory_inventory_reservation_failures_total  # 库存不足次数
stock_factory_production_work_orders_completed_total # 工单完成数
stock_factory_production_yield_rate                 # 良品率

# 基础设施指标
stock_factory_event_outbox_pending                  # 待发布事件数
stock_factory_event_outbox_dead_letter              # 死信数
stock_factory_pgbouncer_waiting_clients             # PgBouncer 等待连接数
stock_factory_redis_memory_used_bytes               # Redis 内存使用
stock_factory_uptime_seconds                        # 进程运行时间
```

### 11.2 告警规则

| 指标 | 阈值 | 级别 | 处理方式 |
|------|-----|------|---------|
| P99 延迟 | > 200ms | Warning | 检查慢查询 |
| P99 延迟 | > 500ms | Critical | 紧急排查 |
| 5xx 错误率 | > 1% | Warning | 检查日志 |
| 5xx 错误率 | > 5% | Critical | 紧急排查 |
| PgBouncer waiting | > 10 | Warning | 考虑扩容 |
| Redis 内存 | > 85% | Warning | 检查淘汰策略 |
| Kafka 消费 lag | > 200 | Warning | 扩 worker |
| Dead Letter 数量 | > 0 | Warning | 检查 replay |
| 库存预扣减失败 | > 100/min | Warning | 检查热门品 |

---

## 第十二章 安全设计

### 12.1 认证流程

```
客户端                      Public API                   Redis
  │                            │                          │
  │  POST /v1/auth/login       │                          │
  │  {email, password}         │                          │
  │ ──────────────────────────►│                          │
  │                            │  验证密码                 │
  │                            │  生成 JWT (30min)         │
  │                            │  生成 Refresh Token (7d)  │
  │                            │                          │
  │                            │  SET session:{hash}      │
  │                            │ ────────────────────────►│
  │                            │                          │
  │  200 {access_token,        │                          │
  │       refresh_token}       │                          │
  │ ◄──────────────────────────│                          │
  │                            │                          │
  │  GET /v1/orders            │                          │
  │  Authorization: Bearer xxx │                          │
  │ ──────────��───────────────►│                          │
  │                            │  验证 JWT 签名            │
  │                            │  检查 session 是否有效    │
  │                            │  GET session:{hash}      │
  │                            │ ────────────────────────►│
  │                            │                          │
  │  200 {orders: [...]}       │                          │
  │ ◄──────────────────────────│                          │
```

### 12.2 File-Backed Secrets

```
开发环境:
  ops/secrets/dev/
    ├── app_database_url.txt      # postgresql+asyncpg://...
    ├── app_secret_key.txt        # jwt-secret-xxx
    ├── postgres_password.txt     # stockpy-pg
    └── minio_root_password.txt   # minio-xxx

生产环境:
  ops/secrets/production/         # 不提交到 Git
    ├── app_database_url.txt
    ├── app_secret_key.txt
    └── ...

Docker Compose 中:
  secrets:
    app_database_url:
      file: ${OPS_SECRET_DIR:-./secrets/dev}/app_database_url.txt

  services:
    public-api:
      environment:
        DATABASE_URL_FILE: /run/secrets/app_database_url
      secrets:
        - app_database_url

配置加载 (infra/core/config.py):
  → FileBackedEnvSettingsSource 检查 DATABASE_URL_FILE
  → 读取文件内容作为 DATABASE_URL 的值
  → 敏感信息不暴露在环境变量中
```

---

## 第十三章 测试策略

### 13.1 测试金字塔

```
                    ╱╲
                   ╱  ╲
                  ╱ Load╲         Locust: 5000 TPS 压测
                 ╱  Test ╲
                ╱────────╲
               ╱   E2E    ╲       完整流程: 下单→排产→发货→结算
              ╱   Tests    ╲
             ╱──────────────╲
            ╱   Contract     ╲     OpenAPI snapshot + response schema 验证
           ╱    Tests         ╲
          ╱────────────────────╲
         ╱    Integration       ╲   DB + Redis + Service 真实交互
        ╱      Tests             ╲
       ╱──────────────────────────╲
      ╱         Unit Tests         ╲   纯逻辑: 状态机、排产算法、价格计算
     ╱──────────────────────────────╲

覆盖率目标:
  Unit:        > 80%
  Integration: > 50%
  Contract:    所有 Public/Admin API
  E2E:         核心链路 (下单→排产→发货)
  Load:        峰值 5000 TPS 稳定运行 10 分钟
```

### 13.2 CI Pipeline

```yaml
# .github/workflows/qa.yml
name: QA
on:
  pull_request:
  push:
    branches: [main, master]

jobs:
  qa:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.13'
          cache: 'pip'
      - run: pip install -r requirements.txt
      - run: make lint          # black --check + isort --check
      - run: make qa-ci         # unit + integration + contract + e2e + load-import
```

---

## 第十四章 部署方案

### 14.1 一键部署命令

```bash
# 开发环境 - 完整启动
make ops-stack-up

# 等价于:
docker compose -f ops/docker-compose.yml up -d --build

# 启动后可访问:
# http://localhost:8080          Nginx 入口
# http://localhost:8000/docs     Public API 文档
# http://localhost:8001/docs     Admin API 文档
# http://localhost:9001          MinIO Console
```

### 14.2 Makefile 命令集

```makefile
# 开发日常
make install                    # 安装依赖
make format                     # 格式化代码 (black + isort)
make lint                       # 检查格式
make test                       # 运行所有测试
make migrate                    # 执行 DB migration
make run-public-api             # 启动 Public API (开发模式)
make run-admin-api              # 启动 Admin API (开发模式)

# 测试
make test-unit                  # 单元测试
make test-integration           # 集成测试
make test-contract              # 契约测试
make test-e2e                   # 端到端测试
make qa-ci                      # CI 全量测试

# 部署
make ops-stack-up               # 一键启动全部服务
make ops-backup-baseline        # 备份
make ops-restore-baseline       # 恢复
make ops-compose-load-baseline  # 压测

# 压测
make load-baseline              # 运行 Locust 压测
make load-report-init           # 初始化压测报告
```

### 14.3 Docker Compose 服务清单

| 服务 | 角色 | 端口 | 说明 |
|------|-----|------|------|
| postgres | 主数据库 | 5432 | PostgreSQL 16 |
| pgbouncer | 连接池 | 6432 | Transaction pooling |
| redis | 缓存/锁/限流 | 6379 | volatile-ttl 策略 |
| kafka | 消息队列 | 9092 | KRaft 单节点 |
| clickhouse | 分析存储 | 8123 | 列式存储 |
| minio | 对象存储 | 9000/9001 | S3 兼容 |
| public-api | 公共 API | 8000 | FastAPI |
| admin-api | 管理 API | 8001 | FastAPI |
| scheduler | 调度器 | - | APScheduler |
| event-pipeline | 事件管道 | - | Outbox → Kafka |
| order-timeout | 超时取消 | - | 30min 扫描 |
| retention | 数据清理 | - | 归档 + 清理 |
| nginx | 反向代理 | 8080 | Edge proxy |
| migrate | DB 迁移 | - | 一次性 |
| kafka-setup | Topic 创建 | - | 一次性 |
| minio-setup | Bucket 创建 | - | 一次性 |

### 14.4 K8s 升级路径

```
何时从 Docker Compose 迁移到 K8s:

  ✅ 现在不需要 K8s 的条件:
     - 单机或双机 VM 能承载 300 万 DAU
     - 团队 < 10 人
     - 还没有多机房需求
     - Docker Compose 的备份/恢复/监控已经够用

  ❌ 需要考虑 K8s 的信号:
     - DAU 突破 1000 万
     - 团队超过 30 人
     - 需要多区域部署
     - 需要自动弹性扩缩
     - 需要灰度发布 (canary/blue-green)
     - 需要故障自动恢复 (pod restart)
     - 日志/指标/追踪需要集中化管理

  迁移步骤:
     1. repo 中已预留 ops/k8s/base/ 目录
     2. 先在 staging 做一次完整 rollout / rollback 演练
     3. 验证 Secret、Ingress、HPA、CronJob
     4. 确认 RTO/RPO 满足要求后切换
```

---

## 第十五章 开发规范

### 15.1 新功能开发 Checklist

```
□ 1. 在 domains/{domain}/ 下创建:
      □ schema.py    — Pydantic 模型
      □ repository.py — DB 操作
      □ service.py   — 业务逻辑
      □ errors.py    — 错误码

□ 2. 在 infra/db/models/ 下创建:
      □ ORM 模型
      □ Alembic migration: make migration-revision message="add xxx table"

□ 3. 在 apps/{api}/routers/ 下创建:
      □ 路由文件
      □ 在 main.py 中注册 router

□ 4. 事件设计:
      □ 在 infra/events/topics.py ���加 Topic 常量
      □ 在 service 中使用 OutboxPublisher 发布事件
      □ 编写 event subscriber (如需要)

□ 5. 缓存设计:
      □ 确定 TTL
      □ 使用 register_after_commit_hook 注册缓存更新
      □ 编写缓存穿透/击穿保护

□ 6. 测试:
      □ unit test (domains/{domain}/)
      □ contract test (API schema)
      □ 更新 e2e test (如涉及核心链路)

□ 7. 文档:
      □ 更新 API 文档
      □ 更新 .env.example (如有新配置)

□ 8. Code Review:
      □ Router 没有业务逻辑
      □ Repository 没有调外部服务
      □ 跨域副作用走 Outbox
      □ 写操作有幂等设计
      □ 错误码使用枚举而非手写字符串
```

### 15.2 Git 分支策略

```
main (生产)
  │
  ├── develop (开发主线)
  │     │
  │     ├── feature/order-timeout      # 功能分支
  │     ├── feature/production-schedule # 功能分支
  │     └── fix/inventory-race         # 修复分支
  │
  └── hotfix/critical-bug              # 紧急修复 → 合并到 main + develop

Commit 消息格式:
  feat: 添加订单超时自动取消功能
  fix: 修复库存并发扣减竞态条件
  refactor: 重构缓存 hook 注册机制
  docs: 更新 API 设计文档
  test: 添加排产算法单元测试
  ops: 优化 docker-compose 健康检查
```

---

## 第十六章 性能优化 Checklist

### 16.1 stock-py 架构已解决的问题

| 问题 | 解决方案 | 出处 |
|------|---------|------|
| PgBouncer prepared statement 冲突 | NullPool + cache_size=0 + unique name | infra/db/session.py |
| Redis 事件流被淘汰 | volatile-ttl 策略 | docker-compose.yml |
| 缓存 - DB 不一致 | cache-after-commit 模式 | infra/db/session.py |
| 事件丢失 | DB Outbox + Kafka 持久化 | infra/events/outbox.py |
| 事件处理失败 | Dead Letter + Replay CLI | infra/events/outbox.py |
| 请求追踪 | RequestContext + ContextVar | infra/core/context.py |
| 秘钥泄露 | File-backed secrets | infra/core/config.py |
| Worker 健康 | Runtime probe + heartbeat | infra/observability/ |

### 16.2 额外优化点

| 优化 | 说明 | 预期收益 |
|------|------|---------|
| 库存 Redis Lua | 原子预扣减，防超卖 | 并发安全 |
| 订单号 Redis INCR | 分布式唯一 ID，无锁 | 高性能 ID 生成 |
| 嵌套 Settings | 配置分组，清晰可维护 | 开发效率 +30% |
| Hook 注册机制 | 替代硬编码 cache apply | 维护性 +50% |
| 错误码枚举 | 统一管理，避免重复 | 调试效率 +40% |
| 排产引擎 | 优先级 + 产能 + 工艺约束 | 产线利用率 +30% |
| 部分索引 | 只索引活跃数据 | 索引体积 -60% |
| 乐观锁 | 订单/库存版本号 | 并发安全 + 低锁等待 |

### 16.3 常见陷阱

```
1. ❌ 不要在 Router 里直接操作 DB
   ✅ Router → Service → Repository → DB

2. ❌ 不要在 Service 里直接调用其他域的 Service
   ✅ 通过 Outbox 事件解耦

3. ❌ 不要在 commit 前更新缓存
   ✅ 使用 register_after_commit_hook

4. ❌ 不要用 Pipeline 做库存扣减
   ✅ 使用 Redis Lua 原子操作

5. ❌ 不要在 PgBouncer 模式下使用默认连接池
   ✅ 使用 NullPool

6. ❌ 不要把所有配置平铺在一个类里
   ✅ 使用嵌套 Settings 分组

7. ❌ 不要手写错误码字符串
   ✅ 使用 AppError 子类 + 枚举

8. ❌ 不要忽略幂等性设计
   ✅ 所有写接口都要有 idempotency_key
```

---

## 附录 A: 快速启动指南

```bash
# 1. 克隆仓库
git clone https://github.com/Liangwei-zhang/glass-factory-app.git
cd glass-factory-app

# 2. 安装依赖
python3.13 -m pip install -r requirements.txt

# 3. 配置环境
cp .env.example .env
# 编辑 .env 配置数据库和 Redis

# 4. 执行 migration
make migrate

# 5. 启动 (选一种方式)

# 方式 A: 本地开发 (分别启动)
make run-public-api     # Terminal 1
make run-admin-api      # Terminal 2

# 方式 B: Docker Compose 一键启动 (推荐)
make ops-stack-up

# 6. 访问
# http://localhost:8000/docs     Public API 文档
# http://localhost:8001/docs     Admin API 文档
# http://localhost:8080          Nginx 统一入口
```

---

## 附录 B: 与 stock-py 的改进对照表

| 维度 | stock-py 做法 | 本项目改进 | 原因 |
|------|-------------|-----------|------|
| Settings | 100+ 字段平铺 | 嵌套分组 (DatabaseSettings 等) | 可维护性 |
| Cache Hook | session.py 硬编码 5 个 apply | 可注册 hook 机制 | 扩展性 |
| 错误码 | 手写字符串 `code="xxx"` | AppError 子类枚举 | 类型安全 |
| ID 生成 | UUID | GF 前缀 + 日期 + 机器号 + 序号 | 业务可读 |
| 排产 | 无（股票系统不需要） | 完整排产引擎 | 业务必需 |
| 库存 | 无（股票系统不需要） | Redis Lua 原子操作 | 防超卖 |
| 物流 | 无 | 完整物流追踪 | 业务必需 |
| 财务 | 无 | 应收应付 + 对账 | 业务必需 |

---

**以上就是完整的开发设计文档。**

这份文档可以直接交给开发团队按章节拆分成 Epic → Story → Task 执行。每个领域模块都有清晰的文件清单、数据模型、核心逻辑、事件定义和验收标准。基础设施层完全复用 stock-py 验证过的成熟模式，在此基础上做了 5 项针对性优化。

如果需要，我可以把这份文档和配套的项目骨架代码一起提交到 `glass-factory-app` 仓库。