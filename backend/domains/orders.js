import { ORDER_STATUSES } from '../constants.js';
import {
  approvePickup,
  cancelOrder,
  createOrder,
  getOrderById,
  markOrderEntered,
  listOrders,
  recordPickupSignature,
  updateOrder,
} from '../persistence/index.js';
import { deliverReadyForPickupEmail } from '../email.js';

const PICKUP_READY_STATUSES = new Set([
  ORDER_STATUSES.READY_FOR_PICKUP,
  ORDER_STATUSES.PICKED_UP,
]);

export async function listOrderBoard(filters = {}) {
  return await listOrders(filters);
}

export async function getOrderDetail(orderId) {
  return await getOrderById(orderId);
}

export async function requireOrderDetail(orderId) {
  const order = await getOrderDetail(orderId);
  if (!order) {
    throw new Error('订单不存在。');
  }

  return order;
}

export async function createSalesOrder(payload, actorUserId) {
  return await createOrder({
    ...payload,
    createdBy: actorUserId,
  });
}

export async function updateSalesOrder(orderId, payload, actorUserId) {
  return await updateOrder(orderId, payload, actorUserId);
}

export async function cancelSalesOrder(orderId, reason, actorUserId) {
  return await cancelOrder(orderId, reason, actorUserId);
}

export async function markSalesOrderEntered(orderId, actorUserId) {
  return await markOrderEntered(orderId, actorUserId);
}

export async function approveOrderPickup(orderId, actorUserId) {
  return await approvePickup(orderId, actorUserId);
}

export async function recordOrderPickupSignature(orderId, payload, actorUserId) {
  return await recordPickupSignature(orderId, payload, actorUserId);
}

export function assertOrderExportAllowed(order, documentType = 'order') {
  const normalizedDocumentType = String(documentType || 'order').trim();

  if (!['order', 'pickup'].includes(normalizedDocumentType)) {
    throw new Error('未知导出类型。');
  }

  if (
    normalizedDocumentType === 'pickup' &&
    !PICKUP_READY_STATUSES.has(order.status)
  ) {
    throw new Error('Pickup PDF 仅适用于已批准或已完成提货的订单。');
  }

  return normalizedDocumentType;
}

export function assertPickupReminderAllowed(order) {
  if (!PICKUP_READY_STATUSES.has(order.status)) {
    throw new Error('只有可取货或已取货订单才能发送取货提醒。');
  }
}

export async function approveOrderPickupAndNotify(orderId, actorUserId) {
  const order = await approveOrderPickup(orderId, actorUserId);
  const emailLog = await deliverReadyForPickupEmail(order, actorUserId);

  return {
    order,
    emailLog,
  };
}

export async function sendPickupReminder(orderId, actorUserId) {
  const order = await requireOrderDetail(orderId);
  assertPickupReminderAllowed(order);

  const emailLog = await deliverReadyForPickupEmail(order, actorUserId);
  return {
    order,
    emailLog,
  };
}