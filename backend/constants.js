export const ROLES = Object.freeze({
  OFFICE: 'office',
  WORKER: 'worker',
  SUPERVISOR: 'supervisor',
});

export const ORDER_STATUSES = Object.freeze({
  RECEIVED: 'received',
  ENTERED: 'entered',
  IN_PRODUCTION: 'in_production',
  COMPLETED: 'completed',
  READY_FOR_PICKUP: 'ready_for_pickup',
  PICKED_UP: 'picked_up',
  CANCELLED: 'cancelled',
});

export const STATUS_LABELS = Object.freeze({
  [ORDER_STATUSES.RECEIVED]: '已接单',
  [ORDER_STATUSES.ENTERED]: '已录入系统',
  [ORDER_STATUSES.IN_PRODUCTION]: '生产中',
  [ORDER_STATUSES.COMPLETED]: '已完成',
  [ORDER_STATUSES.READY_FOR_PICKUP]: '可取货',
  [ORDER_STATUSES.PICKED_UP]: '已取货',
  [ORDER_STATUSES.CANCELLED]: '已取消',
});

export const PRIORITIES = Object.freeze({
  NORMAL: 'normal',
  RUSH: 'rush',
  REWORK: 'rework',
  HOLD: 'hold',
});

export const PRIORITY_LABELS = Object.freeze({
  [PRIORITIES.NORMAL]: '普通',
  [PRIORITIES.RUSH]: '加急',
  [PRIORITIES.REWORK]: '返工',
  [PRIORITIES.HOLD]: 'Hold',
});

export const STEP_STATUSES = Object.freeze({
  PENDING: 'pending',
  IN_PROGRESS: 'in_progress',
  COMPLETED: 'completed',
});

export const STEP_STATUS_LABELS = Object.freeze({
  [STEP_STATUSES.PENDING]: '待处理',
  [STEP_STATUSES.IN_PROGRESS]: '进行中',
  [STEP_STATUSES.COMPLETED]: '已完成',
});

export const PRODUCTION_STEPS = Object.freeze([
  {
    key: 'cutting',
    label: '切玻璃',
    workerLabel: '切玻璃工人',
  },
  {
    key: 'edging',
    label: '开切口',
    workerLabel: '开切口工人',
  },
  {
    key: 'tempering',
    label: '钢化',
    workerLabel: '钢化工人',
  },
  {
    key: 'finishing',
    label: '完成钢化',
    workerLabel: '完成钢化处工人',
  },
]);

export const STAGE_LABELS = Object.freeze(
  PRODUCTION_STEPS.reduce((labels, step) => {
    labels[step.key] = step.workerLabel;
    return labels;
  }, {})
);

export const PRODUCTION_STEP_MAP = Object.freeze(
  PRODUCTION_STEPS.reduce((mapping, step) => {
    mapping[step.key] = step;
    return mapping;
  }, {})
);

export const GLASS_TYPES = Object.freeze([
  'Clear',
  'Rain',
  'Pinhead',
  'Grey',
  'Frosted',
  'Low-E',
  'Laminated',
  'Custom',
]);

export const THICKNESS_OPTIONS = Object.freeze([
  '4mm',
  '5mm',
  '6mm',
  '8mm',
  '10mm',
  '12mm',
]);

export const ACTIVE_ORDER_STATUSES = Object.freeze([
  ORDER_STATUSES.RECEIVED,
  ORDER_STATUSES.ENTERED,
  ORDER_STATUSES.IN_PRODUCTION,
  ORDER_STATUSES.COMPLETED,
  ORDER_STATUSES.READY_FOR_PICKUP,
]);

export const FILE_UPLOAD_LIMIT_BYTES = 10 * 1024 * 1024;