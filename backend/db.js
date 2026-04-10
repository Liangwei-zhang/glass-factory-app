import fs from 'node:fs';
import { randomUUID } from 'node:crypto';

import bcrypt from 'bcryptjs';
import Database from 'better-sqlite3';

import { DATA_DIR, SQLITE_DATABASE_PATH } from './config.js';
import {
  ACTIVE_ORDER_STATUSES,
  GLASS_TYPES,
  ORDER_STATUSES,
  PRIORITIES,
  PRIORITY_LABELS,
  PRODUCTION_STEPS,
  ROLES,
  STATUS_LABELS,
  STEP_STATUSES,
  STEP_STATUS_LABELS,
  STAGE_LABELS,
} from './constants.js';

fs.mkdirSync(DATA_DIR, { recursive: true });

const db = new Database(SQLITE_DATABASE_PATH);
db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');

const ACTIVE_STATUS_SET = new Set(ACTIVE_ORDER_STATUSES);
const CANCELLABLE_ORDER_STATUSES = new Set([
  ORDER_STATUSES.RECEIVED,
  ORDER_STATUSES.ENTERED,
]);

const VERSION_EVENT_LABELS = Object.freeze({
  created: '初始版本',
  updated: '订单修改',
  cancelled: '订单取消',
});

const NOTIFICATION_TEMPLATE_KEYS = Object.freeze({
  READY_FOR_PICKUP: 'ready_for_pickup',
});

const NOTIFICATION_TEMPLATE_VARIABLES = Object.freeze({
  [NOTIFICATION_TEMPLATE_KEYS.READY_FOR_PICKUP]: [
    'customerCompany',
    'customerContact',
    'customerPhone',
    'orderNo',
    'glassType',
    'thickness',
    'quantity',
    'specialInstructions',
    'pickupApprovedAt',
    'estimatedCompletionDate',
    'statusLabel',
  ],
});

const DEFAULT_NOTIFICATION_TEMPLATES = Object.freeze({
  [NOTIFICATION_TEMPLATE_KEYS.READY_FOR_PICKUP]: {
    name: 'Ready for Pickup 邮件',
    subjectTemplate: '订单 {{orderNo}} 已可取货',
    bodyTemplate: [
      '您好 {{customerCompany}}：',
      '',
      '订单 {{orderNo}} 已完成，现可安排取货。',
      '产品信息：{{glassType}} / {{thickness}} / {{quantity}} 片。',
      '批准时间：{{pickupApprovedAt}}。',
      '预计完成日期：{{estimatedCompletionDate}}。',
      '特殊说明：{{specialInstructions}}。',
      '',
      '如需调整取货安排，请直接回复此邮件或联系前台。',
      '',
      'Glass Factory Flow',
    ].join('\n'),
  },
});

function nowIso() {
  return new Date().toISOString();
}

function daysSince(timestamp) {
  if (!timestamp) {
    return 0;
  }

  const delta = Date.now() - new Date(timestamp).getTime();
  return Math.max(0, Math.floor(delta / (1000 * 60 * 60 * 24)));
}

function formatAuditValue(value) {
  if (value === null || value === undefined || value === '') {
    return '未设置';
  }

  return String(value);
}

function formatAuditDate(value) {
  if (!value) {
    return '未设置';
  }

  return String(value).slice(0, 10);
}

function readPatchValue(patch, key, currentValue) {
  return Object.prototype.hasOwnProperty.call(patch, key) ? patch[key] : currentValue;
}

function normalizePieceNumbers(pieceNumbers) {
  const values = Array.isArray(pieceNumbers) ? pieceNumbers : [pieceNumbers];

  return [...new Set(
    values
      .map((value) => Number.parseInt(value, 10))
      .filter((value) => Number.isInteger(value) && value > 0)
  )].sort((left, right) => left - right);
}

function formatPieceNumbers(pieceNumbers) {
  const normalized = normalizePieceNumbers(pieceNumbers);
  if (!normalized.length) {
    return '未指定';
  }

  return normalized.map((pieceNumber) => `第 ${pieceNumber} 片`).join('、');
}

function getTableColumns(tableName) {
  return db.prepare(`PRAGMA table_info(${tableName})`).all().map((row) => row.name);
}

function addColumnIfMissing(tableName, columnDefinition) {
  const columnName = columnDefinition.trim().split(/\s+/)[0];
  if (!getTableColumns(tableName).includes(columnName)) {
    db.exec(`ALTER TABLE ${tableName} ADD COLUMN ${columnDefinition}`);
  }
}

function extractOrderAuditValues(row) {
  return {
    customerId: {
      value: row.customer_id ?? null,
      display: formatAuditValue(row.company_name),
    },
    glassType: {
      value: row.glass_type ?? '',
      display: formatAuditValue(row.glass_type),
    },
    thickness: {
      value: row.thickness ?? '',
      display: formatAuditValue(row.thickness),
    },
    quantity: {
      value: Number(row.quantity ?? 0),
      display: `${Number(row.quantity ?? 0)} 片`,
    },
    priority: {
      value: row.priority ?? '',
      display: PRIORITY_LABELS[row.priority] ?? formatAuditValue(row.priority),
    },
    status: {
      value: row.status ?? '',
      display: STATUS_LABELS[row.status] ?? formatAuditValue(row.status),
    },
    estimatedCompletionDate: {
      value: row.estimated_completion_date ?? null,
      display: formatAuditDate(row.estimated_completion_date),
    },
    specialInstructions: {
      value: row.special_instructions ?? '',
      display: formatAuditValue(row.special_instructions),
    },
    drawingName: {
      value: row.drawing_name ?? '',
      display: formatAuditValue(row.drawing_name),
    },
    cancelledReason: {
      value: row.cancelled_reason ?? '',
      display: formatAuditValue(row.cancelled_reason),
    },
  };
}

function diffOrderSnapshots(previousRow, nextRow) {
  const previous = extractOrderAuditValues(previousRow);
  const next = extractOrderAuditValues(nextRow);
  const labels = {
    customerId: '客户',
    glassType: '玻璃类型',
    thickness: '厚度',
    quantity: '数量',
    priority: '优先级',
    status: '状态',
    estimatedCompletionDate: '预计完成日期',
    specialInstructions: '特殊说明',
    drawingName: '图纸',
    cancelledReason: '取消原因',
  };

  return Object.entries(labels).flatMap(([field, label]) => {
    if (previous[field].value === next[field].value) {
      return [];
    }

    return [
      {
        field,
        label,
        before: previous[field].display,
        after: next[field].display,
      },
    ];
  });
}

function buildOrderSnapshot(row) {
  return {
    version: Number(row.version ?? 1),
    orderNo: row.order_no,
    status: row.status,
    statusLabel: STATUS_LABELS[row.status] ?? row.status,
    priority: row.priority,
    priorityLabel: PRIORITY_LABELS[row.priority] ?? row.priority,
    customerId: row.customer_id,
    customerName: row.company_name ?? '',
    glassType: row.glass_type,
    thickness: row.thickness,
    quantity: Number(row.quantity ?? 0),
    estimatedCompletionDate: row.estimated_completion_date ?? null,
    specialInstructions: row.special_instructions ?? '',
    drawingName: row.drawing_name ?? '',
    drawingPath: row.drawing_path ?? null,
    cancelledAt: row.cancelled_at ?? null,
    cancelledReason: row.cancelled_reason ?? '',
    updatedAt: row.updated_at,
  };
}

function serializeUser(row) {
  if (!row) {
    return null;
  }

  return {
    id: row.id,
    name: row.name,
    email: row.email,
    role: row.role,
    stage: row.stage,
    stageLabel: row.stage ? STAGE_LABELS[row.stage] ?? row.stage : null,
    createdAt: row.created_at,
  };
}

function serializeCustomer(row) {
  return {
    id: row.id,
    companyName: row.company_name,
    contactName: row.contact_name,
    phone: row.phone,
    email: row.email,
    notes: row.notes,
    totalOrders: Number(row.total_orders ?? 0),
    activeOrders: Number(row.active_orders ?? 0),
    hasActiveOrders: Number(row.active_orders ?? 0) > 0,
    lastOrderAt: row.last_order_at,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

function serializeSteps(rows) {
  const normalized = rows.map((row) => ({
    id: row.id,
    key: row.step_key,
    label: row.step_label,
    index: row.step_index,
    status: row.status,
    statusLabel: STEP_STATUS_LABELS[row.status],
    startedAt: row.started_at,
    completedAt: row.completed_at,
    updatedAt: row.updated_at,
    reworkCount: Number(row.rework_count ?? 0),
    reworkNote: row.rework_note ?? '',
    reworkUnread: Boolean(row.rework_unread),
  }));

  return normalized.map((step, index) => {
    const previousSteps = normalized.slice(0, index);
    const previousCompleted = previousSteps.every(
      (candidate) => candidate.status === STEP_STATUSES.COMPLETED
    );

    return {
      ...step,
      isAvailable:
        (index === 0 || previousCompleted) && step.status !== STEP_STATUSES.COMPLETED,
      isBlocked: index > 0 && !previousCompleted,
    };
  });
}

function serializeEvents(orderId) {
  const rows = db
    .prepare(
      `
        SELECT
          events.id,
          events.type,
          events.message,
          events.metadata_json,
          events.created_at,
          users.name AS actor_name
        FROM order_events AS events
        LEFT JOIN users ON users.id = events.actor_user_id
        WHERE events.order_id = ?
        ORDER BY events.created_at DESC
        LIMIT 18
      `
    )
    .all(orderId);

  return rows.map((row) => ({
    id: row.id,
    type: row.type,
    message: row.message,
    actorName: row.actor_name ?? '系统',
    createdAt: row.created_at,
    metadata: row.metadata_json ? JSON.parse(row.metadata_json) : {},
  }));
}

function serializeVersions(orderId) {
  const rows = db
    .prepare(
      `
        SELECT
          versions.id,
          versions.version_number,
          versions.event_type,
          versions.reason,
          versions.snapshot_json,
          versions.changes_json,
          versions.created_at,
          users.name AS actor_name
        FROM order_versions AS versions
        LEFT JOIN users ON users.id = versions.actor_user_id
        WHERE versions.order_id = ?
        ORDER BY versions.version_number DESC, versions.created_at DESC
        LIMIT 12
      `
    )
    .all(orderId);

  return rows.map((row) => ({
    id: row.id,
    versionNumber: Number(row.version_number),
    eventType: row.event_type,
    eventLabel: VERSION_EVENT_LABELS[row.event_type] ?? row.event_type,
    reason: row.reason ?? '',
    actorName: row.actor_name ?? '系统',
    createdAt: row.created_at,
    snapshot: row.snapshot_json ? JSON.parse(row.snapshot_json) : {},
    changes: row.changes_json ? JSON.parse(row.changes_json) : [],
  }));
}

function serializeReworkRequests(orderId, { limit = 24 } = {}) {
  const rows = db
    .prepare(
      `
        SELECT
          rework_requests.*,
          actors.name AS actor_name,
          acknowledged_by_users.name AS acknowledged_by_name
        FROM rework_requests
        LEFT JOIN users AS actors ON actors.id = rework_requests.actor_user_id
        LEFT JOIN users AS acknowledged_by_users ON acknowledged_by_users.id = rework_requests.acknowledged_by
        WHERE rework_requests.order_id = ?
        ORDER BY rework_requests.created_at DESC
        LIMIT ?
      `
    )
    .all(orderId, limit);

  return rows.map((row) => {
    const pieceNumbers = row.piece_numbers_json
      ? normalizePieceNumbers(JSON.parse(row.piece_numbers_json))
      : [];

    return {
      id: row.id,
      sourceStepKey: row.source_step_key,
      sourceStepLabel: row.source_step_label,
      pieceNumbers,
      pieceCount: Number(row.piece_count ?? pieceNumbers.length),
      pieceSummary: formatPieceNumbers(pieceNumbers),
      note: row.note ?? '',
      actorName: row.actor_name ?? '系统',
      createdAt: row.created_at,
      isAcknowledged: Boolean(row.is_acknowledged),
      acknowledgedAt: row.acknowledged_at,
      acknowledgedByName: row.acknowledged_by_name ?? '',
    };
  });
}

function serializeNotificationTemplateRow(row, templateKey) {
  const defaults = DEFAULT_NOTIFICATION_TEMPLATES[templateKey];
  if (!defaults) {
    return null;
  }

  return {
    templateKey,
    name: row?.name ?? defaults.name,
    subjectTemplate: row?.subject_template ?? defaults.subjectTemplate,
    bodyTemplate: row?.body_template ?? defaults.bodyTemplate,
    availableVariables: NOTIFICATION_TEMPLATE_VARIABLES[templateKey] ?? [],
    updatedAt: row?.updated_at ?? null,
    updatedByName: row?.updated_by_name ?? '',
  };
}

function serializeEmailLog(row) {
  return {
    id: row.id,
    templateKey: row.template_key,
    orderId: row.order_id,
    orderNo: row.order_no,
    customerEmail: row.customer_email,
    subject: row.subject,
    body: row.body,
    status: row.status,
    transport: row.transport,
    errorMessage: row.error_message ?? '',
    providerMessageId: row.provider_message_id ?? '',
    actorName: row.actor_name ?? '系统',
    createdAt: row.created_at,
    sentAt: row.sent_at,
  };
}

function serializeGlassTypeRow(row) {
  return {
    id: row.id,
    name: row.name,
    isActive: Boolean(row.is_active),
    sortOrder: Number(row.sort_order ?? 0),
    totalOrderCount: Number(row.total_order_count ?? 0),
    activeOrderCount: Number(row.active_order_count ?? 0),
    updatedAt: row.updated_at,
    updatedByName: row.updated_by_name ?? '',
  };
}

function normalizeBooleanFlag(value, fallback) {
  if (value === undefined || value === null || value === '') {
    return fallback;
  }

  if (typeof value === 'boolean') {
    return value ? 1 : 0;
  }

  if (typeof value === 'number') {
    return value ? 1 : 0;
  }

  const normalized = String(value).trim().toLowerCase();
  if (['1', 'true', 'yes', 'on'].includes(normalized)) {
    return 1;
  }
  if (['0', 'false', 'no', 'off'].includes(normalized)) {
    return 0;
  }

  return fallback;
}

function hydrateOrder(row, { includeTimeline = false, includeVersions = false } = {}) {
  if (!row) {
    return null;
  }

  const steps = serializeSteps(
    db
      .prepare(
        `
          SELECT *
          FROM order_steps
          WHERE order_id = ?
          ORDER BY step_index ASC
        `
      )
      .all(row.id)
  );
  const activeSince = row.last_production_activity_at || row.entered_at || row.created_at;
  const staleDays = daysSince(activeSince);
  const isStale =
    ![
      ORDER_STATUSES.COMPLETED,
      ORDER_STATUSES.READY_FOR_PICKUP,
      ORDER_STATUSES.PICKED_UP,
      ORDER_STATUSES.CANCELLED,
    ].includes(row.status) && staleDays >= 5;
  const hasProductionActivity = steps.some(
    (step) => step.status !== STEP_STATUSES.PENDING || step.startedAt || step.completedAt
  );
  const canCancel = CANCELLABLE_ORDER_STATUSES.has(row.status) && !hasProductionActivity;
  const shouldIncludeReworkRequests =
    includeTimeline ||
    Boolean(row.rework_open) ||
    steps.some((step) => step.reworkCount > 0 || step.reworkUnread);
  const reworkRequests = shouldIncludeReworkRequests
    ? serializeReworkRequests(row.id, { limit: includeTimeline ? 24 : 8 })
    : [];
  const openReworkRequests = reworkRequests.filter((request) => !request.isAcknowledged);
  const cuttingPendingPieces = normalizePieceNumbers(
    openReworkRequests.flatMap((request) => request.pieceNumbers)
  );
  const enrichedSteps = steps.map((step) => {
    const relatedRequests = reworkRequests.filter((request) => request.sourceStepKey === step.key);
    const relatedPieceNumbers =
      step.key === 'cutting'
        ? cuttingPendingPieces
        : normalizePieceNumbers(relatedRequests.flatMap((request) => request.pieceNumbers));

    return {
      ...step,
      reworkPieceNumbers: relatedPieceNumbers,
      reworkPieceSummary: relatedPieceNumbers.length ? formatPieceNumbers(relatedPieceNumbers) : '',
      reworkRequestCount: relatedRequests.length,
    };
  });

  return {
    id: row.id,
    orderNo: row.order_no,
    status: row.status,
    statusLabel: STATUS_LABELS[row.status] ?? row.status,
    priority: row.priority,
    priorityLabel: PRIORITY_LABELS[row.priority] ?? row.priority,
    glassType: row.glass_type,
    thickness: row.thickness,
    quantity: Number(row.quantity),
    estimatedCompletionDate: row.estimated_completion_date,
    specialInstructions: row.special_instructions,
    drawingUrl: row.drawing_path,
    drawingName: row.drawing_name,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
    enteredAt: row.entered_at,
    completedAt: row.completed_at,
    cancelledAt: row.cancelled_at,
    cancelledReason: row.cancelled_reason,
    readyForPickupAt: row.ready_for_pickup_at,
    pickedUpAt: row.picked_up_at,
    pickupApprovedAt: row.pickup_approved_at,
    pickupApprovedBy: row.pickup_approved_by,
    pickupSignerName: row.pickup_signer_name,
    pickupSignatureUrl: row.pickup_signature_path,
    lastProductionActivityAt: row.last_production_activity_at,
    version: Number(row.version ?? 1),
    isModified: Boolean(row.is_modified),
    reworkOpen: Boolean(row.rework_open) || openReworkRequests.length > 0,
    staleDays,
    isStale,
    canCancel,
    canCancelLabel: row.status === ORDER_STATUSES.RECEIVED ? '撤回订单' : '取消订单',
    pickupWaitingDays:
      row.ready_for_pickup_at && row.status !== ORDER_STATUSES.PICKED_UP
        ? daysSince(row.ready_for_pickup_at)
        : 0,
    customer: {
      id: row.customer_id,
      companyName: row.company_name,
      contactName: row.contact_name,
      phone: row.customer_phone,
      email: row.customer_email,
      notes: row.customer_notes,
    },
    steps: enrichedSteps,
    reworkRequests,
    openReworkCount: openReworkRequests.length,
    openReworkPieceSummary: cuttingPendingPieces.length
      ? formatPieceNumbers(cuttingPendingPieces)
      : '',
    timeline: includeTimeline ? serializeEvents(row.id) : [],
    versionHistory: includeVersions ? serializeVersions(row.id) : [],
  };
}

function getUserRowsByRole(role, stage = null) {
  if (stage) {
    return db
      .prepare(
        `
          SELECT id
          FROM users
          WHERE role = ? AND stage = ?
        `
      )
      .all(role, stage);
  }

  return db
    .prepare(
      `
        SELECT id
        FROM users
        WHERE role = ?
      `
    )
    .all(role);
}

function notifyUsers(userIds, payload) {
  if (!userIds.length) {
    return;
  }

  const insert = db.prepare(
    `
      INSERT INTO notifications (
        id,
        user_id,
        order_id,
        title,
        message,
        severity,
        is_read,
        created_at
      ) VALUES (?, ?, ?, ?, ?, ?, 0, ?)
    `
  );

  const createdAt = nowIso();

  for (const userId of new Set(userIds)) {
    insert.run(
      randomUUID(),
      userId,
      payload.orderId ?? null,
      payload.title,
      payload.message,
      payload.severity ?? 'info',
      createdAt
    );
  }
}

function notifyOffice(payload) {
  notifyUsers(
    getUserRowsByRole(ROLES.OFFICE).map((row) => row.id),
    payload
  );
}

function notifySupervisors(payload) {
  notifyUsers(
    getUserRowsByRole(ROLES.SUPERVISOR).map((row) => row.id),
    payload
  );
}

function notifyStageWorkers(stage, payload) {
  notifyUsers(
    getUserRowsByRole(ROLES.WORKER, stage).map((row) => row.id),
    payload
  );
}

function createEvent(orderId, type, message, actorUserId = null, metadata = {}) {
  db.prepare(
    `
      INSERT INTO order_events (
        id,
        order_id,
        type,
        message,
        actor_user_id,
        metadata_json,
        created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?)
    `
  ).run(
    randomUUID(),
    orderId,
    type,
    message,
    actorUserId,
    JSON.stringify(metadata),
    nowIso()
  );
}

function createOrderVersion(orderId, eventType, actorUserId, reason, orderRow, changes = []) {
  db.prepare(
    `
      INSERT INTO order_versions (
        id,
        order_id,
        version_number,
        event_type,
        reason,
        actor_user_id,
        snapshot_json,
        changes_json,
        created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    `
  ).run(
    randomUUID(),
    orderId,
    Number(orderRow.version ?? 1),
    eventType,
    reason ?? '',
    actorUserId,
    JSON.stringify(buildOrderSnapshot(orderRow)),
    JSON.stringify(changes),
    nowIso()
  );
}

function runMigrations() {
  addColumnIfMissing('orders', 'cancelled_at TEXT');
  addColumnIfMissing('orders', 'cancelled_reason TEXT');
  addColumnIfMissing('orders', 'version INTEGER NOT NULL DEFAULT 1');

  db.exec(`
    CREATE TABLE IF NOT EXISTS order_versions (
      id TEXT PRIMARY KEY,
      order_id TEXT NOT NULL,
      version_number INTEGER NOT NULL,
      event_type TEXT NOT NULL,
      reason TEXT,
      actor_user_id TEXT,
      snapshot_json TEXT NOT NULL,
      changes_json TEXT NOT NULL DEFAULT '[]',
      created_at TEXT NOT NULL,
      FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
      FOREIGN KEY (actor_user_id) REFERENCES users(id)
    );

    CREATE INDEX IF NOT EXISTS idx_order_versions_order
      ON order_versions(order_id, version_number DESC, created_at DESC);

    CREATE TABLE IF NOT EXISTS rework_requests (
      id TEXT PRIMARY KEY,
      order_id TEXT NOT NULL,
      source_step_key TEXT NOT NULL,
      source_step_label TEXT NOT NULL,
      piece_numbers_json TEXT NOT NULL,
      piece_count INTEGER NOT NULL,
      note TEXT,
      actor_user_id TEXT,
      is_acknowledged INTEGER NOT NULL DEFAULT 0,
      acknowledged_at TEXT,
      acknowledged_by TEXT,
      created_at TEXT NOT NULL,
      FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
      FOREIGN KEY (actor_user_id) REFERENCES users(id),
      FOREIGN KEY (acknowledged_by) REFERENCES users(id)
    );

    CREATE INDEX IF NOT EXISTS idx_rework_requests_order
      ON rework_requests(order_id, is_acknowledged, created_at DESC);

    CREATE TABLE IF NOT EXISTS notification_templates (
      template_key TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      subject_template TEXT NOT NULL,
      body_template TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      updated_by TEXT,
      FOREIGN KEY (updated_by) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS email_logs (
      id TEXT PRIMARY KEY,
      template_key TEXT NOT NULL,
      order_id TEXT,
      customer_email TEXT NOT NULL,
      subject TEXT NOT NULL,
      body TEXT NOT NULL,
      status TEXT NOT NULL,
      transport TEXT NOT NULL,
      error_message TEXT,
      provider_message_id TEXT,
      actor_user_id TEXT,
      created_at TEXT NOT NULL,
      sent_at TEXT,
      FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE SET NULL,
      FOREIGN KEY (actor_user_id) REFERENCES users(id)
    );

    CREATE INDEX IF NOT EXISTS idx_email_logs_created_at
      ON email_logs(created_at DESC);

    CREATE INDEX IF NOT EXISTS idx_email_logs_order
      ON email_logs(order_id, created_at DESC);
  `);
}

function generateOrderNumber() {
  const dateStamp = new Date().toISOString().slice(0, 10).replaceAll('-', '');
  const prefix = `GF${dateStamp}`;
  const lastRow = db
    .prepare(
      `
        SELECT order_no
        FROM orders
        WHERE order_no LIKE ?
        ORDER BY order_no DESC
        LIMIT 1
      `
    )
    .get(`${prefix}-%`);
  const lastSequence = lastRow ? Number(lastRow.order_no.split('-').pop()) : 0;
  return `${prefix}-${String(lastSequence + 1).padStart(4, '0')}`;
}

function requireOrder(orderId) {
  const row = db
    .prepare(
      `
        SELECT
          orders.*,
          customers.company_name,
          customers.contact_name,
          customers.phone AS customer_phone,
          customers.email AS customer_email,
          customers.notes AS customer_notes
        FROM orders
        JOIN customers ON customers.id = orders.customer_id
        WHERE orders.id = ?
      `
    )
    .get(orderId);

  if (!row) {
    throw new Error('订单不存在。');
  }

  return row;
}

function requireStep(orderId, stepKey) {
  const row = db
    .prepare(
      `
        SELECT *
        FROM order_steps
        WHERE order_id = ? AND step_key = ?
      `
    )
    .get(orderId, stepKey);

  if (!row) {
    throw new Error('工序不存在。');
  }

  return row;
}

function ensurePreviousStepsCompleted(orderId, stepIndex) {
  const previousIncomplete = db
    .prepare(
      `
        SELECT COUNT(*) AS count
        FROM order_steps
        WHERE order_id = ? AND step_index < ? AND status != ?
      `
    )
    .get(orderId, stepIndex, STEP_STATUSES.COMPLETED);

  if (Number(previousIncomplete.count) > 0) {
    throw new Error('上一个工序未完成，不能继续流转。');
  }
}

function getJoinedOrderRow(orderId) {
  return db
    .prepare(
      `
        SELECT
          orders.*,
          customers.company_name,
          customers.contact_name,
          customers.phone AS customer_phone,
          customers.email AS customer_email,
          customers.notes AS customer_notes
        FROM orders
        JOIN customers ON customers.id = orders.customer_id
        WHERE orders.id = ?
      `
    )
    .get(orderId);
}

function updateOrderStatus(orderId, status, patch = {}) {
  const current = requireOrder(orderId);
  const updatedAt = nowIso();
  const values = {
    id: orderId,
    status,
    updatedAt,
    enteredAt: readPatchValue(patch, 'enteredAt', current.entered_at),
    completedAt: readPatchValue(patch, 'completedAt', current.completed_at),
    cancelledAt: readPatchValue(patch, 'cancelledAt', current.cancelled_at),
    cancelledReason: readPatchValue(patch, 'cancelledReason', current.cancelled_reason),
    readyForPickupAt: readPatchValue(patch, 'readyForPickupAt', current.ready_for_pickup_at),
    pickedUpAt: readPatchValue(patch, 'pickedUpAt', current.picked_up_at),
    pickupApprovedAt: readPatchValue(patch, 'pickupApprovedAt', current.pickup_approved_at),
    pickupApprovedBy: readPatchValue(patch, 'pickupApprovedBy', current.pickup_approved_by),
    pickupSignerName: readPatchValue(patch, 'pickupSignerName', current.pickup_signer_name),
    pickupSignaturePath: readPatchValue(
      patch,
      'pickupSignaturePath',
      current.pickup_signature_path
    ),
    lastProductionActivityAt: readPatchValue(
      patch,
      'lastProductionActivityAt',
      current.last_production_activity_at
    ),
    reworkOpen: readPatchValue(patch, 'reworkOpen', current.rework_open),
    version: readPatchValue(patch, 'version', current.version ?? 1),
  };

  db.prepare(
    `
      UPDATE orders
      SET
        status = @status,
        updated_at = @updatedAt,
        entered_at = @enteredAt,
        completed_at = @completedAt,
        cancelled_at = @cancelledAt,
        cancelled_reason = @cancelledReason,
        ready_for_pickup_at = @readyForPickupAt,
        picked_up_at = @pickedUpAt,
        pickup_approved_at = @pickupApprovedAt,
        pickup_approved_by = @pickupApprovedBy,
        pickup_signer_name = @pickupSignerName,
        pickup_signature_path = @pickupSignaturePath,
        last_production_activity_at = @lastProductionActivityAt,
        rework_open = @reworkOpen,
        version = @version
      WHERE id = @id
    `
  ).run(values);
}

function recalculateCompletionState(orderId, actorUserId) {
  const incomplete = db
    .prepare(
      `
        SELECT COUNT(*) AS count
        FROM order_steps
        WHERE order_id = ? AND status != ?
      `
    )
    .get(orderId, STEP_STATUSES.COMPLETED);

  if (Number(incomplete.count) === 0) {
    const completedAt = nowIso();
    updateOrderStatus(orderId, ORDER_STATUSES.COMPLETED, {
      completedAt,
      lastProductionActivityAt: completedAt,
    });
    const order = requireOrder(orderId);

    createEvent(
      orderId,
      'order_completed',
      '全部生产工序完成，订单待主管批准取货。',
      actorUserId,
      { status: ORDER_STATUSES.COMPLETED }
    );

    notifyOffice({
      orderId,
      severity: 'success',
      title: '订单已完成',
      message: `${order.order_no} 已完成，可安排主管批准 pickup。`,
    });

    notifySupervisors({
      orderId,
      severity: 'success',
      title: '订单待批准取货',
      message: `${order.order_no} 已完工，请确认是否允许 pickup。`,
    });
  }
}

export function initDatabase() {
  db.exec(`
    CREATE TABLE IF NOT EXISTS users (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      email TEXT NOT NULL UNIQUE,
      password_hash TEXT NOT NULL,
      role TEXT NOT NULL,
      stage TEXT,
      created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS customers (
      id TEXT PRIMARY KEY,
      company_name TEXT NOT NULL,
      contact_name TEXT,
      phone TEXT,
      email TEXT,
      notes TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS glass_types (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      sort_order INTEGER NOT NULL DEFAULT 0,
      is_active INTEGER NOT NULL DEFAULT 1,
      updated_at TEXT NOT NULL,
      updated_by TEXT,
      FOREIGN KEY (updated_by) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS orders (
      id TEXT PRIMARY KEY,
      order_no TEXT NOT NULL UNIQUE,
      customer_id TEXT NOT NULL,
      status TEXT NOT NULL,
      priority TEXT NOT NULL DEFAULT 'normal',
      glass_type TEXT NOT NULL,
      thickness TEXT NOT NULL,
      quantity INTEGER NOT NULL,
      estimated_completion_date TEXT,
      special_instructions TEXT,
      drawing_path TEXT,
      drawing_name TEXT,
      created_by TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      entered_at TEXT,
      completed_at TEXT,
      cancelled_at TEXT,
      cancelled_reason TEXT,
      ready_for_pickup_at TEXT,
      picked_up_at TEXT,
      pickup_approved_at TEXT,
      pickup_approved_by TEXT,
      pickup_signer_name TEXT,
      pickup_signature_path TEXT,
      is_modified INTEGER NOT NULL DEFAULT 0,
      rework_open INTEGER NOT NULL DEFAULT 0,
      last_production_activity_at TEXT,
      version INTEGER NOT NULL DEFAULT 1,
      FOREIGN KEY (customer_id) REFERENCES customers(id),
      FOREIGN KEY (created_by) REFERENCES users(id),
      FOREIGN KEY (pickup_approved_by) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS order_steps (
      id TEXT PRIMARY KEY,
      order_id TEXT NOT NULL,
      step_key TEXT NOT NULL,
      step_label TEXT NOT NULL,
      step_index INTEGER NOT NULL,
      status TEXT NOT NULL,
      rework_count INTEGER NOT NULL DEFAULT 0,
      rework_note TEXT,
      rework_unread INTEGER NOT NULL DEFAULT 0,
      started_at TEXT,
      completed_at TEXT,
      updated_at TEXT NOT NULL,
      UNIQUE (order_id, step_key),
      FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS order_events (
      id TEXT PRIMARY KEY,
      order_id TEXT NOT NULL,
      type TEXT NOT NULL,
      message TEXT NOT NULL,
      actor_user_id TEXT,
      metadata_json TEXT,
      created_at TEXT NOT NULL,
      FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
      FOREIGN KEY (actor_user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS notifications (
      id TEXT PRIMARY KEY,
      user_id TEXT NOT NULL,
      order_id TEXT,
      title TEXT NOT NULL,
      message TEXT NOT NULL,
      severity TEXT NOT NULL DEFAULT 'info',
      is_read INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL,
      FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
      FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
    CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
    CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at DESC);
    CREATE UNIQUE INDEX IF NOT EXISTS idx_glass_types_name_unique
      ON glass_types(name COLLATE NOCASE);
    CREATE INDEX IF NOT EXISTS idx_glass_types_active_sort
      ON glass_types(is_active, sort_order, name COLLATE NOCASE);
    CREATE INDEX IF NOT EXISTS idx_order_steps_order_id ON order_steps(order_id, step_index);
    CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON notifications(user_id, is_read, created_at DESC);
  `);

  runMigrations();

  seedUsers();
  seedCustomers();
  seedGlassTypes();
  seedNotificationTemplates();
  seedDemoOrder();
}

function seedUsers() {
  const row = db.prepare('SELECT COUNT(*) AS count FROM users').get();
  if (Number(row.count) > 0) {
    return;
  }

  const timestamp = nowIso();
  const insert = db.prepare(
    `
      INSERT INTO users (id, name, email, password_hash, role, stage, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `
  );
  const hash = (password) => bcrypt.hashSync(password, 10);

  const seededUsers = [
    {
      name: 'Front Desk',
      email: 'office@glass.local',
      password: 'office123',
      role: ROLES.OFFICE,
      stage: null,
    },
    {
      name: 'Cutting Worker',
      email: 'cutting@glass.local',
      password: 'worker123',
      role: ROLES.WORKER,
      stage: 'cutting',
    },
    {
      name: 'Edging Worker',
      email: 'edging@glass.local',
      password: 'worker123',
      role: ROLES.WORKER,
      stage: 'edging',
    },
    {
      name: 'Tempering Worker',
      email: 'tempering@glass.local',
      password: 'worker123',
      role: ROLES.WORKER,
      stage: 'tempering',
    },
    {
      name: 'Finishing Worker',
      email: 'finishing@glass.local',
      password: 'worker123',
      role: ROLES.WORKER,
      stage: 'finishing',
    },
    {
      name: 'Floor Supervisor',
      email: 'supervisor@glass.local',
      password: 'supervisor123',
      role: ROLES.SUPERVISOR,
      stage: null,
    },
  ];

  for (const user of seededUsers) {
    insert.run(
      randomUUID(),
      user.name,
      user.email,
      hash(user.password),
      user.role,
      user.stage,
      timestamp
    );
  }
}

function seedCustomers() {
  const row = db.prepare('SELECT COUNT(*) AS count FROM customers').get();
  if (Number(row.count) > 0) {
    return;
  }

  const insert = db.prepare(
    `
      INSERT INTO customers (
        id,
        company_name,
        contact_name,
        phone,
        email,
        notes,
        created_at,
        updated_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `
  );
  const timestamp = nowIso();

  const samples = [
    {
      companyName: 'Aurora Construction',
      contactName: 'Liam Chen',
      phone: '0412 330 900',
      email: 'liam@aurora.example',
      notes: '常做商场店面玻璃，优先走 Clear 6mm。',
    },
    {
      companyName: 'Harbor Fitout',
      contactName: 'Sophie Ng',
      phone: '0455 881 210',
      email: 'ops@harborfitout.example',
      notes: '常加急，图纸修改频繁。',
    },
  ];

  for (const customer of samples) {
    insert.run(
      randomUUID(),
      customer.companyName,
      customer.contactName,
      customer.phone,
      customer.email,
      customer.notes,
      timestamp,
      timestamp
    );
  }
}

function seedGlassTypes() {
  const insert = db.prepare(
    `
      INSERT OR IGNORE INTO glass_types (
        id,
        name,
        sort_order,
        is_active,
        updated_at,
        updated_by
      ) VALUES (?, ?, ?, 1, ?, NULL)
    `
  );
  const timestamp = nowIso();

  GLASS_TYPES.forEach((glassTypeName, index) => {
    insert.run(randomUUID(), glassTypeName, index, timestamp);
  });
}

function seedNotificationTemplates() {
  const insert = db.prepare(
    `
      INSERT INTO notification_templates (
        template_key,
        name,
        subject_template,
        body_template,
        updated_at,
        updated_by
      ) VALUES (?, ?, ?, ?, ?, ?)
      ON CONFLICT(template_key) DO NOTHING
    `
  );
  const timestamp = nowIso();

  for (const [templateKey, template] of Object.entries(DEFAULT_NOTIFICATION_TEMPLATES)) {
    insert.run(
      templateKey,
      template.name,
      template.subjectTemplate,
      template.bodyTemplate,
      timestamp,
      null
    );
  }
}

function seedDemoOrder() {
  if (process.env.SEED_DEMO_DATA === 'false') {
    return;
  }

  const existing = db.prepare('SELECT COUNT(*) AS count FROM orders').get();
  if (Number(existing.count) > 0) {
    return;
  }

  const office = db.prepare('SELECT * FROM users WHERE role = ? LIMIT 1').get(ROLES.OFFICE);
  const customer = db.prepare('SELECT * FROM customers ORDER BY created_at ASC LIMIT 1').get();

  if (!office || !customer) {
    return;
  }

  const order = createOrder({
    customerId: customer.id,
    glassType: 'Clear',
    thickness: '6mm',
    quantity: 12,
    priority: PRIORITIES.RUSH,
    estimatedCompletionDate: new Date(Date.now() + 2 * 24 * 60 * 60 * 1000).toISOString(),
    specialInstructions: '样板订单：前 2 片先做，客户下午确认。',
    createdBy: office.id,
  });

  markOrderEntered(order.id, office.id);
}

export function getUserByEmail(email) {
  return db.prepare('SELECT * FROM users WHERE email = ?').get(email);
}

export function getUserById(userId) {
  return db.prepare('SELECT * FROM users WHERE id = ?').get(userId);
}

export function listCustomers() {
  const activeCases = ACTIVE_ORDER_STATUSES.map(() => '?').join(', ');
  const rows = db
    .prepare(
      `
        SELECT
          customers.*,
          COUNT(orders.id) AS total_orders,
          SUM(CASE WHEN orders.status IN (${activeCases}) THEN 1 ELSE 0 END) AS active_orders,
          MAX(orders.created_at) AS last_order_at
        FROM customers
        LEFT JOIN orders ON orders.customer_id = customers.id
        GROUP BY customers.id
        ORDER BY customers.company_name COLLATE NOCASE ASC
      `
    )
    .all(...ACTIVE_ORDER_STATUSES);

  return rows.map(serializeCustomer);
}

export function createCustomer(payload) {
  const timestamp = nowIso();
  const customerId = randomUUID();

  db.prepare(
    `
      INSERT INTO customers (
        id,
        company_name,
        contact_name,
        phone,
        email,
        notes,
        created_at,
        updated_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `
  ).run(
    customerId,
    payload.companyName,
    payload.contactName ?? '',
    payload.phone ?? '',
    payload.email ?? '',
    payload.notes ?? '',
    timestamp,
    timestamp
  );

  return listCustomers().find((customer) => customer.id === customerId);
}

export function updateCustomer(customerId, payload) {
  const current = db.prepare('SELECT * FROM customers WHERE id = ?').get(customerId);
  if (!current) {
    throw new Error('客户不存在。');
  }

  db.prepare(
    `
      UPDATE customers
      SET
        company_name = ?,
        contact_name = ?,
        phone = ?,
        email = ?,
        notes = ?,
        updated_at = ?
      WHERE id = ?
    `
  ).run(
    payload.companyName ?? current.company_name,
    payload.contactName ?? current.contact_name,
    payload.phone ?? current.phone,
    payload.email ?? current.email,
    payload.notes ?? current.notes,
    nowIso(),
    customerId
  );

  return listCustomers().find((customer) => customer.id === customerId);
}

function requireGlassType(glassTypeId) {
  const row = db.prepare('SELECT * FROM glass_types WHERE id = ?').get(glassTypeId);

  if (!row) {
    throw new Error('玻璃类型不存在。');
  }

  return row;
}

export function listGlassTypes({ includeInactive = false } = {}) {
  const activeCases = ACTIVE_ORDER_STATUSES.map(() => '?').join(', ');
  const rows = db
    .prepare(
      `
        SELECT
          glass_types.*,
          users.name AS updated_by_name,
          COUNT(orders.id) AS total_order_count,
          SUM(CASE WHEN orders.status IN (${activeCases}) THEN 1 ELSE 0 END) AS active_order_count
        FROM glass_types
        LEFT JOIN users ON users.id = glass_types.updated_by
        LEFT JOIN orders ON lower(orders.glass_type) = lower(glass_types.name)
        ${includeInactive ? '' : 'WHERE glass_types.is_active = 1'}
        GROUP BY glass_types.id
        ORDER BY glass_types.sort_order ASC, glass_types.name COLLATE NOCASE ASC
      `
    )
    .all(...ACTIVE_ORDER_STATUSES);

  return rows.map(serializeGlassTypeRow);
}

export function createGlassType(name, actorUserId) {
  const normalizedName = String(name || '').trim();
  if (!normalizedName) {
    throw new Error('玻璃类型名称不能为空。');
  }
  if (normalizedName.length > 48) {
    throw new Error('玻璃类型名称不能超过 48 个字符。');
  }

  const duplicate = db
    .prepare('SELECT id FROM glass_types WHERE lower(name) = lower(?)')
    .get(normalizedName);
  if (duplicate) {
    throw new Error('玻璃类型已存在。');
  }

  const glassTypeId = randomUUID();
  const timestamp = nowIso();
  const maxSortOrder = db
    .prepare('SELECT COALESCE(MAX(sort_order), -1) AS value FROM glass_types')
    .get();

  db.prepare(
    `
      INSERT INTO glass_types (
        id,
        name,
        sort_order,
        is_active,
        updated_at,
        updated_by
      ) VALUES (?, ?, ?, 1, ?, ?)
    `
  ).run(
    glassTypeId,
    normalizedName,
    Number(maxSortOrder?.value ?? -1) + 1,
    timestamp,
    actorUserId ?? null
  );

  return listGlassTypes({ includeInactive: true }).find(
    (glassType) => glassType.id === glassTypeId
  );
}

export function updateGlassType(glassTypeId, payload, actorUserId) {
  const current = requireGlassType(glassTypeId);
  const nextName =
    payload.name !== undefined ? String(payload.name || '').trim() : current.name;
  const nextIsActive = normalizeBooleanFlag(payload.isActive, current.is_active);

  if (!nextName) {
    throw new Error('玻璃类型名称不能为空。');
  }
  if (nextName.length > 48) {
    throw new Error('玻璃类型名称不能超过 48 个字符。');
  }

  const duplicate = db
    .prepare(
      `
        SELECT id
        FROM glass_types
        WHERE lower(name) = lower(?) AND id != ?
      `
    )
    .get(nextName, glassTypeId);
  if (duplicate) {
    throw new Error('玻璃类型已存在。');
  }

  const timestamp = nowIso();
  const transaction = db.transaction(() => {
    db.prepare(
      `
        UPDATE glass_types
        SET
          name = ?,
          is_active = ?,
          updated_at = ?,
          updated_by = ?
        WHERE id = ?
      `
    ).run(nextName, nextIsActive, timestamp, actorUserId ?? null, glassTypeId);

    if (nextName.toLowerCase() !== String(current.name).toLowerCase()) {
      db.prepare(
        `
          UPDATE orders
          SET glass_type = ?
          WHERE lower(glass_type) = lower(?)
        `
      ).run(nextName, current.name);
    }
  });

  transaction();

  return listGlassTypes({ includeInactive: true }).find(
    (glassType) => glassType.id === glassTypeId
  );
}

export function getNotificationTemplate(templateKey) {
  const defaults = DEFAULT_NOTIFICATION_TEMPLATES[templateKey];
  if (!defaults) {
    throw new Error('通知模板不存在。');
  }

  const row = db
    .prepare(
      `
        SELECT
          notification_templates.*, 
          users.name AS updated_by_name
        FROM notification_templates
        LEFT JOIN users ON users.id = notification_templates.updated_by
        WHERE template_key = ?
      `
    )
    .get(templateKey);

  return serializeNotificationTemplateRow(row, templateKey);
}

export function updateNotificationTemplate(templateKey, payload, actorUserId) {
  const defaults = DEFAULT_NOTIFICATION_TEMPLATES[templateKey];
  if (!defaults) {
    throw new Error('通知模板不存在。');
  }

  const subjectTemplate = String(payload.subjectTemplate || '').trim();
  const bodyTemplate = String(payload.bodyTemplate || '').trim();

  if (!subjectTemplate) {
    throw new Error('邮件标题模板不能为空。');
  }

  if (!bodyTemplate) {
    throw new Error('邮件正文模板不能为空。');
  }

  db.prepare(
    `
      INSERT INTO notification_templates (
        template_key,
        name,
        subject_template,
        body_template,
        updated_at,
        updated_by
      ) VALUES (?, ?, ?, ?, ?, ?)
      ON CONFLICT(template_key) DO UPDATE SET
        name = excluded.name,
        subject_template = excluded.subject_template,
        body_template = excluded.body_template,
        updated_at = excluded.updated_at,
        updated_by = excluded.updated_by
    `
  ).run(
    templateKey,
    defaults.name,
    subjectTemplate,
    bodyTemplate,
    nowIso(),
    actorUserId ?? null
  );

  return getNotificationTemplate(templateKey);
}

function getEmailLogById(emailLogId) {
  const row = db
    .prepare(
      `
        SELECT
          email_logs.*,
          orders.order_no,
          users.name AS actor_name
        FROM email_logs
        LEFT JOIN orders ON orders.id = email_logs.order_id
        LEFT JOIN users ON users.id = email_logs.actor_user_id
        WHERE email_logs.id = ?
      `
    )
    .get(emailLogId);

  return row ? serializeEmailLog(row) : null;
}

export function createEmailLog(payload) {
  const emailLogId = randomUUID();

  db.prepare(
    `
      INSERT INTO email_logs (
        id,
        template_key,
        order_id,
        customer_email,
        subject,
        body,
        status,
        transport,
        error_message,
        provider_message_id,
        actor_user_id,
        created_at,
        sent_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `
  ).run(
    emailLogId,
    payload.templateKey,
    payload.orderId ?? null,
    payload.customerEmail,
    payload.subject,
    payload.body,
    payload.status,
    payload.transport,
    payload.errorMessage ?? '',
    payload.providerMessageId ?? '',
    payload.actorUserId ?? null,
    payload.createdAt ?? nowIso(),
    payload.sentAt ?? null
  );

  return getEmailLogById(emailLogId);
}

export function listEmailLogs(limit = 40) {
  const safeLimit = Math.min(Math.max(Number(limit) || 40, 1), 100);
  const rows = db
    .prepare(
      `
        SELECT
          email_logs.*,
          orders.order_no,
          users.name AS actor_name
        FROM email_logs
        LEFT JOIN orders ON orders.id = email_logs.order_id
        LEFT JOIN users ON users.id = email_logs.actor_user_id
        ORDER BY email_logs.created_at DESC
        LIMIT ?
      `
    )
    .all(safeLimit);

  return rows.map(serializeEmailLog);
}

export function listOrders(filters = {}) {
  const clauses = ['1 = 1'];
  const params = [];

  if (filters.query) {
    clauses.push(
      '(orders.order_no LIKE ? OR customers.company_name LIKE ? OR customers.phone LIKE ? OR customers.email LIKE ?)'
    );
    const pattern = `%${filters.query}%`;
    params.push(pattern, pattern, pattern, pattern);
  }

  if (filters.status && filters.status !== 'all') {
    clauses.push('orders.status = ?');
    params.push(filters.status);
  }

  if (filters.priority && filters.priority !== 'all') {
    clauses.push('orders.priority = ?');
    params.push(filters.priority);
  }

  const rows = db
    .prepare(
      `
        SELECT
          orders.*,
          customers.company_name,
          customers.contact_name,
          customers.phone AS customer_phone,
          customers.email AS customer_email,
          customers.notes AS customer_notes
        FROM orders
        JOIN customers ON customers.id = orders.customer_id
        WHERE ${clauses.join(' AND ')}
        ORDER BY
          CASE WHEN orders.status = 'cancelled' THEN 1 ELSE 0 END,
          CASE orders.priority
            WHEN 'rush' THEN 0
            WHEN 'rework' THEN 1
            WHEN 'hold' THEN 2
            ELSE 3
          END,
          orders.updated_at DESC
      `
    )
    .all(...params);

  return rows.map((row) => hydrateOrder(row));
}

export function getOrderById(orderId) {
  return hydrateOrder(getJoinedOrderRow(orderId), {
    includeTimeline: true,
    includeVersions: true,
  });
}

export function createOrder(payload) {
  const customer = db.prepare('SELECT id FROM customers WHERE id = ?').get(payload.customerId);
  if (!customer) {
    throw new Error('客户不存在，请先创建客户。');
  }

  const orderId = randomUUID();
  const orderNo = generateOrderNumber();
  const timestamp = nowIso();

  const transaction = db.transaction(() => {
    db.prepare(
      `
        INSERT INTO orders (
          id,
          order_no,
          customer_id,
          status,
          priority,
          glass_type,
          thickness,
          quantity,
          estimated_completion_date,
          special_instructions,
          drawing_path,
          drawing_name,
          created_by,
          created_at,
          updated_at,
          last_production_activity_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `
    ).run(
      orderId,
      orderNo,
      payload.customerId,
      ORDER_STATUSES.RECEIVED,
      payload.priority ?? PRIORITIES.NORMAL,
      payload.glassType,
      payload.thickness,
      payload.quantity,
      payload.estimatedCompletionDate ?? null,
      payload.specialInstructions ?? '',
      payload.drawingPath ?? null,
      payload.drawingName ?? null,
      payload.createdBy ?? null,
      timestamp,
      timestamp,
      timestamp
    );

    const insertStep = db.prepare(
      `
        INSERT INTO order_steps (
          id,
          order_id,
          step_key,
          step_label,
          step_index,
          status,
          updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
      `
    );

    PRODUCTION_STEPS.forEach((step, index) => {
      insertStep.run(
        randomUUID(),
        orderId,
        step.key,
        step.label,
        index,
        STEP_STATUSES.PENDING,
        timestamp
      );
    });

    const createdOrder = requireOrder(orderId);
    createOrderVersion(orderId, 'created', payload.createdBy ?? null, '', createdOrder);

    createEvent(orderId, 'order_created', '订单已创建。', payload.createdBy, {
      orderNo,
      status: ORDER_STATUSES.RECEIVED,
    });
  });

  transaction();
  return getOrderById(orderId);
}

export function updateOrder(orderId, payload, actorUserId) {
  const current = requireOrder(orderId);
  if (current.status === ORDER_STATUSES.PICKED_UP) {
    throw new Error('订单已取货，不能再修改。');
  }
  if (current.status === ORDER_STATUSES.CANCELLED) {
    throw new Error('订单已取消，不能再修改。');
  }

  const nextCustomerId = payload.customerId ?? current.customer_id;
  let nextCustomer = null;
  if (nextCustomerId !== current.customer_id) {
    nextCustomer = db
      .prepare(
        `
          SELECT id, company_name
          FROM customers
          WHERE id = ?
        `
      )
      .get(nextCustomerId);

    if (!nextCustomer) {
      throw new Error('客户不存在，请先创建客户。');
    }
  }

  const nextValues = {
    customerId: nextCustomerId,
    glassType: payload.glassType ?? current.glass_type,
    thickness: payload.thickness ?? current.thickness,
    quantity: payload.quantity ?? current.quantity,
    estimatedCompletionDate:
      payload.estimatedCompletionDate ?? current.estimated_completion_date,
    specialInstructions:
      payload.specialInstructions ?? current.special_instructions,
    priority: payload.priority ?? current.priority,
    drawingPath: payload.drawingPath ?? current.drawing_path,
    drawingName: payload.drawingName ?? current.drawing_name,
    updatedAt: nowIso(),
  };
  const previewRow = {
    ...current,
    customer_id: nextValues.customerId,
    company_name: nextCustomer?.company_name ?? current.company_name,
    glass_type: nextValues.glassType,
    thickness: nextValues.thickness,
    quantity: nextValues.quantity,
    estimated_completion_date: nextValues.estimatedCompletionDate,
    special_instructions: nextValues.specialInstructions,
    priority: nextValues.priority,
    drawing_path: nextValues.drawingPath,
    drawing_name: nextValues.drawingName,
    updated_at: nextValues.updatedAt,
    is_modified: 1,
    version: Number(current.version ?? 1) + 1,
  };
  const changes = diffOrderSnapshots(current, previewRow);
  if (!changes.length) {
    return getOrderById(orderId);
  }

  const changedFieldsText = changes.map((change) => change.label).join('、');

  const transaction = db.transaction(() => {
    db.prepare(
      `
        UPDATE orders
        SET
          customer_id = ?,
          glass_type = ?,
          thickness = ?,
          quantity = ?,
          estimated_completion_date = ?,
          special_instructions = ?,
          priority = ?,
          drawing_path = ?,
          drawing_name = ?,
          is_modified = 1,
          version = version + 1,
          updated_at = ?
        WHERE id = ?
      `
    ).run(
      nextValues.customerId,
      nextValues.glassType,
      nextValues.thickness,
      nextValues.quantity,
      nextValues.estimatedCompletionDate,
      nextValues.specialInstructions,
      nextValues.priority,
      nextValues.drawingPath,
      nextValues.drawingName,
      nextValues.updatedAt,
      orderId
    );

    const updatedOrder = requireOrder(orderId);
    createOrderVersion(orderId, 'updated', actorUserId, '', updatedOrder, changes);

    createEvent(
      orderId,
      'order_updated',
      `订单内容已修改（${changedFieldsText}），生产端已收到高亮提醒。`,
      actorUserId,
      {
        changes,
        priority: nextValues.priority,
        quantity: nextValues.quantity,
      }
    );

    for (const step of PRODUCTION_STEPS) {
      notifyStageWorkers(step.key, {
        orderId,
        severity: 'warning',
        title: '订单已修改',
        message: `${updatedOrder.order_no} 已被修改，请重点确认：${changedFieldsText}。`,
      });
    }

    notifySupervisors({
      orderId,
      severity: 'warning',
      title: '订单有变更',
      message: `${updatedOrder.order_no} 已被修改，变更字段：${changedFieldsText}。`,
    });
  });

  transaction();
  return getOrderById(orderId);
}

export function cancelOrder(orderId, reason, actorUserId) {
  const current = requireOrder(orderId);
  if (current.status === ORDER_STATUSES.CANCELLED) {
    return getOrderById(orderId);
  }
  if (!CANCELLABLE_ORDER_STATUSES.has(current.status)) {
    throw new Error('只有尚未开始生产的订单才允许撤回或取消。');
  }

  const startedSteps = db
    .prepare(
      `
        SELECT COUNT(*) AS count
        FROM order_steps
        WHERE order_id = ?
          AND (status != ? OR started_at IS NOT NULL OR completed_at IS NOT NULL)
      `
    )
    .get(orderId, STEP_STATUSES.PENDING);

  if (Number(startedSteps.count) > 0) {
    throw new Error('订单已经进入生产，不能再撤回。');
  }

  const cancelledReason = String(reason || '').trim();
  const timestamp = nowIso();
  const message = cancelledReason ? `订单已取消：${cancelledReason}` : '订单已撤回。';

  const transaction = db.transaction(() => {
    updateOrderStatus(orderId, ORDER_STATUSES.CANCELLED, {
      cancelledAt: timestamp,
      cancelledReason,
      readyForPickupAt: null,
      pickedUpAt: null,
      pickupApprovedAt: null,
      pickupApprovedBy: null,
      pickupSignerName: null,
      pickupSignaturePath: null,
      reworkOpen: 0,
      version: Number(current.version ?? 1) + 1,
    });

    const cancelledOrder = requireOrder(orderId);
    const changes = diffOrderSnapshots(current, cancelledOrder);

    createOrderVersion(orderId, 'cancelled', actorUserId, cancelledReason, cancelledOrder, changes);
    createEvent(orderId, 'order_cancelled', message, actorUserId, {
      reason: cancelledReason,
      status: ORDER_STATUSES.CANCELLED,
    });

    notifyOffice({
      orderId,
      severity: 'warning',
      title: '订单已取消',
      message: `${current.order_no} 已被撤回${cancelledReason ? `：${cancelledReason}` : '。'}`,
    });

    notifySupervisors({
      orderId,
      severity: 'warning',
      title: '订单已取消',
      message: `${current.order_no} 已被撤回${cancelledReason ? `：${cancelledReason}` : '。'}`,
    });

    if (current.status === ORDER_STATUSES.ENTERED) {
      notifyStageWorkers('cutting', {
        orderId,
        severity: 'warning',
        title: '订单已取消',
        message: `${current.order_no} 已撤回，无需继续准备切玻璃。`,
      });
    }
  });

  transaction();
  return getOrderById(orderId);
}

export function markOrderEntered(orderId, actorUserId) {
  const current = requireOrder(orderId);

  if (current.status !== ORDER_STATUSES.RECEIVED) {
    return getOrderById(orderId);
  }

  const timestamp = nowIso();

  const transaction = db.transaction(() => {
    updateOrderStatus(orderId, ORDER_STATUSES.ENTERED, {
      enteredAt: timestamp,
      lastProductionActivityAt: timestamp,
    });

    createEvent(orderId, 'order_entered', '订单已录入系统，推送到切玻璃工位。', actorUserId, {
      status: ORDER_STATUSES.ENTERED,
    });

    notifyStageWorkers('cutting', {
      orderId,
      severity: 'info',
      title: '新订单待切玻璃',
      message: `${current.order_no} 已录入系统，请开始第一道工序。`,
    });
  });

  transaction();
  return getOrderById(orderId);
}

export function startStep(orderId, stepKey, actorUserId) {
  const order = requireOrder(orderId);
  if (order.status === ORDER_STATUSES.CANCELLED) {
    throw new Error('订单已取消，不能继续生产。');
  }
  if (order.status === ORDER_STATUSES.PICKED_UP) {
    throw new Error('订单已完成提货，不能继续生产。');
  }

  const step = requireStep(orderId, stepKey);
  ensurePreviousStepsCompleted(orderId, step.step_index);

  if (step.status === STEP_STATUSES.COMPLETED) {
    return getOrderById(orderId);
  }

  const timestamp = nowIso();

  const transaction = db.transaction(() => {
    db.prepare(
      `
        UPDATE order_steps
        SET
          status = ?,
          started_at = COALESCE(started_at, ?),
          updated_at = ?,
          rework_unread = CASE WHEN step_key = 'cutting' THEN 0 ELSE rework_unread END
        WHERE order_id = ? AND step_key = ?
      `
    ).run(STEP_STATUSES.IN_PROGRESS, timestamp, timestamp, orderId, stepKey);

    updateOrderStatus(orderId, ORDER_STATUSES.IN_PRODUCTION, {
      enteredAt: order.entered_at ?? timestamp,
      lastProductionActivityAt: timestamp,
    });

    createEvent(orderId, 'step_started', `${step.step_label} 已开始。`, actorUserId, {
      stepKey,
      status: STEP_STATUSES.IN_PROGRESS,
    });
  });

  transaction();
  return getOrderById(orderId);
}

export function completeStep(orderId, stepKey, actorUserId) {
  const order = requireOrder(orderId);
  if (order.status === ORDER_STATUSES.CANCELLED) {
    throw new Error('订单已取消，不能继续生产。');
  }
  if (order.status === ORDER_STATUSES.PICKED_UP) {
    throw new Error('订单已完成提货，不能继续生产。');
  }

  const step = requireStep(orderId, stepKey);
  ensurePreviousStepsCompleted(orderId, step.step_index);

  const timestamp = nowIso();

  const transaction = db.transaction(() => {
    db.prepare(
      `
        UPDATE order_steps
        SET
          status = ?,
          started_at = COALESCE(started_at, ?),
          completed_at = ?,
          updated_at = ?,
          rework_unread = 0
        WHERE order_id = ? AND step_key = ?
      `
    ).run(STEP_STATUSES.COMPLETED, timestamp, timestamp, timestamp, orderId, stepKey);

    updateOrderStatus(orderId, ORDER_STATUSES.IN_PRODUCTION, {
      enteredAt: order.entered_at ?? timestamp,
      lastProductionActivityAt: timestamp,
      reworkOpen: stepKey === 'cutting' ? 0 : order.rework_open,
    });

    createEvent(orderId, 'step_completed', `${step.step_label} 已完成。`, actorUserId, {
      stepKey,
      status: STEP_STATUSES.COMPLETED,
    });

    recalculateCompletionState(orderId, actorUserId);
  });

  transaction();
  return getOrderById(orderId);
}

export function reportRework(orderId, stepKey, pieceNumbers, note, actorUserId) {
  const normalizedPieceNumbers = normalizePieceNumbers(pieceNumbers);
  if (!normalizedPieceNumbers.length) {
    throw new Error('请至少选择一片需要返工的玻璃。');
  }

  const order = requireOrder(orderId);
  if (order.status === ORDER_STATUSES.CANCELLED) {
    throw new Error('订单已取消，不能再发起返工。');
  }
  if (stepKey === 'cutting') {
    throw new Error('切玻璃工位可直接重做，不需要回推返工。');
  }
  const step = requireStep(orderId, stepKey);
  const cuttingStep = requireStep(orderId, 'cutting');
  const orderQuantity = Number(order.quantity ?? 0);
  if (normalizedPieceNumbers.some((pieceNumber) => pieceNumber > orderQuantity)) {
    throw new Error(`返工片号超出范围，当前订单只有 ${orderQuantity} 片。`);
  }

  const openPieceNumbers = new Set(
    serializeReworkRequests(orderId, { limit: 100 })
      .filter((request) => !request.isAcknowledged)
      .flatMap((request) => request.pieceNumbers)
  );
  const duplicatedPieces = normalizedPieceNumbers.filter((pieceNumber) =>
    openPieceNumbers.has(pieceNumber)
  );
  if (duplicatedPieces.length) {
    throw new Error(`${formatPieceNumbers(duplicatedPieces)} 已在返工队列中。`);
  }

  const pieceSummary = formatPieceNumbers(normalizedPieceNumbers);
  const pieceCount = normalizedPieceNumbers.length;
  const timestamp = nowIso();

  const transaction = db.transaction(() => {
    db.prepare(
      `
        UPDATE order_steps
        SET
          rework_count = rework_count + ?,
          rework_note = ?,
          updated_at = ?
        WHERE order_id = ? AND step_key = ?
      `
    ).run(pieceCount, note ?? '', timestamp, orderId, stepKey);

    db.prepare(
      `
        UPDATE order_steps
        SET
          rework_count = rework_count + ?,
          rework_note = ?,
          rework_unread = 1,
          status = ?,
          completed_at = NULL,
          updated_at = ?
        WHERE order_id = ? AND step_key = 'cutting'
      `
    ).run(
      pieceCount,
      `${step.step_label} 回推返工：${pieceSummary}${note ? `；${note}` : ''}`,
      cuttingStep.status === STEP_STATUSES.IN_PROGRESS
        ? STEP_STATUSES.IN_PROGRESS
        : STEP_STATUSES.PENDING,
      timestamp,
      orderId
    );

    db.prepare(
      `
        INSERT INTO rework_requests (
          id,
          order_id,
          source_step_key,
          source_step_label,
          piece_numbers_json,
          piece_count,
          note,
          actor_user_id,
          created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
      `
    ).run(
      randomUUID(),
      orderId,
      stepKey,
      step.step_label,
      JSON.stringify(normalizedPieceNumbers),
      pieceCount,
      note ?? '',
      actorUserId,
      timestamp
    );

    updateOrderStatus(orderId, ORDER_STATUSES.IN_PRODUCTION, {
      enteredAt: order.entered_at ?? timestamp,
      lastProductionActivityAt: timestamp,
      reworkOpen: 1,
    });

    createEvent(
      orderId,
      'step_rework',
      `${step.step_label} 标记返工 ${pieceSummary}，已回推切玻璃工位。`,
      actorUserId,
      { stepKey, pieceNumbers: normalizedPieceNumbers, note }
    );

    notifyStageWorkers('cutting', {
      orderId,
      severity: 'warning',
      title: '返工高亮',
      message: `${order.order_no} 在 ${step.step_label} 标记返工：${pieceSummary}${
        note ? `。说明：${note}` : '。'
      }`,
    });

    notifySupervisors({
      orderId,
      severity: 'warning',
      title: '订单返工',
      message: `${order.order_no} 在 ${step.step_label} 标记返工：${pieceSummary}。`,
    });
  });

  transaction();
  return getOrderById(orderId);
}

export function acknowledgeRework(orderId, actorUserId) {
  const openRequests = db
    .prepare(
      `
        SELECT COUNT(*) AS count
        FROM rework_requests
        WHERE order_id = ? AND is_acknowledged = 0
      `
    )
    .get(orderId);

  if (Number(openRequests.count) === 0) {
    return getOrderById(orderId);
  }

  const timestamp = nowIso();

  const transaction = db.transaction(() => {
    db.prepare(
      `
        UPDATE order_steps
        SET
          rework_unread = 0,
          updated_at = ?
        WHERE order_id = ? AND step_key = 'cutting'
      `
    ).run(timestamp, orderId);

    db.prepare(
      `
        UPDATE rework_requests
        SET
          is_acknowledged = 1,
          acknowledged_at = ?,
          acknowledged_by = ?
        WHERE order_id = ? AND is_acknowledged = 0
      `
    ).run(timestamp, actorUserId, orderId);

    db.prepare('UPDATE orders SET rework_open = 0 WHERE id = ?').run(orderId);

    createEvent(orderId, 'rework_acknowledged', '切玻璃工位已确认返工提醒。', actorUserId);
  });

  transaction();
  return getOrderById(orderId);
}

export function approvePickup(orderId, actorUserId) {
  const order = requireOrder(orderId);
  if (order.status === ORDER_STATUSES.CANCELLED) {
    throw new Error('订单已取消，不能批准 pickup。');
  }
  if (order.status !== ORDER_STATUSES.COMPLETED) {
    throw new Error('只有已完成订单才能批准 pickup。');
  }

  const timestamp = nowIso();

  const transaction = db.transaction(() => {
    updateOrderStatus(orderId, ORDER_STATUSES.READY_FOR_PICKUP, {
      readyForPickupAt: timestamp,
      pickupApprovedAt: timestamp,
      pickupApprovedBy: actorUserId,
      lastProductionActivityAt: order.last_production_activity_at,
    });

    createEvent(orderId, 'pickup_approved', '主管已批准取货，可以调出签字界面。', actorUserId, {
      status: ORDER_STATUSES.READY_FOR_PICKUP,
    });

    notifyOffice({
      orderId,
      severity: 'success',
      title: '可取货',
      message: `${order.order_no} 已批准 pickup，可请客户现场签字。`,
    });

    notifyStageWorkers('finishing', {
      orderId,
      severity: 'info',
      title: '准备出货',
      message: `${order.order_no} 已批准 pickup，可安排仓库协助取货。`,
    });
  });

  transaction();
  return getOrderById(orderId);
}

export function recordPickupSignature(orderId, payload, actorUserId) {
  const order = requireOrder(orderId);
  if (order.status === ORDER_STATUSES.CANCELLED) {
    throw new Error('订单已取消，不能签字取货。');
  }
  if (order.status !== ORDER_STATUSES.READY_FOR_PICKUP) {
    throw new Error('订单尚未批准 pickup，不能签字。');
  }

  const timestamp = nowIso();

  const transaction = db.transaction(() => {
    updateOrderStatus(orderId, ORDER_STATUSES.PICKED_UP, {
      pickedUpAt: timestamp,
      pickupSignerName: payload.signerName,
      pickupSignaturePath: payload.signaturePath,
      lastProductionActivityAt: order.last_production_activity_at,
    });

    createEvent(orderId, 'pickup_signed', '客户已完成电子签字并提货。', actorUserId, {
      signerName: payload.signerName,
      status: ORDER_STATUSES.PICKED_UP,
    });

    notifySupervisors({
      orderId,
      severity: 'success',
      title: '已完成取货',
      message: `${order.order_no} 已由 ${payload.signerName} 完成签字提货。`,
    });
  });

  transaction();
  return getOrderById(orderId);
}

export function listNotificationsForUser(userId) {
  const rows = db
    .prepare(
      `
        SELECT
          notifications.*,
          orders.order_no
        FROM notifications
        LEFT JOIN orders ON orders.id = notifications.order_id
        WHERE notifications.user_id = ?
        ORDER BY notifications.is_read ASC, notifications.created_at DESC
        LIMIT 100
      `
    )
    .all(userId);

  return rows.map((row) => ({
    id: row.id,
    orderId: row.order_id,
    orderNo: row.order_no,
    title: row.title,
    message: row.message,
    severity: row.severity,
    isRead: Boolean(row.is_read),
    createdAt: row.created_at,
  }));
}

export function listNotificationTemplates() {
  return Object.keys(DEFAULT_NOTIFICATION_TEMPLATES).map((templateKey) =>
    getNotificationTemplate(templateKey)
  );
}

export function markNotificationsRead(userId) {
  db.prepare(
    `
      UPDATE notifications
      SET is_read = 1
      WHERE user_id = ?
    `
  ).run(userId);

  return listNotificationsForUser(userId);
}

export function getDashboardSummary(user) {
  const orders = listOrders();
  const customers = listCustomers();
  const summary = {
    totalOrders: orders.length,
    activeOrders: orders.filter((order) => ACTIVE_STATUS_SET.has(order.status)).length,
    inProductionOrders: orders.filter(
      (order) => order.status === ORDER_STATUSES.IN_PRODUCTION
    ).length,
    readyForPickupOrders: orders.filter(
      (order) => order.status === ORDER_STATUSES.READY_FOR_PICKUP
    ).length,
    staleOrders: orders.filter((order) => order.isStale).length,
    rushOrders: orders.filter((order) => order.priority === PRIORITIES.RUSH).length,
    reworkOrders: orders.filter((order) => order.reworkOpen).length,
    modifiedOrders: orders.filter((order) => order.isModified).length,
    activeCustomers: customers.filter((customer) => customer.hasActiveOrders).length,
  };

  if (user.role === ROLES.WORKER && user.stage) {
    const workerOrders = orders.filter((order) => {
      const step = order.steps.find((candidate) => candidate.key === user.stage);
      return step && step.status !== STEP_STATUSES.COMPLETED;
    });

    summary.workerQueue = workerOrders.length;
    summary.workerReady = workerOrders.filter((order) => {
      const step = order.steps.find((candidate) => candidate.key === user.stage);
      return step?.isAvailable || step?.status === STEP_STATUSES.IN_PROGRESS;
    }).length;
  }

  return summary;
}

export function getBootstrapData(user) {
  return {
    customers: listCustomers(),
    orders: listOrders(),
    notifications: listNotificationsForUser(user.id),
    summary: getDashboardSummary(user),
  };
}

export function getDatabasePath() {
  return SQLITE_DATABASE_PATH;
}

export { serializeUser };