import {
  ORDER_STATUSES,
  PRIORITIES,
  PRIORITY_LABELS,
  PRODUCTION_STEPS,
  STATUS_LABELS,
  THICKNESS_OPTIONS,
} from '../constants.js';
import {
  createGlassType,
  getNotificationTemplate,
  listEmailLogs,
  listGlassTypes,
  updateGlassType,
  updateNotificationTemplate,
} from '../persistence/index.js';

export async function buildClientOptions() {
  const glassTypes = await listGlassTypes();

  return {
    glassTypes: glassTypes.map((glassType) => glassType.name),
    thicknessOptions: THICKNESS_OPTIONS,
    priorities: Object.values(PRIORITIES).map((value) => ({
      value,
      label: PRIORITY_LABELS[value],
    })),
    orderStatuses: Object.values(ORDER_STATUSES).map((value) => ({
      value,
      label: STATUS_LABELS[value],
    })),
    productionSteps: PRODUCTION_STEPS,
  };
}

export async function listManageableGlassTypes() {
  return await listGlassTypes({ includeInactive: true });
}

export async function createManageableGlassType(name, actorUserId) {
  return await createGlassType(name, actorUserId);
}

export async function updateManageableGlassType(glassTypeId, payload, actorUserId) {
  return await updateGlassType(glassTypeId, payload, actorUserId);
}

export async function getNotificationTemplateConfig(templateKey) {
  return await getNotificationTemplate(templateKey);
}

export async function updateNotificationTemplateConfig(templateKey, payload, actorUserId) {
  return await updateNotificationTemplate(templateKey, payload, actorUserId);
}

export async function listRecentEmailLogs(limit) {
  return await listEmailLogs(limit);
}