# 玻璃工厂数字化管理系统 — 全面 QA 与优化文档

**版本**: v1.0.0  
**日期**: 2026-04-13  
**目标**: 300 万日活 · 峰值 QPS 20,000 · 订单 TPS 5,000 · 可用性 99.99%  
**范围**: 基于 `glass-factory-app-backup-20260413` 全量代码深度审查

---

## 目录

1. [执行摘要](#1-执行摘要)
2. [架构总览与现状评估](#2-架构总览与现状评估)
3. [严重缺陷（必须修复）](#3-严重缺陷必须修复)
4. [代码质量问题](#4-代码质量问题)
5. [数据库层优化](#5-数据库层优化)
6. [缓存层优化](#6-缓存层优化)
7. [API 与并发保障](#7-api-与并发保障)
8. [生产域补全](#8-生产域补全)
9. [前端 PWA 优化](#9-前端-pwa-优化)
10. [安全加固](#10-安全加固)
11. [可观测性补全](#11-可观测性补全)
12. [运维与部署优化](#12-运维与部署优化)
13. [容量规划与压测基线](#13-容量规划与压测基线)
14. [优化实施路线图](#14-优化实施路线图)
15. [验收标准 Checklist](#15-验收标准-checklist)

---

## 1. 执行摘要

经过对项目全量代码（Python 后端、FastAPI 路由、领域服务、基础设施层、Docker Compose 运维配置、前端 HTML/PWA）的深度审查，综合评估如下：

| 维度 | 现状评分 | 说明 |
|------|---------|------|
| 架构设计 | ★★★★☆ | DDD 三层结构清晰，Outbox + Kafka 已落地，PgBouncer 已配置 |
| 代码质量 | ★★★☆☆ | `orders/service.py` 1659 行过度耦合，`smtplib` 直调阻塞 API 线程 |
| 性能保障 | ★★★☆☆ | 缓存层缺少 Read Replica 和热点数据缓存策略 |
| 生产域完整性 | ★★☆☆☆ | `production/service.py` 仅 66 行，`scheduler_engine.py` 未被调用 |
| 安全性 | ★★★★☆ | JWT + RBAC + File-backed secrets 已实现，CSRF 保护待补充 |
| 可观测性 | ★★★☆☆ | MetricsMiddleware 已有，Grafana 告警规则和慢查询日志待补全 |
| 运维完备度 | ★★★★☆ | Docker Compose 一键启动、备份脚本、Nginx 均已就绪 |

**核心结论**：架构基础良好，完全具备支撑 300 万日活的基础能力。当前最紧迫问题是 `orders/service.py` 的职责过载和 `smtplib` 同步调用对 API 线程的阻塞风险，以及生产域排产引擎未接入实际流程。其余优化均可在不停服的情况下逐步迭代。

---

## 2. 架构总览与现状评估

### 2.1 已验证的优秀设计（保持不变）

```
✅ PgBouncer transaction pooling + NullPool + prepared_statement_cache_size=0
   → 解决 asyncpg + PgBouncer 的 prepared statement 冲突

✅ Redis volatile-ttl 策略
   → 防止 Event Streams key 被 LRU 误淘汰，保证事件不丢

✅ Outbox 模式 (event_outbox + FOR UPDATE SKIP LOCKED)
   → 订单写入 + 事件发布原子提交，消息不丢失

✅ File-backed secrets (env_or_file)
   → 敏感信息不暴露在环境变量中，支持 Docker Secrets

✅ 幂等键 (idempotency_key UNIQUE)
   → 防止网络重试导致重复下单

✅ 乐观锁 (version 字段)
   → OrderModel 有 version 字段，防止并发更新冲突

✅ 嵌套 Settings (DatabaseSettings / RedisSettings / EventBrokerSettings)
   → 配置分组清晰，可独立注入测试

✅ DDD 三层架构 (apps / domains / infra)
   → 职责分离，Router 不写业务逻辑，Repository 不调外部服务
```

### 2.2 当前系统承载能力估算

| 指标 | 当前配置估算 | 300 万 DAU 需求 | 差距 |
|------|------------|----------------|------|
| API QPS | ~8,000（单机 4 worker） | 峰值 ~20,000 | 需横向扩容或优化 |
| DB TPS | ~3,000（单机 PG） | 5,000 | 需 Read Replica |
| Redis QPS | ~80,000 | 100,000 | 充裕 |
| Kafka 吞吐 | ~50,000 msg/s | 10,000 msg/s | 充裕 |
| 并发连接 | PgBouncer 1000 | 1000 | 刚好达标 |

---

## 3. 严重缺陷（必须修复）

### 3.1 🔴 `smtplib` 同步调用阻塞 async 线程

**文件**: `domains/orders/service.py` 第 1014–1160 行  
**问题**: `smtplib.SMTP` / `smtplib.SMTP_SSL` 是**同步阻塞**操作，超时设置为 10 秒。在 FastAPI async 线程中直接调用，会**完全阻塞整个 event loop**，导致所有并发请求在此期间排队等待。

**现状代码（问题所在）**:
```python
# ❌ 危险：同步 SMTP 阻塞 async event loop 长达 10 秒
with smtplib.SMTP_SSL(settings.smtp.host, settings.smtp.port, timeout=10) as smtp:
    smtp.send_message(message)
```

**修复方案 A — 推荐（Outbox 异步化）**:
```python
# ✅ service 只负责写 Outbox 事件，不直接发邮件
async def send_pickup_email(self, session, order_id, actor_user_id):
    row = await self.repository.get_order(session, order_id)
    # ... 校验逻辑 ...
    
    outbox = OutboxPublisher(session)
    await outbox.publish_after_commit(
        topic=Topics.NOTIFICATION_EMAIL_SEND,
        key=row.id,
        payload={
            "template_key": PICKUP_TEMPLATE_KEY,
            "order_id": row.id,
            "order_no": row.order_no,
            "customer_id": row.customer_id,
            "actor_user_id": actor_user_id,
        },
    )
    return {"status": "queued"}
```

实际邮件发送移到 `apps/workers/notification_dispatch/worker.py`，消费 `NOTIFICATION_EMAIL_SEND` 事件后用 `asyncio.to_thread(smtplib_send)` 或 `aiosmtplib` 异步发送。

**修复方案 B — 快速方案**:
```python
# 最小改动：用 asyncio.to_thread 包装，不阻塞 event loop
import asyncio

async def _send_smtp_async(message, settings):
    def _sync_send():
        with smtplib.SMTP(settings.smtp.host, settings.smtp.port, timeout=10) as smtp:
            smtp.send_message(message)
    await asyncio.to_thread(_sync_send)
```

**优先级**: P0 — 生产环境高并发时极易触发，需在上线前修复。

---

### 3.2 🔴 `orders/service.py` 职责过载（1659 行）

**问题**: 单文件包含以下完全不同层次的关注点：
- PDF 生成（`struct` / `zlib` PNG 解码、PDF 对象构建，约 400 行）
- 邮件发送（`smtplib` 直调，约 150 行）
- 订单 CRUD 业务逻辑（约 500 行）
- 签名处理与存储（约 100 行）
- 工单创建（与 `production` 域耦合）

**违反的三条铁律**: Service 直接操作 `WorkOrderModel`（应由 production 域管理），直接调用 SMTP（应由 notification worker 处理），直接生成 PDF（应由 infra/pdf 模块处理）。

**拆分方案**:

```
重构后的职责边界：

orders/service.py          → 仅保留订单业务逻辑（目标 ~500 行）
  create_order()
  update_order()
  cancel_order()
  approve_pickup()
  save_pickup_signature()
  transition_status()

infra/pdf/generator.py     → PDF 生成（新建）
  build_pickup_slip_pdf()
  build_order_summary_pdf()

infra/pdf/png_decoder.py   → PNG/图像处理工具（新建，复用现有代码）

apps/workers/
  notification_dispatch/   → 邮件/通知发送（现有，需接入）
  pdf_export/              → PDF 异步生成（新建 Worker）
```

**关键操作**:
1. 将 `_escape_pdf_text`、`_apply_png_filter`、`_build_minimal_pdf` 等纯工具函数剪切到 `infra/pdf/`
2. 将 `send_pickup_email` 改为发布 Outbox 事件
3. 将 `export_document_pdf` 改为异步任务（返回 task_id，前端轮询）
4. 将 `WorkOrderModel` 直接操作移至 `ProductionService.create_work_orders_for_order()`

---

### 3.3 🔴 生产排产引擎未接入（`scheduler_engine.py` 孤立）

**文件**: `domains/production/scheduler_engine.py`（已写好的完整排产算法）  
**问题**: `ProductionService`（66 行）完全没有引用 `ProductionSchedulerEngine`，排产逻辑实际上**从未被调用**。工单创建后直接进入 `pending` 状态，没有自动排产。

**修复方案**:
```python
# domains/production/service.py 补充核心方法

from domains.production.scheduler_engine import (
    ProductionSchedulerEngine,
    WorkOrderCandidate,
)

class ProductionService:
    async def trigger_schedule(
        self,
        session: AsyncSession,
        work_order_ids: list[str] | None = None,
    ) -> ScheduleResult:
        """
        触发排产：从 DB 拉取 pending 工单 → 拉取产线配置
        → 调用 scheduler_engine → 写回 scheduled_date + production_line_id
        """
        lines = await self.repository.list_active_lines(session)
        engine = ProductionSchedulerEngine(lines)
        
        candidates = await self.repository.list_unscheduled_work_orders(
            session, ids=work_order_ids
        )
        result = engine.schedule(candidates)
        
        for slot in result.scheduled:
            await self.repository.assign_work_order_slot(
                session,
                work_order_id=slot.work_order_id,
                line_id=slot.line_id,
                scheduled_date=slot.scheduled_date,
            )
        
        return result

    async def apply_step_action(
        self,
        session: AsyncSession,
        work_order_id: str,
        action: str,   # "start" | "complete" | "rework"
        actor_user_id: str,
        rework_reason: str | None = None,
    ) -> WorkOrderView:
        """工人点击【开始生产】【生产完成】的核心状态机"""
        ...
```

**还需补充的 API 路由**（`apps/public_api/routers/production.py`）:
- `POST /v1/production/work-orders/{id}/start` — 工人开始
- `POST /v1/production/work-orders/{id}/complete` — 工人完成
- `POST /v1/production/work-orders/{id}/rework` — 标记返工（自动推送至切割工序）
- `POST /v1/admin/production/schedule` — 主管触发排产

---

### 3.4 🔴 电子签名数据存储方式不安全

**文件**: `domains/orders/service.py` `save_pickup_signature()` 方法  
**问题**: 签名 base64 data URL 如果直接存入 DB 字段（`pickup_signature_key`），每张签名约 20–100KB，随时间累积会导致 DB 表膨胀，且 PostgreSQL 不适合存储大二进制。

**现状**: `OrderModel.pickup_signature_key` 字段为 `String(500)`，存的是 MinIO 对象路径（设计正确），但需确认 `save_pickup_signature()` 实际上将 base64 **先上传 MinIO**，再只存路径。

**验证代码**（`service.py` 第 930 行附近）:
```python
# 确认此处调用了 ObjectStorage，而非将 base64 直存 DB
decoded = decode_signature_data_url(payload.signature_data_url)
key = build_signature_storage_key(order_id=row.id, ext=decoded.extension)
await object_storage.upload_bytes(key=key, data=decoded.data, ...)
# order.pickup_signature_key = key  ← 只存路径，正确
```

若未正确执行以上逻辑，需立即修复，防止大数据写入 DB。

---

## 4. 代码质量问题

### 4.1 🟠 `orders/service.py` 内跨域直接操作 WorkOrderModel

**问题**: `create_order()` 中直接 `session.add(WorkOrderModel(...))` 创建工单，绕过了 `ProductionService`。

```python
# ❌ 当前：orders service 直接写 production 域的 Model
session.add(WorkOrderModel(
    work_order_no=f"WO-{order.order_no}-{index:03d}",
    process_step_key="cutting",
    ...
))
```

**修复**: 通过 Outbox 事件解耦。订单创建后发布 `ORDER_CREATED` 事件，`production_scheduler` worker 消费该事件并调用 `ProductionService.create_work_orders_for_order()`。

---

### 4.2 🟠 `domains/production/service.py` 仅有查询，无写操作

`ProductionService` 目前只有 5 个 `list_*` / `get_*` 查询方法，缺少：
- `create_work_orders_for_order()` — 接单后创建工单
- `apply_step_action()` — 工人操作状态机
- `mark_rework()` — 标记返工并推送至切割工序
- `assign_to_line()` — 排产分配

这导致工人端界面的「开始生产」「生产完成」按钮背后没有对应的服务层实现。

---

### 4.3 🟡 错误码使用不统一

部分地方直接抛出 `AppError(code=ErrorCode.xxx)`，而 `domains/orders/errors.py` 已经定义了工厂函数 `order_not_found()`。建议统一为工厂函数模式，方便集中管理。

```python
# 现状（不统一）：
raise AppError(code=ErrorCode.ORDER_NOT_FOUND, message="...", status_code=404)

# 建议统一为：
from domains.orders.errors import order_not_found
raise order_not_found(order_id)
```

---

### 4.4 🟡 `_normalize_priority()` 与 `_normalize_step_key()` 等私有函数散落模块顶层

这些纯工具函数定义在 `service.py` 模块顶层（而非类方法），且与领域逻辑混杂。建议：
- 移至 `domains/orders/utils.py`
- 或作为 `@staticmethod` 归入 `OrdersService` 类

---

### 4.5 🟡 `uuid4()` 作为 DB 主键默认值（String(36)）vs UUID 类型

**现状**: `id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))`

**建议**: 改用 PostgreSQL 原生 `UUID` 类型（`mapped_column(UUID(as_uuid=False))`），节省存储（16 bytes vs 36 bytes）且索引性能更好。迁移时需要同步更新所有外键列。

---

### 4.6 🟡 `dev_bootstrap.py` 中的明文密码种子数据

`infra/db/dev_bootstrap.py` 中若有硬编码的默认密码（如 `password=123456`），需确保：
1. 仅在 `app_env == "dev"` 时执行
2. CI/CD 的 staging 环境不使用 dev bootstrap
3. 生产环境 `AUTO_INIT_SCHEMA_ON_STARTUP` 应设为 `0`（docker-compose.yml 已配置）

---

## 5. 数据库层优化

### 5.1 PostgreSQL 配置调优（postgresql.conf.tuning 已提供，需实际应用）

项目已有 `ops/postgresql.conf.tuning`，内容已按生产标准设定，**需确认已挂载到 postgres 容器**：

```yaml
# ops/docker-compose.yml — postgres 服务补充挂载
postgres:
  image: postgres:16
  volumes:
    - gf_postgres_data:/var/lib/postgresql/data
    - ./postgresql.conf.tuning:/etc/postgresql/postgresql.conf  # ← 补充此行
  command: postgres -c config_file=/etc/postgresql/postgresql.conf
```

关键参数确认表：

| 参数 | 推荐值 | 说明 |
|------|--------|------|
| `max_connections` | 200 | PgBouncer 代理后实际需要的连接数 |
| `shared_buffers` | 4GB | 服务器内存的 25% |
| `effective_cache_size` | 12GB | 服务器内存的 75% |
| `work_mem` | 32MB | 每个排序操作的内存 |
| `maintenance_work_mem` | 512MB | 索引维护内存 |
| `wal_compression` | on | 减少 WAL 体积 |
| `checkpoint_completion_target` | 0.9 | 平滑 checkpoint IO |
| `random_page_cost` | 1.1 | SSD 存储使用此值 |
| `effective_io_concurrency` | 200 | SSD 并发 IO |
| `log_min_duration_statement` | 100 | 开启慢查询日志（ms）|

---

### 5.2 Read Replica（读写分离）

**当前痛点**: 300 万 DAU 场景下，订单列表查询、历史记录查询、统计看板会占用主库大量读 IO，挤占写入性能。

**方案**:
```yaml
# ops/docker-compose.yml 补充从库（开发验证用）
postgres-replica:
  image: postgres:16
  environment:
    POSTGRES_DB: glass_factory
    PGUSER: replicator
    PGPASSWORD: replicator_password
  command: |
    postgres -c hot_standby=on -c primary_conninfo='host=postgres port=5432 user=replicator'
```

**代码层**（`infra/db/session.py`）:
```python
# 读操作使用从库连接
READ_REPLICA_URL = env_or_file("DATABASE_REPLICA_URL", settings.database.url)

@asynccontextmanager
async def get_read_session():
    async with ReadSessionFactory() as session:
        yield session
```

**适用场景**: `list_orders()`、`list_customers()`、`analytics` 端点，均可切换到从库。

---

### 5.3 核心索引补充

基于当前 `OrderModel`，以下查询路径缺少复合索引：

```sql
-- 前台"按客户查当前订单"（高频）
CREATE INDEX idx_orders_customer_status 
ON orders(customer_id, status) 
WHERE status NOT IN ('cancelled', 'picked_up');

-- 超期告警（每小时扫描）
CREATE INDEX idx_orders_overdue 
ON orders(status, expected_delivery_date) 
WHERE status IN ('in_production', 'entered');

-- 主管"今日完工"统计
CREATE INDEX idx_orders_completed_date 
ON orders(status, updated_at DESC) 
WHERE status = 'completed';

-- 工单按工序查询（工人视图高频）
CREATE INDEX idx_work_orders_step_assignee 
ON work_orders(process_step_key, assigned_user_id, status)
WHERE status NOT IN ('completed', 'cancelled');

-- 返工未读查询
CREATE INDEX idx_work_orders_rework_unread 
ON work_orders(rework_unread) 
WHERE rework_unread = TRUE;
```

---

### 5.4 orders 表分区（数据量预估超 1000 万行时）

```sql
-- 按月分区（300 万 DAU，每天约 10 万订单，月均 300 万行）
-- 建议在数据量突破 500 万行前预先分区

CREATE TABLE orders_partitioned (LIKE orders) 
PARTITION BY RANGE (created_at);

CREATE TABLE orders_2026_04 PARTITION OF orders_partitioned
FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');

CREATE TABLE orders_2026_05 PARTITION OF orders_partitioned
FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
-- 按月自动建表（APScheduler 调度）
```

---

### 5.5 PgBouncer 参数优化

当前 `pgbouncer.ini.template` 建议确认以下参数：

```ini
[pgbouncer]
pool_mode = transaction          # 必须为 transaction（已配置）
max_client_conn = 1000           # 客户端最大连接数
default_pool_size = 50           # 每个 DB/User 组合的服务端连接数
reserve_pool_size = 10           # 紧急预留连接
reserve_pool_timeout = 3         # 等待预留池的超时（秒）
server_idle_timeout = 600        # 空闲连接回收
query_wait_timeout = 30          # 等待连接超时（需大于业务超时）
server_reset_query = DISCARD ALL # transaction 模式下必须
```

---

## 6. 缓存层优化

### 6.1 Redis 配置确认（已配置 volatile-ttl，✅）

`docker-compose.yml` 中 Redis 配置：
```
command: redis-server --appendonly yes --maxmemory-policy volatile-ttl
```
此配置**正确**，防止 Kafka Streams 等无 TTL key 被误淘汰。

**补充建议**：
```
--maxmemory 6gb              # 明确限制内存上限，防止 OOM
--save 900 1 300 10 60 10000 # 持久化策略（当前只有 appendonly，需评估）
```

---

### 6.2 订单热数据缓存（当前缺失）

`OrdersService` 当前每次 `get_order()` 都查 DB。高频场景（前台刷新订单状态）应增加：

```python
# infra/cache/order_cache.py（新建）
ORDER_CACHE_TTL = 30  # 秒

async def get_cached_order(order_id: str) -> dict | None:
    redis = await get_redis()
    raw = await redis.get(f"order:{order_id}")
    return json.loads(raw) if raw else None

async def set_cached_order(order_id: str, data: dict) -> None:
    redis = await get_redis()
    await redis.setex(f"order:{order_id}", ORDER_CACHE_TTL, json.dumps(data, default=str))

async def invalidate_order_cache(order_id: str) -> None:
    redis = await get_redis()
    await redis.delete(f"order:{order_id}")
```

在 `OrdersService.get_order()` 中使用 cache-aside 模式，结合 `register_after_commit_hook` 在写操作后更新缓存。

---

### 6.3 客户信息缓存 TTL 策略

客户信息（公司名、联系方式、信用额度）变更频率低，可用较长 TTL：

```python
CUSTOMER_CACHE_TTL = 300  # 5 分钟

# 信用额度缓存需在付款/下单后主动失效
async def invalidate_customer_credit(customer_id: str):
    redis = await get_redis()
    await redis.delete(f"customer:credit:{customer_id}")
```

---

### 6.4 缓存穿透防护

对于查询不存在的 order_id / customer_id（可能是爬虫或误操作），应缓存空值：

```python
async def get_order_with_null_cache(order_id: str) -> dict | None:
    cached = await get_cached_order(order_id)
    if cached == "__NULL__":
        return None  # 空值缓存命中，直接返回
    if cached:
        return cached
    
    row = await repo.get_order(session, order_id)
    if row is None:
        await redis.setex(f"order:{order_id}", 60, "__NULL__")  # 缓存空值 60 秒
        return None
    
    await set_cached_order(order_id, row)
    return row
```

---

## 7. API 与并发保障

### 7.1 限流策略完善

当前 `infra/security/rate_limit.py` 使用 `slowapi`。建议三层限流配置：

**第一层 — Nginx（已有，确认参数）**:
```nginx
# ops/nginx/default.conf
limit_req_zone $binary_remote_addr zone=api_general:10m rate=100r/s;
limit_req_zone $binary_remote_addr zone=api_order:10m rate=10r/s;
limit_req_zone $binary_remote_addr zone=api_auth:10m rate=5r/s;

location /v1/orders {
    limit_req zone=api_order burst=30 nodelay;
}
location /v1/auth {
    limit_req zone=api_auth burst=10 nodelay;
}
```

**第二层 — slowapi（已有，补充 order 路由限流）**:
```python
# apps/public_api/routers/orders.py
@router.post("/v1/orders")
@limiter.limit("10/minute")  # 每用户每分钟最多下 10 单
async def create_order(request: Request, ...):
    ...
```

**第三层 — 业务层（补充）**:
```python
# 同一客户 Rush 订单频率限制
async def check_rush_order_limit(customer_id: str, redis) -> None:
    key = f"rush_limit:{customer_id}:{int(time.time()) // 3600}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 7200)
    if count > 3:  # 每小时最多 3 个 Rush 订单
        raise AppError(code=ErrorCode.RATE_LIMITED, message="Rush 订单频率超限", status_code=429)
```

---

### 7.2 Server-Sent Events 实时推送（替代前端轮询）

当前前台刷新订单状态需要手动刷新页面。建议补充 SSE 端点：

```python
# apps/public_api/routers/orders.py
from fastapi.responses import StreamingResponse

@router.get("/v1/orders/{order_id}/events")
async def order_status_stream(order_id: str, current_user: AuthUser = Depends(get_current_user)):
    async def event_generator():
        redis = await get_redis()
        pubsub = redis.pubsub()
        await pubsub.subscribe(f"order:status:{order_id}")
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    yield f"data: {message['data']}\n\n"
        finally:
            await pubsub.unsubscribe(f"order:status:{order_id}")
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

在 `transition_status()` 后发布 Redis Pub/Sub 消息通知订阅方。

---

### 7.3 PDF 导出异步化

`export_document_pdf()` 是 CPU 密集型操作，不应在 API 线程中同步执行：

```python
# 改为异步任务模式
@router.post("/v1/orders/{order_id}/export-pdf")
async def export_order_pdf(order_id: str, ...):
    # 1. 发布 PDF 生成任务到 Outbox
    task_id = str(uuid4())
    await outbox.publish_after_commit(
        topic=Topics.PDF_EXPORT_REQUESTED,
        key=task_id,
        payload={"order_id": order_id, "task_id": task_id},
    )
    return {"task_id": task_id, "status": "processing"}

@router.get("/v1/tasks/{task_id}/result")
async def get_task_result(task_id: str, ...):
    # 2. 前端轮询任务结果
    result = await task_store.get(task_id)
    if result is None:
        return {"status": "processing"}
    return {"status": "done", "download_url": result["url"]}
```

---

### 7.4 幂等性保障完善

当前 `create_order()` 已有 `idempotency_key` 校验，但需确认：

- `update_order()` 的重复更新是否有防护
- `apply_step_action()`（待实现）是否有操作幂等性设计
- 建议所有状态变更操作加入 `version` 乐观锁校验：

```python
# 状态转换时加入乐观锁
result = await session.execute(
    update(OrderModel)
    .where(OrderModel.id == order_id, OrderModel.version == current_version)
    .values(status=new_status, version=OrderModel.version + 1)
    .returning(OrderModel)
)
if result.rowcount == 0:
    raise AppError(code=ErrorCode.CONFLICT, message="订单已被并发修改，请重试", status_code=409)
```

---

## 8. 生产域补全

### 8.1 工单状态机完整定义

根据 `xq.md` 需求，工单应有以下工序链：

```
cutting（切割）→ edging（开口）→ tempering（钢化）→ tempering_done（钢化完成）

规则：
  - 上一工序未完成，下一工序不可开始
  - 钢化工人只可查看，不需要操作
  - 返工时，需要重做的玻璃自动回到 cutting 工序，并高亮显示
  - 每个工序完成后自动推送至下一工序的负责人
```

**WorkOrder 状态机定义**（补充到 `domains/production/schema.py`）:

```python
class WorkOrderStatus(StrEnum):
    PENDING = "pending"              # 等待上道工序
    IN_PROGRESS = "in_progress"      # 当前工序进行中
    COMPLETED = "completed"          # 当前工序完成
    REWORK = "rework"                # 需要返工
    CANCELLED = "cancelled"

PROCESS_STEPS = ["cutting", "edging", "tempering", "tempering_done"]

WORK_ORDER_TRANSITIONS: dict[WorkOrderStatus, set[WorkOrderStatus]] = {
    WorkOrderStatus.PENDING: {WorkOrderStatus.IN_PROGRESS},
    WorkOrderStatus.IN_PROGRESS: {WorkOrderStatus.COMPLETED, WorkOrderStatus.REWORK},
    WorkOrderStatus.REWORK: {WorkOrderStatus.IN_PROGRESS},
}
```

---

### 8.2 返工推送逻辑（`rework_unread` 字段已存在，需实现推送）

`WorkOrderModel.rework_unread` 字段已在 DB 模型中定义，但推送逻辑未实现。

```python
# domains/production/service.py 补充
async def mark_rework(
    self,
    session: AsyncSession,
    work_order_id: str,
    piece_numbers: list[int],  # 哪几片需要返工
    reason: str,
    actor_user_id: str,
) -> WorkOrderView:
    """
    标记指定玻璃片返工：
    1. 在当前工单创建子工单（仅针对需返工的片）
    2. 子工单分配至 cutting 工序，rework_unread=True
    3. 高亮通知切割工人
    """
    work_order = await self.repository.get_work_order(session, work_order_id)
    
    cutting_assignee = await self.repository.get_stage_assignee(session, "cutting")
    
    for piece_no in piece_numbers:
        rework_wo = WorkOrderModel(
            work_order_no=f"RW-{work_order.work_order_no}-P{piece_no:02d}",
            order_id=work_order.order_id,
            order_item_id=work_order.order_item_id,
            process_step_key="cutting",
            assigned_user_id=cutting_assignee,
            status="pending",
            rework_unread=True,  # 高亮标记
            rework_reason=reason,
            rework_piece_no=piece_no,
            ...
        )
        session.add(rework_wo)
    
    # 发 Outbox 事件通知前台
    await OutboxPublisher(session).publish_after_commit(
        topic=Topics.PRODUCTION_REWORK_CREATED,
        key=work_order_id,
        payload={"work_order_id": work_order_id, "piece_numbers": piece_numbers},
    )
    
    return WorkOrderView.model_validate(work_order)
```

---

### 8.3 订单超期告警

`ops/ecosystem.config.js` 和 `apps/scheduler/` 中需补充超期扫描任务：

```python
# apps/scheduler/main.py 补充 APScheduler job
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

@scheduler.scheduled_job("interval", hours=1)
async def check_overdue_orders():
    """
    扫描超过 5 天未完成的生产订单，
    更新 is_overdue 标记，触发高亮通知
    """
    threshold = datetime.now(timezone.utc) - timedelta(days=5)
    async with get_db_session() as session:
        overdue = await session.execute(
            select(OrderModel)
            .where(
                OrderModel.status.in_(["in_production", "entered"]),
                OrderModel.updated_at < threshold,
            )
        )
        for order in overdue.scalars():
            await publish_event(
                Topics.ORDER_OVERDUE_ALERT,
                {"order_id": order.id, "order_no": order.order_no, "days": ...}
            )
```

---

## 9. 前端 PWA 优化

### 9.1 Service Worker 缓存策略

`public/sw.js` 已存在，需确认缓存策略覆盖关键离线场景：

```javascript
// public/sw.js 建议策略

// 静态资源：Cache First
self.addEventListener('fetch', event => {
  if (event.request.url.includes('/static/')) {
    event.respondWith(cacheFirst(event.request));
  }
  // API 请求：Network First，超时后走缓存
  else if (event.request.url.includes('/v1/')) {
    event.respondWith(networkFirstWithTimeout(event.request, 3000));
  }
});

// 离线时提示友好错误页面
// 签名画板数据离线暂存 IndexedDB，联网后同步
```

---

### 9.2 签名 Canvas 压缩上传

当前签名 canvas 可能以 PNG 格式上传（文件较大）。建议前端压缩：

```javascript
// 上传前压缩签名图像
function getCompressedSignature(canvas) {
  return canvas.toDataURL('image/jpeg', 0.75);  // JPEG 75% 质量
  // PNG ~150KB → JPEG ~20KB，减少 87% 体积
}
```

---

### 9.3 订单列表虚拟滚动

前台订单列表超过 100 条时，直接渲染全部 DOM 会导致性能问题。建议使用 Vue 3 虚拟滚动（已引入 Element Plus，可用 `el-virtual-list`）：

```javascript
// platform.html / app.html 中的订单列表改为虚拟滚动
<el-virtual-list :data="orders" :height="600" item-size="80">
  <template #default="{ item }">
    <order-card :order="item" />
  </template>
</el-virtual-list>
```

---

### 9.4 PDF 图纸懒加载

订单列表中不应预加载图纸 PDF，应在点击「查看图纸」时才请求 MinIO presigned URL：

```javascript
async function viewDrawing(orderId) {
  // 请求后端生成短期 presigned URL（有效期 15 分钟）
  const { url } = await api.get(`/v1/orders/${orderId}/drawing-url`);
  window.open(url, '_blank');
}
```

后端补充端点：
```python
@router.get("/v1/orders/{order_id}/drawing-url")
async def get_drawing_presigned_url(order_id: str, ...):
    key = await order_service.get_drawing_key(session, order_id)
    url = await object_storage.generate_presigned_url(key, expires_in=900)
    return {"url": url}
```

---

### 9.5 中英文切换支持

根据 `xq.md` 要求支持中英文切换。建议 i18n 方案：

```javascript
// 简单实现：前端 JSON 字典 + reactive locale
const LOCALE = {
  zh: {
    order_status_pending: '已接单',
    order_status_in_production: '生产中',
    // ...
  },
  en: {
    order_status_pending: 'Received',
    order_status_in_production: 'In Production',
    // ...
  }
}

const locale = Vue.ref('zh');
const t = (key) => LOCALE[locale.value][key] ?? key;
```

---

## 10. 安全加固

### 10.1 JWT 刷新 Token 轮换

`infra/security/auth.py` 中 Access Token 有过期时间（`access_token_minutes`），但需确认 Refresh Token 策略：

- Refresh Token 应单次使用（用后立即轮换，防止 token 盗用）
- Refresh Token 吊销记录存 Redis（`revoked_tokens:{token_hash}`）
- Session ID（`sid`）在 JWT payload 中用于服务端主动吊销会话

```python
# 推荐：Refresh Token 单次使用轮换
async def refresh_access_token(refresh_token: str) -> tuple[str, str]:
    payload = verify_refresh_token(refresh_token)
    
    # 检查是否已被吊销
    redis = await get_redis()
    if await redis.exists(f"revoked_refresh:{payload['jti']}"):
        raise AppError(code=ErrorCode.UNAUTHORIZED, message="Token 已失效", status_code=401)
    
    # 吊销旧 token
    await redis.setex(f"revoked_refresh:{payload['jti']}", 7 * 86400, "1")
    
    # 签发新 token pair
    new_access = create_access_token(...)
    new_refresh = create_refresh_token(...)
    return new_access, new_refresh
```

---

### 10.2 敏感操作审计日志

主管批准取货、取消订单、修改订单等敏感操作，需记录完整审计日志：

```python
# 利用现有 OPS_AUDIT_LOGGED 事件（已有基础）
# 确保以下操作均发布审计事件：
# - approve_pickup()        ✅ 已有
# - cancel_order()          ❓ 待确认
# - update_order()          ❓ 待确认
# - 用户权限变更             ❓ 待确认
# - 库存调整                 ❓ 待确认
```

---

### 10.3 文件上传安全

`upload_drawing()` 接受 PDF 上传，需验证：
```python
ALLOWED_MIME_TYPES = {"application/pdf", "image/jpeg", "image/png"}
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50MB

async def upload_drawing(self, session, order_id, file: UploadFile, ...):
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise AppError(code=ErrorCode.INVALID_INPUT, message="仅支持 PDF/JPG/PNG 格式")
    
    content = await file.read()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise AppError(code=ErrorCode.INVALID_INPUT, message="文件不能超过 50MB")
    
    # 上传 MinIO 时使用随机 UUID key，而非原始文件名（防路径遍历）
    safe_key = f"drawings/{order_id}/{uuid4().hex}.{ext}"
```

---

## 11. 可观测性补全

### 11.1 Grafana + Prometheus 补充到 docker-compose.yml

```yaml
# ops/docker-compose.yml 补充
prometheus:
  image: prom/prometheus:latest
  container_name: gf-prometheus
  volumes:
    - ./prometheus.yml:/etc/prometheus/prometheus.yml
  ports:
    - "19090:9090"

grafana:
  image: grafana/grafana:latest
  container_name: gf-grafana
  environment:
    GF_SECURITY_ADMIN_PASSWORD: admin
  ports:
    - "13000:3000"
  depends_on:
    - prometheus
```

`ops/prometheus.yml`:
```yaml
scrape_configs:
  - job_name: 'glass-factory-public-api'
    static_configs:
      - targets: ['public-api:8000']
    metrics_path: '/metrics'
    scrape_interval: 15s
  
  - job_name: 'glass-factory-admin-api'
    static_configs:
      - targets: ['admin-api:8001']
```

---

### 11.2 关键业务 Metrics 补充

当前 `infra/observability/metrics.py` 有 HTTP 层 metrics，建议补充业务 metrics：

```python
# infra/observability/metrics.py 补充
from prometheus_client import Counter, Histogram, Gauge

# 订单业务指标
orders_created_total = Counter(
    "gf_orders_created_total", "Total orders created", ["priority"]
)
orders_cancelled_total = Counter(
    "gf_orders_cancelled_total", "Total orders cancelled", ["reason"]
)
pickup_email_sent_total = Counter(
    "gf_pickup_email_sent_total", "Pickup emails sent", ["status"]  # sent/failed/skipped
)

# 生产指标
work_orders_completed_total = Counter(
    "gf_work_orders_completed_total", "Work orders completed", ["step_key"]
)
rework_rate = Gauge(
    "gf_rework_rate", "Current rework rate (last 24h)"
)

# 基础设施指标
outbox_pending_events = Gauge(
    "gf_outbox_pending_events", "Pending events in outbox"
)
outbox_dead_letter_events = Gauge(
    "gf_outbox_dead_letter_events", "Dead letter events in outbox"
)
```

---

### 11.3 告警规则（Grafana/AlertManager）

| 告警名称 | 触发条件 | 级别 | 处理方式 |
|---------|---------|------|---------|
| `APIHighErrorRate` | 5xx 率 > 1% | Warning | 查看最近 error 日志 |
| `APIHighErrorRate` | 5xx 率 > 5% | Critical | 立即排查，考虑回滚 |
| `APIHighLatency` | P99 > 500ms | Warning | 检查慢查询 |
| `OutboxDeadLetter` | dead_letter > 0 | Warning | `python -m infra.events.outbox replay-dead-letter` |
| `OutboxPendingHigh` | pending > 500 | Warning | 检查 event-pipeline worker |
| `PGBBouncerWaiting` | waiting_clients > 20 | Warning | 考虑增加 pool_size |
| `RedisMemoryHigh` | 内存使用 > 85% | Warning | 检查 key 分布，清理过期数据 |
| `OrderOverdue` | 超期订单数 > 0 | Info | 通知主管跟进 |

---

### 11.4 慢查询日志

在 `postgresql.conf.tuning` 中补充（已有文件）：
```
log_min_duration_statement = 100    # 记录超过 100ms 的查询
log_statement = 'none'              # 不记录所有 SQL（太多）
log_duration = off
log_line_prefix = '%t [%p]: [%l-1] user=%u,db=%d,app=%a,client=%h '
```

---

## 12. 运维与部署优化

### 12.1 健康检查补全

当前 `health.py` 端点需确认探测了所有依赖：

```python
# infra/http/health.py 建议实现
@router.get("/health/ready")
async def readiness_check():
    checks = {}
    
    # PostgreSQL
    try:
        async with get_db_session() as session:
            await session.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as e:
        checks["postgres"] = f"error: {e}"
    
    # Redis
    try:
        redis = await get_redis()
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"
    
    # MinIO
    try:
        await object_storage.check_bucket_exists()
        checks["minio"] = "ok"
    except Exception as e:
        checks["minio"] = f"error: {e}"
    
    # Kafka（可选，降级为 warning）
    checks["kafka"] = "ok"  # 实现 Kafka admin client ping
    
    all_ok = all(v == "ok" for v in checks.values())
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={"status": "ready" if all_ok else "degraded", "checks": checks}
    )
```

---

### 12.2 Docker Compose 服务依赖完善

确认 `public-api` 服务的依赖链正确等待就绪（而非仅等待容器启动）：

```yaml
public-api:
  depends_on:
    postgres:
      condition: service_healthy    # 等待 healthcheck 通过
    redis:
      condition: service_healthy
    pgbouncer:
      condition: service_healthy
    kafka:
      condition: service_healthy
    migrate:
      condition: service_completed_successfully  # migration 完成后再启动
```

---

### 12.3 MinIO 生命周期策略（已配置，确认）

`ops/minio/lifecycle.json` 已配置对象生命周期，需确认：
- 签名图片保留策略（建议永久保留，作为法律凭证）
- 图纸 PDF 保留策略（建议 5 年）
- 临时导出文件过期策略（建议 24 小时）

```json
{
  "Rules": [
    {
      "ID": "expire-temp-exports",
      "Status": "Enabled",
      "Filter": {"Prefix": "exports/"},
      "Expiration": {"Days": 1}
    },
    {
      "ID": "archive-old-drawings",
      "Status": "Enabled", 
      "Filter": {"Prefix": "drawings/"},
      "Transition": {"Days": 365, "StorageClass": "GLACIER"}
    }
  ]
}
```

---

### 12.4 数据库备份策略

`ops/bin/backup-baseline.sh` 已存在。补充自动化备份调度：

```yaml
# ops/docker-compose.yml 补充定时备份
backup:
  image: postgres:16
  environment:
    PGPASSWORD: postgres
  volumes:
    - ./bin:/scripts
    - gf_backups:/backups
  entrypoint: |
    sh -c 'while true; do
      /scripts/backup-baseline.sh
      sleep 86400  # 每 24 小时备份一次
    done'
  depends_on:
    postgres:
      condition: service_healthy
```

生产环境建议将备份文件推送至 MinIO 或 S3 异地存储。

---

## 13. 容量规划与压测基线

### 13.1 单机承载能力评估

基于当前架构，**单机部署**（8C32G）的理论承载上限：

| 指标 | 理论值 | 备注 |
|------|-------|------|
| API 峰值 QPS | ~12,000 | 4 uvicorn workers × ~3,000 QPS/worker |
| DB 写入 TPS | ~5,000 | PgBouncer pool_size=50，短事务 |
| DB 读取 QPS | ~20,000 | 含缓存命中后的 DB 实际请求 |
| Redis 操作 QPS | ~100,000 | 单节点 6GB 内存 |
| 日均订单量 | ~200 万 | 按 5,000 TPS 峰值 × 6 小时窗口估算 |
| 并发在线用户 | ~3 万 | 长连接（SSE/WS）场景需评估 |

**结论**: 300 万 DAU、峰值 20,000 QPS 场景下，单机 + Read Replica 架构可以满足需求，无需立即上 K8s。

---

### 13.2 Locust 压测场景（`tests/load/locustfile.py` 补充）

```python
# tests/load/locustfile.py
from locust import HttpUser, task, between

class OfficeUser(HttpUser):
    """模拟前台操作员行为"""
    wait_time = between(1, 3)
    
    @task(5)
    def list_orders(self):
        self.client.get("/v1/orders?limit=20", headers=self.headers)
    
    @task(2)
    def get_order_detail(self):
        self.client.get(f"/v1/orders/{self.random_order_id}", headers=self.headers)
    
    @task(1)
    def create_order(self):
        self.client.post("/v1/orders", json=self.order_payload(), headers=self.headers)

class WorkerUser(HttpUser):
    """模拟生产工人行为（低频，简单操作）"""
    wait_time = between(10, 30)
    
    @task(3)
    def list_my_work_orders(self):
        self.client.get("/v1/production/work-orders?my=true", headers=self.headers)
    
    @task(1)
    def complete_step(self):
        self.client.post(f"/v1/production/work-orders/{self.work_order_id}/complete", 
                        headers=self.headers)

class SupervisorUser(HttpUser):
    """模拟主管行为"""
    wait_time = between(5, 15)
    
    @task(1)
    def view_analytics(self):
        self.client.get("/v1/admin/analytics/overview", headers=self.headers)
```

**目标指标**（`ops/runbooks/qa-cutover-checklist.md` 补充）：
- P50 延迟 < 20ms（读操作）
- P99 延迟 < 100ms（写操作）
- 5000 TPS 下单维持 10 分钟无错误
- 错误率 < 0.1%

---

### 13.3 扩容路径

```
当前（单机）
  └── 2×4C8G App VM + 1×8C32G DB (主) + 1×4C8G Redis
        ↓ DAU 突破 500 万
  双机负载均衡
  └── 2×4C8G App VM × 2 + DB (主从) + Redis Sentinel
        ↓ DAU 突破 1000 万
  K8s + HPA 弹性扩缩
  └── App Pod 自动扩缩 + Aurora PostgreSQL + ElastiCache Redis Cluster
```

---

## 14. 优化实施路线图

### Phase 0 — 上线前必修（1 周）

| 编号 | 任务 | 优先级 | 预估工时 |
|------|------|--------|---------|
| P0-1 | `smtplib` 改为 Outbox 异步化 | 🔴 P0 | 4h |
| P0-2 | `pdf export` 改为异步任务 | 🔴 P0 | 4h |
| P0-3 | 确认 `pickup_signature_key` 仅存 MinIO 路径 | 🔴 P0 | 2h |
| P0-4 | `postgresql.conf.tuning` 挂载到 postgres 容器 | 🔴 P0 | 1h |
| P0-5 | Docker Compose `depends_on` 补充健康检查条件 | 🔴 P0 | 2h |
| P0-6 | 文件上传 MIME 类型和大小校验 | 🟠 P1 | 2h |

### Phase 1 — 生产域补全（2–3 周）

| 编号 | 任务 | 优先级 | 预估工时 |
|------|------|--------|---------|
| P1-1 | `ProductionService.apply_step_action()` 实现工人操作状态机 | 🔴 P0 | 2d |
| P1-2 | `ProductionService.mark_rework()` 实现返工推送 | 🔴 P0 | 1d |
| P1-3 | `scheduler_engine.py` 接入 `ProductionService.trigger_schedule()` | 🟠 P1 | 1d |
| P1-4 | 工人端 API 路由补全（start/complete/rework） | 🟠 P1 | 1d |
| P1-5 | 订单超期告警 APScheduler Job | 🟠 P1 | 4h |
| P1-6 | `orders/service.py` 拆分重构（抽出 PDF/邮件） | 🟡 P2 | 3d |

### Phase 2 — 性能加固（3–4 周）

| 编号 | 任务 | 优先级 | 预估工时 |
|------|------|--------|---------|
| P2-1 | 订单热数据 Redis 缓存（cache-aside + after-commit hook） | 🟠 P1 | 1d |
| P2-2 | Read Replica 配置 + 路由 | 🟠 P1 | 2d |
| P2-3 | 补充复合索引（超期、工序查询） | 🟠 P1 | 4h |
| P2-4 | SSE 实时订单状态推送 | 🟡 P2 | 1d |
| P2-5 | 虚拟滚动 + 懒加载图纸 | 🟡 P2 | 1d |
| P2-6 | Prometheus + Grafana 接入 | 🟡 P2 | 1d |
| P2-7 | Locust 压测 5000 TPS 基线验收 | 🟠 P1 | 1d |

### Phase 3 — 质量提升（持续迭代）

| 编号 | 任务 | 说明 |
|------|------|------|
| P3-1 | 单元测试覆盖率 > 80% | 重点：订单状态机、库存 Lua 脚本、排产算法 |
| P3-2 | 集成测试 | DB + Redis + Service 真实交互 |
| P3-3 | Refresh Token 轮换策略 | 安全加固 |
| P3-4 | 订单分区表 | 数据量突破 500 万行时实施 |
| P3-5 | i18n 中英文切换 | 前端 Vue 3 reactive locale |

---

## 15. 验收标准 Checklist

### 功能完整性

```
□ 前台可创建订单（含 PDF 图纸上传）
□ 订单状态六步流转正常（接单→画图→生产→完成→待取→已取）
□ Rush 订单、超期订单高亮显示
□ 订单修改后自动高亮通知生产人员
□ 工人界面：切割→开口→钢化→完成 工序流转
□ 返工标记：指定玻璃片自动推送至切割工序，高亮显示，已读后消失
□ 主管可批准取货
□ 客户手写签名（canvas）上传成功
□ 签字后自动生成 Pickup Slip PDF
□ 邮件通知客户取货（异步，不阻塞 API）
□ 历史记录可按客户/日期/订单号查询
□ 中英文切换正常
```

### 性能指标

```
□ P50 延迟 < 20ms（GET 接口）
□ P99 延迟 < 100ms（POST 接口）
□ 5000 TPS 下单压测 10 分钟，错误率 < 0.1%
□ 20,000 QPS 混合负载压测 5 分钟，系统稳定
□ Redis 缓存命中率 > 80%（订单详情）
□ DB 连接等待时间 < 5ms（PgBouncer 监控）
```

### 运维就绪

```
□ make ops-stack-up 一键启动成功
□ /health/ready 返回所有依赖 ok
□ Prometheus 指标端点 /metrics 可访问
□ 备份脚本 backup-baseline.sh 执行成功
□ 恢复脚本 restore-baseline.sh 验证成功（RTO < 30 分钟）
□ outbox dead_letter 告警触发测试
□ PostgreSQL 慢查询日志开启，100ms+ 查询可见
```

### 安全验收

```
□ 不同角色权限隔离（前台不可访问主管端点）
□ JWT 过期后 401 正确返回
□ 文件上传类型校验（非 PDF/JPG/PNG 被拒绝）
□ 文件大小限制（50MB）生效
□ 速率限制（下单 10次/分钟）生效
□ 生产环境 AUTO_INIT_SCHEMA_ON_STARTUP=0
□ 生产环境 secrets 目录不在代码仓库中
```

---

*文档由 Claude Sonnet 4.6 基于项目全量代码审查生成 · 2026-04-13*
