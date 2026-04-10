import { DATABASE_PROVIDER as TARGET_DATABASE_PROVIDER } from '../config.js';
import { getPostgresHealth, isPostgresConfigured } from './postgres-client.js';
import * as sqlitePersistence from './sqlite.js';

const activePersistence = sqlitePersistence;

export const DATABASE_PROVIDER = activePersistence.DATABASE_PROVIDER;
export const getPersistenceInfo = activePersistence.getPersistenceInfo;
export { TARGET_DATABASE_PROVIDER };

export function isPersistenceRuntimeReady() {
  return TARGET_DATABASE_PROVIDER === DATABASE_PROVIDER;
}

export async function getPersistenceHealth() {
  const baseInfo = activePersistence.getPersistenceInfo();
  const postgres =
    TARGET_DATABASE_PROVIDER === 'postgres' || isPostgresConfigured()
      ? await getPostgresHealth()
      : {
          configured: false,
          reachable: false,
          latencyMs: null,
          connection: null,
          error: null,
        };

  return {
    ...baseInfo,
    targetProvider: TARGET_DATABASE_PROVIDER,
    runtimeReady: isPersistenceRuntimeReady(),
    postgres,
  };
}

export const {
  acknowledgeRework,
  approvePickup,
  cancelOrder,
  completeStep,
  createCustomer,
  createEmailLog,
  createGlassType,
  createOrder,
  getNotificationTemplate,
  getOrderById,
  getUserByEmail,
  getUserById,
  initDatabase,
  listCustomers,
  listEmailLogs,
  listGlassTypes,
  listNotificationsForUser,
  listOrders,
  markNotificationsRead,
  markOrderEntered,
  recordPickupSignature,
  reportRework,
  startStep,
  updateCustomer,
  updateGlassType,
  updateNotificationTemplate,
  updateOrder,
} = activePersistence;