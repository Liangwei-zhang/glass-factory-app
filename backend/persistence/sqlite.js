import { getDatabasePath } from '../db.js';

export {
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
} from '../db.js';

export const DATABASE_PROVIDER = 'sqlite';

export function getPersistenceInfo() {
  return {
    provider: DATABASE_PROVIDER,
    databasePath: getDatabasePath(),
  };
}