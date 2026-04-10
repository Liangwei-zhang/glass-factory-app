import { randomUUID } from 'node:crypto';

import bcrypt from 'bcryptjs';
import { Pool } from 'pg';

import { POSTGRES_SCHEMA_SQL } from '../../scripts/postgres-schema.js';
import {
  POSTGRES_DATABASE_URL,
  requirePostgresDatabaseUrl,
} from '../config.js';
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
} from '../constants.js';
import { getPostgresConnectionInfo } from './postgres-client.js';

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

let pool = null;

function getPool() {
  if (!pool) {
    pool = new Pool({ connectionString: requirePostgresDatabaseUrl() });
  }

  return pool;
}

function getExecutor(executor = null) {
  return executor ?? getPool();
}

async function queryRows(text, params = [], executor = null) {
  const result = await getExecutor(executor).query(text, params);
  return result.rows;
}

async function queryOne(text, params = [], executor = null) {
  const rows = await queryRows(text, params, executor);
  return rows[0] ?? null;
}

async function execute(text, params = [], executor = null) {
  await getExecutor(executor).query(text, params);
}

async function withTransaction(callback) {
  const client = await getPool().connect();

  try {
    await client.query('BEGIN');
    const result = await callback(client);
    await client.query('COMMIT');
    return result;
  } catch (error) {
    try {
      await client.query('ROLLBACK');
    } catch {
      // Ignore rollback errors and surface the original failure.
    }

    throw error;
  } finally {
    client.release();
  }
}

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
    index: Number(row.step_index),
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

async function serializeEvents(orderId, executor = null) {
  const rows = await queryRows(
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
      WHERE events.order_id = $1
      ORDER BY events.created_at DESC
      LIMIT 18
    `,
    [orderId],
    executor
  );

  return rows.map((row) => ({
    id: row.id,
    type: row.type,
    message: row.message,
    actorName: row.actor_name ?? '系统',
    createdAt: row.created_at,
    metadata: row.metadata_json ? JSON.parse(row.metadata_json) : {},
  }));
}

async function serializeVersions(orderId, executor = null) {
  const rows = await queryRows(
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
      WHERE versions.order_id = $1
      ORDER BY versions.version_number DESC, versions.created_at DESC
      LIMIT 12
    `,
    [orderId],
    executor
  );

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

async function serializeReworkRequests(orderId, { limit = 24 } = {}, executor = null) {
  const rows = await queryRows(
    `
      SELECT
        rework_requests.*,
        actors.name AS actor_name,
        acknowledged_by_users.name AS acknowledged_by_name
      FROM rework_requests
      LEFT JOIN users AS actors ON actors.id = rework_requests.actor_user_id
      LEFT JOIN users AS acknowledged_by_users ON acknowledged_by_users.id = rework_requests.acknowledged_by
      WHERE rework_requests.order_id = $1
      ORDER BY rework_requests.created_at DESC
      LIMIT $2
    `,
    [orderId, limit],
    executor
  );

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

async function hydrateOrder(row, { includeTimeline = false, includeVersions = false } = {}, executor = null) {
  if (!row) {
    return null;
  }

  const steps = serializeSteps(
    await queryRows(
      `
        SELECT *
        FROM order_steps
        WHERE order_id = $1
        ORDER BY step_index ASC
      `,
      [row.id],
      executor
    )
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
    ? await serializeReworkRequests(row.id, { limit: includeTimeline ? 24 : 8 }, executor)
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
    timeline: includeTimeline ? await serializeEvents(row.id, executor) : [],
    versionHistory: includeVersions ? await serializeVersions(row.id, executor) : [],
  };
}

async function getUserRowsByRole(role, stage = null, executor = null) {
  if (stage) {
    return await queryRows(
      `
        SELECT id
        FROM users
        WHERE role = $1 AND stage = $2
      `,
      [role, stage],
      executor
    );
  }

  return await queryRows(
    `
      SELECT id
      FROM users
      WHERE role = $1
    `,
    [role],
    executor
  );
}

async function notifyUsers(userIds, payload, executor = null) {
  const uniqueUserIds = [...new Set(userIds)];

  if (!uniqueUserIds.length) {
    return;
  }

  const createdAt = nowIso();

  for (const userId of uniqueUserIds) {
    await execute(
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
        ) VALUES ($1, $2, $3, $4, $5, $6, 0, $7)
      `,
      [
        randomUUID(),
        userId,
        payload.orderId ?? null,
        payload.title,
        payload.message,
        payload.severity ?? 'info',
        createdAt,
      ],
      executor
    );
  }
}

async function notifyOffice(payload, executor = null) {
  const rows = await getUserRowsByRole(ROLES.OFFICE, null, executor);
  await notifyUsers(
    rows.map((row) => row.id),
    payload,
    executor
  );
}

async function notifySupervisors(payload, executor = null) {
  const rows = await getUserRowsByRole(ROLES.SUPERVISOR, null, executor);
  await notifyUsers(
    rows.map((row) => row.id),
    payload,
    executor
  );
}

async function notifyStageWorkers(stage, payload, executor = null) {
  const rows = await getUserRowsByRole(ROLES.WORKER, stage, executor);
  await notifyUsers(
    rows.map((row) => row.id),
    payload,
    executor
  );
}

async function createEvent(orderId, type, message, actorUserId = null, metadata = {}, executor = null) {
  await execute(
    `
      INSERT INTO order_events (
        id,
        order_id,
        type,
        message,
        actor_user_id,
        metadata_json,
        created_at
      ) VALUES ($1, $2, $3, $4, $5, $6, $7)
    `,
    [
      randomUUID(),
      orderId,
      type,
      message,
      actorUserId,
      JSON.stringify(metadata),
      nowIso(),
    ],
    executor
  );
}

async function createOrderVersion(
  orderId,
  eventType,
  actorUserId,
  reason,
  orderRow,
  changes = [],
  executor = null
) {
  await execute(
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
      ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
    `,
    [
      randomUUID(),
      orderId,
      Number(orderRow.version ?? 1),
      eventType,
      reason ?? '',
      actorUserId,
      JSON.stringify(buildOrderSnapshot(orderRow)),
      JSON.stringify(changes),
      nowIso(),
    ],
    executor
  );
}

async function generateOrderNumber(executor = null) {
  const dateStamp = new Date().toISOString().slice(0, 10).replaceAll('-', '');
  const prefix = `GF${dateStamp}`;
  const lastRow = await queryOne(
    `
      SELECT order_no
      FROM orders
      WHERE order_no LIKE $1
      ORDER BY order_no DESC
      LIMIT 1
    `,
    [`${prefix}-%`],
    executor
  );
  const lastSequence = lastRow ? Number(String(lastRow.order_no).split('-').pop()) : 0;
  return `${prefix}-${String(lastSequence + 1).padStart(4, '0')}`;
}

async function requireOrder(orderId, executor = null) {
  const row = await queryOne(
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
      WHERE orders.id = $1
    `,
    [orderId],
    executor
  );

  if (!row) {
    throw new Error('订单不存在。');
  }

  return row;
}

async function requireStep(orderId, stepKey, executor = null) {
  const row = await queryOne(
    `
      SELECT *
      FROM order_steps
      WHERE order_id = $1 AND step_key = $2
    `,
    [orderId, stepKey],
    executor
  );

  if (!row) {
    throw new Error('工序不存在。');
  }

  return row;
}

async function ensurePreviousStepsCompleted(orderId, stepIndex, executor = null) {
  const previousIncomplete = await queryOne(
    `
      SELECT COUNT(*) AS count
      FROM order_steps
      WHERE order_id = $1 AND step_index < $2 AND status != $3
    `,
    [orderId, stepIndex, STEP_STATUSES.COMPLETED],
    executor
  );

  if (Number(previousIncomplete?.count ?? 0) > 0) {
    throw new Error('上一个工序未完成，不能继续流转。');
  }
}

async function getJoinedOrderRow(orderId, executor = null) {
  return await queryOne(
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
      WHERE orders.id = $1
    `,
    [orderId],
    executor
  );
}

async function updateOrderStatus(orderId, status, patch = {}, executor = null) {
  const current = await requireOrder(orderId, executor);
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

  await execute(
    `
      UPDATE orders
      SET
        status = $1,
        updated_at = $2,
        entered_at = $3,
        completed_at = $4,
        cancelled_at = $5,
        cancelled_reason = $6,
        ready_for_pickup_at = $7,
        picked_up_at = $8,
        pickup_approved_at = $9,
        pickup_approved_by = $10,
        pickup_signer_name = $11,
        pickup_signature_path = $12,
        last_production_activity_at = $13,
        rework_open = $14,
        version = $15
      WHERE id = $16
    `,
    [
      values.status,
      values.updatedAt,
      values.enteredAt,
      values.completedAt,
      values.cancelledAt,
      values.cancelledReason,
      values.readyForPickupAt,
      values.pickedUpAt,
      values.pickupApprovedAt,
      values.pickupApprovedBy,
      values.pickupSignerName,
      values.pickupSignaturePath,
      values.lastProductionActivityAt,
      values.reworkOpen,
      values.version,
      values.id,
    ],
    executor
  );
}

async function recalculateCompletionState(orderId, actorUserId, executor = null) {
  const incomplete = await queryOne(
    `
      SELECT COUNT(*) AS count
      FROM order_steps
      WHERE order_id = $1 AND status != $2
    `,
    [orderId, STEP_STATUSES.COMPLETED],
    executor
  );

  if (Number(incomplete?.count ?? 0) === 0) {
    const completedAt = nowIso();
    await updateOrderStatus(
      orderId,
      ORDER_STATUSES.COMPLETED,
      {
        completedAt,
        lastProductionActivityAt: completedAt,
      },
      executor
    );
    const order = await requireOrder(orderId, executor);

    await createEvent(
      orderId,
      'order_completed',
      '全部生产工序完成，订单待主管批准取货。',
      actorUserId,
      { status: ORDER_STATUSES.COMPLETED },
      executor
    );

    await notifyOffice(
      {
        orderId,
        severity: 'success',
        title: '订单已完成',
        message: `${order.order_no} 已完成，可安排主管批准 pickup。`,
      },
      executor
    );

    await notifySupervisors(
      {
        orderId,
        severity: 'success',
        title: '订单待批准取货',
        message: `${order.order_no} 已完工，请确认是否允许 pickup。`,
      },
      executor
    );
  }
}

export async function initDatabase() {
  await getPool().query(POSTGRES_SCHEMA_SQL);

  await seedUsers();
  await seedCustomers();
  await seedGlassTypes();
  await seedNotificationTemplates();
  await seedDemoOrder();
}

async function seedUsers() {
  const row = await queryOne('SELECT COUNT(*) AS count FROM users');
  if (Number(row?.count ?? 0) > 0) {
    return;
  }

  const timestamp = nowIso();
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
    await execute(
      `
        INSERT INTO users (id, name, email, password_hash, role, stage, created_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
      `,
      [
        randomUUID(),
        user.name,
        user.email,
        hash(user.password),
        user.role,
        user.stage,
        timestamp,
      ]
    );
  }
}

async function seedCustomers() {
  const row = await queryOne('SELECT COUNT(*) AS count FROM customers');
  if (Number(row?.count ?? 0) > 0) {
    return;
  }

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
    await execute(
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
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
      `,
      [
        randomUUID(),
        customer.companyName,
        customer.contactName,
        customer.phone,
        customer.email,
        customer.notes,
        timestamp,
        timestamp,
      ]
    );
  }
}

async function seedGlassTypes() {
  const timestamp = nowIso();

  for (const [index, glassTypeName] of GLASS_TYPES.entries()) {
    await execute(
      `
        INSERT INTO glass_types (
          id,
          name,
          sort_order,
          is_active,
          updated_at,
          updated_by
        ) VALUES ($1, $2, $3, 1, $4, NULL)
        ON CONFLICT DO NOTHING
      `,
      [randomUUID(), glassTypeName, index, timestamp]
    );
  }
}

async function seedNotificationTemplates() {
  const timestamp = nowIso();

  for (const [templateKey, template] of Object.entries(DEFAULT_NOTIFICATION_TEMPLATES)) {
    await execute(
      `
        INSERT INTO notification_templates (
          template_key,
          name,
          subject_template,
          body_template,
          updated_at,
          updated_by
        ) VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (template_key) DO NOTHING
      `,
      [
        templateKey,
        template.name,
        template.subjectTemplate,
        template.bodyTemplate,
        timestamp,
        null,
      ]
    );
  }
}

async function seedDemoOrder() {
  if (process.env.SEED_DEMO_DATA === 'false') {
    return;
  }

  const existing = await queryOne('SELECT COUNT(*) AS count FROM orders');
  if (Number(existing?.count ?? 0) > 0) {
    return;
  }

  const office = await queryOne(
    `
      SELECT *
      FROM users
      WHERE role = $1
      LIMIT 1
    `,
    [ROLES.OFFICE]
  );
  const customer = await queryOne(
    `
      SELECT *
      FROM customers
      ORDER BY created_at ASC
      LIMIT 1
    `
  );

  if (!office || !customer) {
    return;
  }

  const order = await createOrder({
    customerId: customer.id,
    glassType: 'Clear',
    thickness: '6mm',
    quantity: 12,
    priority: PRIORITIES.RUSH,
    estimatedCompletionDate: new Date(Date.now() + 2 * 24 * 60 * 60 * 1000).toISOString(),
    specialInstructions: '样板订单：前 2 片先做，客户下午确认。',
    createdBy: office.id,
  });

  await markOrderEntered(order.id, office.id);
}

export async function getUserByEmail(email) {
  return await queryOne('SELECT * FROM users WHERE email = $1', [email]);
}

export async function getUserById(userId) {
  return await queryOne('SELECT * FROM users WHERE id = $1', [userId]);
}

export async function listCustomers() {
  const activeStatuses = ACTIVE_ORDER_STATUSES;
  const statusPlaceholders = activeStatuses.map((_, index) => `$${index + 1}`).join(', ');
  const rows = await queryRows(
    `
      SELECT
        customers.*,
        COUNT(orders.id) AS total_orders,
        SUM(CASE WHEN orders.status IN (${statusPlaceholders}) THEN 1 ELSE 0 END) AS active_orders,
        MAX(orders.created_at) AS last_order_at
      FROM customers
      LEFT JOIN orders ON orders.customer_id = customers.id
      GROUP BY customers.id
      ORDER BY LOWER(customers.company_name) ASC
    `,
    activeStatuses
  );

  return rows.map(serializeCustomer);
}

export async function createCustomer(payload) {
  const timestamp = nowIso();
  const customerId = randomUUID();

  await execute(
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
      ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
    `,
    [
      customerId,
      payload.companyName,
      payload.contactName ?? '',
      payload.phone ?? '',
      payload.email ?? '',
      payload.notes ?? '',
      timestamp,
      timestamp,
    ]
  );

  return (await listCustomers()).find((customer) => customer.id === customerId) ?? null;
}

export async function updateCustomer(customerId, payload) {
  const current = await queryOne('SELECT * FROM customers WHERE id = $1', [customerId]);
  if (!current) {
    throw new Error('客户不存在。');
  }

  await execute(
    `
      UPDATE customers
      SET
        company_name = $1,
        contact_name = $2,
        phone = $3,
        email = $4,
        notes = $5,
        updated_at = $6
      WHERE id = $7
    `,
    [
      payload.companyName ?? current.company_name,
      payload.contactName ?? current.contact_name,
      payload.phone ?? current.phone,
      payload.email ?? current.email,
      payload.notes ?? current.notes,
      nowIso(),
      customerId,
    ]
  );

  return (await listCustomers()).find((customer) => customer.id === customerId) ?? null;
}

async function requireGlassType(glassTypeId, executor = null) {
  const row = await queryOne('SELECT * FROM glass_types WHERE id = $1', [glassTypeId], executor);

  if (!row) {
    throw new Error('玻璃类型不存在。');
  }

  return row;
}

export async function listGlassTypes({ includeInactive = false } = {}) {
  const activeStatuses = ACTIVE_ORDER_STATUSES;
  const statusPlaceholders = activeStatuses.map((_, index) => `$${index + 1}`).join(', ');
  const whereClause = includeInactive ? '' : 'WHERE glass_types.is_active = 1';
  const rows = await queryRows(
    `
      SELECT
        glass_types.*,
        users.name AS updated_by_name,
        COUNT(orders.id) AS total_order_count,
        SUM(CASE WHEN orders.status IN (${statusPlaceholders}) THEN 1 ELSE 0 END) AS active_order_count
      FROM glass_types
      LEFT JOIN users ON users.id = glass_types.updated_by
      LEFT JOIN orders ON LOWER(orders.glass_type) = LOWER(glass_types.name)
      ${whereClause}
      GROUP BY glass_types.id, users.name
      ORDER BY glass_types.sort_order ASC, LOWER(glass_types.name) ASC
    `,
    activeStatuses
  );

  return rows.map(serializeGlassTypeRow);
}

export async function createGlassType(name, actorUserId) {
  const normalizedName = String(name || '').trim();
  if (!normalizedName) {
    throw new Error('玻璃类型名称不能为空。');
  }
  if (normalizedName.length > 48) {
    throw new Error('玻璃类型名称不能超过 48 个字符。');
  }

  const duplicate = await queryOne(
    'SELECT id FROM glass_types WHERE LOWER(name) = LOWER($1)',
    [normalizedName]
  );
  if (duplicate) {
    throw new Error('玻璃类型已存在。');
  }

  const glassTypeId = randomUUID();
  const timestamp = nowIso();
  const maxSortOrder = await queryOne(
    'SELECT COALESCE(MAX(sort_order), -1) AS value FROM glass_types'
  );

  await execute(
    `
      INSERT INTO glass_types (
        id,
        name,
        sort_order,
        is_active,
        updated_at,
        updated_by
      ) VALUES ($1, $2, $3, 1, $4, $5)
    `,
    [
      glassTypeId,
      normalizedName,
      Number(maxSortOrder?.value ?? -1) + 1,
      timestamp,
      actorUserId ?? null,
    ]
  );

  return (await listGlassTypes({ includeInactive: true })).find(
    (glassType) => glassType.id === glassTypeId
  ) ?? null;
}

export async function updateGlassType(glassTypeId, payload, actorUserId) {
  const current = await requireGlassType(glassTypeId);
  const nextName =
    payload.name !== undefined ? String(payload.name || '').trim() : current.name;
  const nextIsActive = normalizeBooleanFlag(payload.isActive, current.is_active);

  if (!nextName) {
    throw new Error('玻璃类型名称不能为空。');
  }
  if (nextName.length > 48) {
    throw new Error('玻璃类型名称不能超过 48 个字符。');
  }

  const duplicate = await queryOne(
    `
      SELECT id
      FROM glass_types
      WHERE LOWER(name) = LOWER($1) AND id != $2
    `,
    [nextName, glassTypeId]
  );
  if (duplicate) {
    throw new Error('玻璃类型已存在。');
  }

  const timestamp = nowIso();

  await withTransaction(async (client) => {
    await execute(
      `
        UPDATE glass_types
        SET
          name = $1,
          is_active = $2,
          updated_at = $3,
          updated_by = $4
        WHERE id = $5
      `,
      [nextName, nextIsActive, timestamp, actorUserId ?? null, glassTypeId],
      client
    );

    if (nextName.toLowerCase() !== String(current.name).toLowerCase()) {
      await execute(
        `
          UPDATE orders
          SET glass_type = $1
          WHERE LOWER(glass_type) = LOWER($2)
        `,
        [nextName, current.name],
        client
      );
    }
  });

  return (await listGlassTypes({ includeInactive: true })).find(
    (glassType) => glassType.id === glassTypeId
  ) ?? null;
}

export async function getNotificationTemplate(templateKey) {
  const defaults = DEFAULT_NOTIFICATION_TEMPLATES[templateKey];
  if (!defaults) {
    throw new Error('通知模板不存在。');
  }

  const row = await queryOne(
    `
      SELECT
        notification_templates.*,
        users.name AS updated_by_name
      FROM notification_templates
      LEFT JOIN users ON users.id = notification_templates.updated_by
      WHERE template_key = $1
    `,
    [templateKey]
  );

  return serializeNotificationTemplateRow(row, templateKey);
}

export async function updateNotificationTemplate(templateKey, payload, actorUserId) {
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

  await execute(
    `
      INSERT INTO notification_templates (
        template_key,
        name,
        subject_template,
        body_template,
        updated_at,
        updated_by
      ) VALUES ($1, $2, $3, $4, $5, $6)
      ON CONFLICT (template_key) DO UPDATE SET
        name = EXCLUDED.name,
        subject_template = EXCLUDED.subject_template,
        body_template = EXCLUDED.body_template,
        updated_at = EXCLUDED.updated_at,
        updated_by = EXCLUDED.updated_by
    `,
    [
      templateKey,
      defaults.name,
      subjectTemplate,
      bodyTemplate,
      nowIso(),
      actorUserId ?? null,
    ]
  );

  return await getNotificationTemplate(templateKey);
}

async function getEmailLogById(emailLogId, executor = null) {
  const row = await queryOne(
    `
      SELECT
        email_logs.*,
        orders.order_no,
        users.name AS actor_name
      FROM email_logs
      LEFT JOIN orders ON orders.id = email_logs.order_id
      LEFT JOIN users ON users.id = email_logs.actor_user_id
      WHERE email_logs.id = $1
    `,
    [emailLogId],
    executor
  );

  return row ? serializeEmailLog(row) : null;
}

export async function createEmailLog(payload) {
  const emailLogId = randomUUID();

  await execute(
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
      ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
    `,
    [
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
      payload.sentAt ?? null,
    ]
  );

  return await getEmailLogById(emailLogId);
}

export async function listEmailLogs(limit = 40) {
  const safeLimit = Math.min(Math.max(Number(limit) || 40, 1), 100);
  const rows = await queryRows(
    `
      SELECT
        email_logs.*,
        orders.order_no,
        users.name AS actor_name
      FROM email_logs
      LEFT JOIN orders ON orders.id = email_logs.order_id
      LEFT JOIN users ON users.id = email_logs.actor_user_id
      ORDER BY email_logs.created_at DESC
      LIMIT $1
    `,
    [safeLimit]
  );

  return rows.map(serializeEmailLog);
}

export async function listOrders(filters = {}) {
  const clauses = ['1 = 1'];
  const params = [];

  if (filters.query) {
    const pattern = `%${filters.query}%`;
    clauses.push(
      `(
        orders.order_no ILIKE $${params.length + 1}
        OR customers.company_name ILIKE $${params.length + 2}
        OR customers.phone ILIKE $${params.length + 3}
        OR customers.email ILIKE $${params.length + 4}
      )`
    );
    params.push(pattern, pattern, pattern, pattern);
  }

  if (filters.status && filters.status !== 'all') {
    clauses.push(`orders.status = $${params.length + 1}`);
    params.push(filters.status);
  }

  if (filters.priority && filters.priority !== 'all') {
    clauses.push(`orders.priority = $${params.length + 1}`);
    params.push(filters.priority);
  }

  const rows = await queryRows(
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
    `,
    params
  );

  return await Promise.all(rows.map((row) => hydrateOrder(row)));
}

export async function getOrderById(orderId) {
  return await hydrateOrder(await getJoinedOrderRow(orderId), {
    includeTimeline: true,
    includeVersions: true,
  });
}

export async function createOrder(payload) {
  const customer = await queryOne('SELECT id FROM customers WHERE id = $1', [payload.customerId]);
  if (!customer) {
    throw new Error('客户不存在，请先创建客户。');
  }

  const orderId = randomUUID();
  const timestamp = nowIso();

  await withTransaction(async (client) => {
    await client.query('LOCK TABLE orders IN SHARE ROW EXCLUSIVE MODE');
    const orderNo = await generateOrderNumber(client);

    await execute(
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
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
      `,
      [
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
        timestamp,
      ],
      client
    );

    for (const [index, step] of PRODUCTION_STEPS.entries()) {
      await execute(
        `
          INSERT INTO order_steps (
            id,
            order_id,
            step_key,
            step_label,
            step_index,
            status,
            updated_at
          ) VALUES ($1, $2, $3, $4, $5, $6, $7)
        `,
        [
          randomUUID(),
          orderId,
          step.key,
          step.label,
          index,
          STEP_STATUSES.PENDING,
          timestamp,
        ],
        client
      );
    }

    const createdOrder = await requireOrder(orderId, client);
    await createOrderVersion(orderId, 'created', payload.createdBy ?? null, '', createdOrder, [], client);

    await createEvent(orderId, 'order_created', '订单已创建。', payload.createdBy, {
      orderNo,
      status: ORDER_STATUSES.RECEIVED,
    }, client);
  });

  return await getOrderById(orderId);
}

export async function updateOrder(orderId, payload, actorUserId) {
  const current = await requireOrder(orderId);
  if (current.status === ORDER_STATUSES.PICKED_UP) {
    throw new Error('订单已取货，不能再修改。');
  }
  if (current.status === ORDER_STATUSES.CANCELLED) {
    throw new Error('订单已取消，不能再修改。');
  }

  const nextCustomerId = payload.customerId ?? current.customer_id;
  let nextCustomer = null;
  if (nextCustomerId !== current.customer_id) {
    nextCustomer = await queryOne(
      `
        SELECT id, company_name
        FROM customers
        WHERE id = $1
      `,
      [nextCustomerId]
    );

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
    return await getOrderById(orderId);
  }

  const changedFieldsText = changes.map((change) => change.label).join('、');

  await withTransaction(async (client) => {
    await execute(
      `
        UPDATE orders
        SET
          customer_id = $1,
          glass_type = $2,
          thickness = $3,
          quantity = $4,
          estimated_completion_date = $5,
          special_instructions = $6,
          priority = $7,
          drawing_path = $8,
          drawing_name = $9,
          is_modified = 1,
          version = version + 1,
          updated_at = $10
        WHERE id = $11
      `,
      [
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
        orderId,
      ],
      client
    );

    const updatedOrder = await requireOrder(orderId, client);
    await createOrderVersion(orderId, 'updated', actorUserId, '', updatedOrder, changes, client);

    await createEvent(
      orderId,
      'order_updated',
      `订单内容已修改（${changedFieldsText}），生产端已收到高亮提醒。`,
      actorUserId,
      {
        changes,
        priority: nextValues.priority,
        quantity: nextValues.quantity,
      },
      client
    );

    for (const step of PRODUCTION_STEPS) {
      await notifyStageWorkers(
        step.key,
        {
          orderId,
          severity: 'warning',
          title: '订单已修改',
          message: `${updatedOrder.order_no} 已被修改，请重点确认：${changedFieldsText}。`,
        },
        client
      );
    }

    await notifySupervisors(
      {
        orderId,
        severity: 'warning',
        title: '订单有变更',
        message: `${updatedOrder.order_no} 已被修改，变更字段：${changedFieldsText}。`,
      },
      client
    );
  });

  return await getOrderById(orderId);
}

export async function cancelOrder(orderId, reason, actorUserId) {
  const current = await requireOrder(orderId);
  if (current.status === ORDER_STATUSES.CANCELLED) {
    return await getOrderById(orderId);
  }
  if (!CANCELLABLE_ORDER_STATUSES.has(current.status)) {
    throw new Error('只有尚未开始生产的订单才允许撤回或取消。');
  }

  const startedSteps = await queryOne(
    `
      SELECT COUNT(*) AS count
      FROM order_steps
      WHERE order_id = $1
        AND (status != $2 OR started_at IS NOT NULL OR completed_at IS NOT NULL)
    `,
    [orderId, STEP_STATUSES.PENDING]
  );

  if (Number(startedSteps?.count ?? 0) > 0) {
    throw new Error('订单已经进入生产，不能再撤回。');
  }

  const cancelledReason = String(reason || '').trim();
  const timestamp = nowIso();
  const message = cancelledReason ? `订单已取消：${cancelledReason}` : '订单已撤回。';

  await withTransaction(async (client) => {
    await updateOrderStatus(
      orderId,
      ORDER_STATUSES.CANCELLED,
      {
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
      },
      client
    );

    const cancelledOrder = await requireOrder(orderId, client);
    const changes = diffOrderSnapshots(current, cancelledOrder);

    await createOrderVersion(
      orderId,
      'cancelled',
      actorUserId,
      cancelledReason,
      cancelledOrder,
      changes,
      client
    );
    await createEvent(orderId, 'order_cancelled', message, actorUserId, {
      reason: cancelledReason,
      status: ORDER_STATUSES.CANCELLED,
    }, client);

    await notifyOffice(
      {
        orderId,
        severity: 'warning',
        title: '订单已取消',
        message: `${current.order_no} 已被撤回${cancelledReason ? `：${cancelledReason}` : '。'}`,
      },
      client
    );

    await notifySupervisors(
      {
        orderId,
        severity: 'warning',
        title: '订单已取消',
        message: `${current.order_no} 已被撤回${cancelledReason ? `：${cancelledReason}` : '。'}`,
      },
      client
    );

    if (current.status === ORDER_STATUSES.ENTERED) {
      await notifyStageWorkers(
        'cutting',
        {
          orderId,
          severity: 'warning',
          title: '订单已取消',
          message: `${current.order_no} 已撤回，无需继续准备切玻璃。`,
        },
        client
      );
    }
  });

  return await getOrderById(orderId);
}

export async function markOrderEntered(orderId, actorUserId) {
  const current = await requireOrder(orderId);

  if (current.status !== ORDER_STATUSES.RECEIVED) {
    return await getOrderById(orderId);
  }

  const timestamp = nowIso();

  await withTransaction(async (client) => {
    await updateOrderStatus(
      orderId,
      ORDER_STATUSES.ENTERED,
      {
        enteredAt: timestamp,
        lastProductionActivityAt: timestamp,
      },
      client
    );

    await createEvent(orderId, 'order_entered', '订单已录入系统，推送到切玻璃工位。', actorUserId, {
      status: ORDER_STATUSES.ENTERED,
    }, client);

    await notifyStageWorkers(
      'cutting',
      {
        orderId,
        severity: 'info',
        title: '新订单待切玻璃',
        message: `${current.order_no} 已录入系统，请开始第一道工序。`,
      },
      client
    );
  });

  return await getOrderById(orderId);
}

export async function startStep(orderId, stepKey, actorUserId) {
  const order = await requireOrder(orderId);
  if (order.status === ORDER_STATUSES.CANCELLED) {
    throw new Error('订单已取消，不能继续生产。');
  }
  if (order.status === ORDER_STATUSES.PICKED_UP) {
    throw new Error('订单已完成提货，不能继续生产。');
  }

  const step = await requireStep(orderId, stepKey);
  await ensurePreviousStepsCompleted(orderId, step.step_index);

  if (step.status === STEP_STATUSES.COMPLETED) {
    return await getOrderById(orderId);
  }

  const timestamp = nowIso();

  await withTransaction(async (client) => {
    await execute(
      `
        UPDATE order_steps
        SET
          status = $1,
          started_at = COALESCE(started_at, $2),
          updated_at = $3,
          rework_unread = CASE WHEN step_key = 'cutting' THEN 0 ELSE rework_unread END
        WHERE order_id = $4 AND step_key = $5
      `,
      [STEP_STATUSES.IN_PROGRESS, timestamp, timestamp, orderId, stepKey],
      client
    );

    await updateOrderStatus(
      orderId,
      ORDER_STATUSES.IN_PRODUCTION,
      {
        enteredAt: order.entered_at ?? timestamp,
        lastProductionActivityAt: timestamp,
      },
      client
    );

    await createEvent(orderId, 'step_started', `${step.step_label} 已开始。`, actorUserId, {
      stepKey,
      status: STEP_STATUSES.IN_PROGRESS,
    }, client);
  });

  return await getOrderById(orderId);
}

export async function completeStep(orderId, stepKey, actorUserId) {
  const order = await requireOrder(orderId);
  if (order.status === ORDER_STATUSES.CANCELLED) {
    throw new Error('订单已取消，不能继续生产。');
  }
  if (order.status === ORDER_STATUSES.PICKED_UP) {
    throw new Error('订单已完成提货，不能继续生产。');
  }

  const step = await requireStep(orderId, stepKey);
  await ensurePreviousStepsCompleted(orderId, step.step_index);

  const timestamp = nowIso();

  await withTransaction(async (client) => {
    await execute(
      `
        UPDATE order_steps
        SET
          status = $1,
          started_at = COALESCE(started_at, $2),
          completed_at = $3,
          updated_at = $4,
          rework_unread = 0
        WHERE order_id = $5 AND step_key = $6
      `,
      [STEP_STATUSES.COMPLETED, timestamp, timestamp, timestamp, orderId, stepKey],
      client
    );

    await updateOrderStatus(
      orderId,
      ORDER_STATUSES.IN_PRODUCTION,
      {
        enteredAt: order.entered_at ?? timestamp,
        lastProductionActivityAt: timestamp,
        reworkOpen: stepKey === 'cutting' ? 0 : order.rework_open,
      },
      client
    );

    await createEvent(orderId, 'step_completed', `${step.step_label} 已完成。`, actorUserId, {
      stepKey,
      status: STEP_STATUSES.COMPLETED,
    }, client);

    await recalculateCompletionState(orderId, actorUserId, client);
  });

  return await getOrderById(orderId);
}

export async function reportRework(orderId, stepKey, pieceNumbers, note, actorUserId) {
  const normalizedPieceNumbers = normalizePieceNumbers(pieceNumbers);
  if (!normalizedPieceNumbers.length) {
    throw new Error('请至少选择一片需要返工的玻璃。');
  }

  const order = await requireOrder(orderId);
  if (order.status === ORDER_STATUSES.CANCELLED) {
    throw new Error('订单已取消，不能再发起返工。');
  }
  if (stepKey === 'cutting') {
    throw new Error('切玻璃工位可直接重做，不需要回推返工。');
  }
  const step = await requireStep(orderId, stepKey);
  const cuttingStep = await requireStep(orderId, 'cutting');
  const orderQuantity = Number(order.quantity ?? 0);
  if (normalizedPieceNumbers.some((pieceNumber) => pieceNumber > orderQuantity)) {
    throw new Error(`返工片号超出范围，当前订单只有 ${orderQuantity} 片。`);
  }

  const openPieceNumbers = new Set(
    (await serializeReworkRequests(orderId, { limit: 100 }))
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

  await withTransaction(async (client) => {
    await execute(
      `
        UPDATE order_steps
        SET
          rework_count = rework_count + $1,
          rework_note = $2,
          updated_at = $3
        WHERE order_id = $4 AND step_key = $5
      `,
      [pieceCount, note ?? '', timestamp, orderId, stepKey],
      client
    );

    await execute(
      `
        UPDATE order_steps
        SET
          rework_count = rework_count + $1,
          rework_note = $2,
          rework_unread = 1,
          status = $3,
          completed_at = NULL,
          updated_at = $4
        WHERE order_id = $5 AND step_key = 'cutting'
      `,
      [
        pieceCount,
        `${step.step_label} 回推返工：${pieceSummary}${note ? `；${note}` : ''}`,
        cuttingStep.status === STEP_STATUSES.IN_PROGRESS
          ? STEP_STATUSES.IN_PROGRESS
          : STEP_STATUSES.PENDING,
        timestamp,
        orderId,
      ],
      client
    );

    await execute(
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
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
      `,
      [
        randomUUID(),
        orderId,
        stepKey,
        step.step_label,
        JSON.stringify(normalizedPieceNumbers),
        pieceCount,
        note ?? '',
        actorUserId,
        timestamp,
      ],
      client
    );

    await updateOrderStatus(
      orderId,
      ORDER_STATUSES.IN_PRODUCTION,
      {
        enteredAt: order.entered_at ?? timestamp,
        lastProductionActivityAt: timestamp,
        reworkOpen: 1,
      },
      client
    );

    await createEvent(
      orderId,
      'step_rework',
      `${step.step_label} 标记返工 ${pieceSummary}，已回推切玻璃工位。`,
      actorUserId,
      { stepKey, pieceNumbers: normalizedPieceNumbers, note },
      client
    );

    await notifyStageWorkers(
      'cutting',
      {
        orderId,
        severity: 'warning',
        title: '返工高亮',
        message: `${order.order_no} 在 ${step.step_label} 标记返工：${pieceSummary}${
          note ? `。说明：${note}` : '。'
        }`,
      },
      client
    );

    await notifySupervisors(
      {
        orderId,
        severity: 'warning',
        title: '订单返工',
        message: `${order.order_no} 在 ${step.step_label} 标记返工：${pieceSummary}。`,
      },
      client
    );
  });

  return await getOrderById(orderId);
}

export async function acknowledgeRework(orderId, actorUserId) {
  const openRequests = await queryOne(
    `
      SELECT COUNT(*) AS count
      FROM rework_requests
      WHERE order_id = $1 AND is_acknowledged = 0
    `,
    [orderId]
  );

  if (Number(openRequests?.count ?? 0) === 0) {
    return await getOrderById(orderId);
  }

  const timestamp = nowIso();

  await withTransaction(async (client) => {
    await execute(
      `
        UPDATE order_steps
        SET
          rework_unread = 0,
          updated_at = $1
        WHERE order_id = $2 AND step_key = 'cutting'
      `,
      [timestamp, orderId],
      client
    );

    await execute(
      `
        UPDATE rework_requests
        SET
          is_acknowledged = 1,
          acknowledged_at = $1,
          acknowledged_by = $2
        WHERE order_id = $3 AND is_acknowledged = 0
      `,
      [timestamp, actorUserId, orderId],
      client
    );

    await execute('UPDATE orders SET rework_open = 0 WHERE id = $1', [orderId], client);

    await createEvent(orderId, 'rework_acknowledged', '切玻璃工位已确认返工提醒。', actorUserId, {}, client);
  });

  return await getOrderById(orderId);
}

export async function approvePickup(orderId, actorUserId) {
  const order = await requireOrder(orderId);
  if (order.status === ORDER_STATUSES.CANCELLED) {
    throw new Error('订单已取消，不能批准 pickup。');
  }
  if (order.status !== ORDER_STATUSES.COMPLETED) {
    throw new Error('只有已完成订单才能批准 pickup。');
  }

  const timestamp = nowIso();

  await withTransaction(async (client) => {
    await updateOrderStatus(
      orderId,
      ORDER_STATUSES.READY_FOR_PICKUP,
      {
        readyForPickupAt: timestamp,
        pickupApprovedAt: timestamp,
        pickupApprovedBy: actorUserId,
        lastProductionActivityAt: order.last_production_activity_at,
      },
      client
    );

    await createEvent(orderId, 'pickup_approved', '主管已批准取货，可以调出签字界面。', actorUserId, {
      status: ORDER_STATUSES.READY_FOR_PICKUP,
    }, client);

    await notifyOffice(
      {
        orderId,
        severity: 'success',
        title: '可取货',
        message: `${order.order_no} 已批准 pickup，可请客户现场签字。`,
      },
      client
    );

    await notifyStageWorkers(
      'finishing',
      {
        orderId,
        severity: 'info',
        title: '准备出货',
        message: `${order.order_no} 已批准 pickup，可安排仓库协助取货。`,
      },
      client
    );
  });

  return await getOrderById(orderId);
}

export async function recordPickupSignature(orderId, payload, actorUserId) {
  const order = await requireOrder(orderId);
  if (order.status === ORDER_STATUSES.CANCELLED) {
    throw new Error('订单已取消，不能签字取货。');
  }
  if (order.status !== ORDER_STATUSES.READY_FOR_PICKUP) {
    throw new Error('订单尚未批准 pickup，不能签字。');
  }

  const timestamp = nowIso();

  await withTransaction(async (client) => {
    await updateOrderStatus(
      orderId,
      ORDER_STATUSES.PICKED_UP,
      {
        pickedUpAt: timestamp,
        pickupSignerName: payload.signerName,
        pickupSignaturePath: payload.signaturePath,
        lastProductionActivityAt: order.last_production_activity_at,
      },
      client
    );

    await createEvent(orderId, 'pickup_signed', '客户已完成电子签字并提货。', actorUserId, {
      signerName: payload.signerName,
      status: ORDER_STATUSES.PICKED_UP,
    }, client);

    await notifySupervisors(
      {
        orderId,
        severity: 'success',
        title: '已完成取货',
        message: `${order.order_no} 已由 ${payload.signerName} 完成签字提货。`,
      },
      client
    );
  });

  return await getOrderById(orderId);
}

export async function listNotificationsForUser(userId) {
  const rows = await queryRows(
    `
      SELECT
        notifications.*,
        orders.order_no
      FROM notifications
      LEFT JOIN orders ON orders.id = notifications.order_id
      WHERE notifications.user_id = $1
      ORDER BY notifications.is_read ASC, notifications.created_at DESC
      LIMIT 100
    `,
    [userId]
  );

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

export async function markNotificationsRead(userId) {
  await execute(
    `
      UPDATE notifications
      SET is_read = 1
      WHERE user_id = $1
    `,
    [userId]
  );

  return await listNotificationsForUser(userId);
}

export const DATABASE_PROVIDER = 'postgres';

export function getPersistenceInfo() {
  return {
    provider: DATABASE_PROVIDER,
    databasePath: getPostgresConnectionInfo(POSTGRES_DATABASE_URL)?.summary ?? null,
  };
}

export { serializeUser };