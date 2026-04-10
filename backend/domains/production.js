import { PRODUCTION_STEPS, ROLES } from '../constants.js';
import {
  acknowledgeRework,
  completeStep,
  reportRework,
  startStep,
} from '../persistence/index.js';

const KNOWN_STEP_KEYS = new Set(PRODUCTION_STEPS.map((step) => step.key));

export function assertKnownProductionStep(stepKey) {
  if (!KNOWN_STEP_KEYS.has(stepKey)) {
    throw new Error('未知工序。');
  }
}

export function assertProductionAccess(user, stepKey) {
  assertKnownProductionStep(stepKey);

  if (user.role === ROLES.WORKER && user.stage !== stepKey) {
    throw new Error('工人只能操作自己工位的订单。');
  }
}

export async function handleProductionAction({
  action,
  actorUser,
  note,
  orderId,
  pieceNumbers,
  stepKey,
}) {
  assertProductionAccess(actorUser, stepKey);

  switch (action) {
    case 'start':
      return await startStep(orderId, stepKey, actorUser.id);
    case 'complete':
      return await completeStep(orderId, stepKey, actorUser.id);
    case 'rework':
      return await reportRework(orderId, stepKey, pieceNumbers, note, actorUser.id);
    case 'acknowledge_rework':
      if (stepKey !== 'cutting') {
        throw new Error('只有切玻璃工位可以确认返工提醒。');
      }

      return await acknowledgeRework(orderId, actorUser.id);
    default:
      throw new Error('不支持的工序操作。');
  }
}