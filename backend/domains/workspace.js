import {
  ACTIVE_ORDER_STATUSES,
  ORDER_STATUSES,
  PRIORITIES,
  ROLES,
  STEP_STATUSES,
} from '../constants.js';
import { listCustomerDirectory } from './customers.js';
import { listUserNotifications } from './notifications.js';
import { listOrderBoard } from './orders.js';

const ACTIVE_STATUS_SET = new Set(ACTIVE_ORDER_STATUSES);

export async function getWorkspaceSummary(user, context = null) {
  const orders = context?.orders ?? (await listOrderBoard());
  const customers = context?.customers ?? (await listCustomerDirectory());
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

export async function getWorkspaceBootstrap(user) {
  const customers = await listCustomerDirectory();
  const orders = await listOrderBoard();
  const notifications = await listUserNotifications(user.id);
  const summary = await getWorkspaceSummary(user, { customers, orders });

  return {
    customers,
    orders,
    notifications,
    summary,
  };
}