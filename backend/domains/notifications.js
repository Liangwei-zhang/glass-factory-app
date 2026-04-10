import {
  listNotificationsForUser,
  markNotificationsRead,
} from '../persistence/index.js';

export async function listUserNotifications(userId) {
  return await listNotificationsForUser(userId);
}

export async function markUserNotificationsRead(userId) {
  return await markNotificationsRead(userId);
}