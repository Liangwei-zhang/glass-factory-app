import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';

import cors from 'cors';
import express from 'express';
import multer from 'multer';

import { authenticateUser, issueToken, requireAuth } from './auth.js';
import {
  DRAWINGS_DIR,
  PORT,
  PUBLIC_DIR,
  SIGNATURES_DIR,
  UPLOADS_DIR,
} from './config.js';
import {
  FILE_UPLOAD_LIMIT_BYTES,
  PRIORITIES,
  ROLES,
} from './constants.js';
import {
  getPersistenceHealth,
  initDatabase,
} from './persistence/index.js';
import {
  createCustomerProfile,
  listCustomerDirectory,
  updateCustomerProfile,
} from './domains/customers.js';
import {
  listUserNotifications,
  markUserNotificationsRead,
} from './domains/notifications.js';
import {
  approveOrderPickupAndNotify,
  assertOrderExportAllowed,
  createSalesOrder,
  getOrderDetail,
  listOrderBoard,
  markSalesOrderEntered,
  recordOrderPickupSignature,
  sendPickupReminder,
  updateSalesOrder,
  cancelSalesOrder,
} from './domains/orders.js';
import {
  handleProductionAction,
} from './domains/production.js';
import {
  buildClientOptions,
  createManageableGlassType,
  getNotificationTemplateConfig,
  listManageableGlassTypes,
  listRecentEmailLogs,
  updateManageableGlassType,
  updateNotificationTemplateConfig,
} from './domains/settings.js';
import {
  getWorkspaceBootstrap,
  getWorkspaceSummary,
} from './domains/workspace.js';
import { sendOrderPdf } from './pdf.js';

fs.mkdirSync(DRAWINGS_DIR, { recursive: true });
fs.mkdirSync(SIGNATURES_DIR, { recursive: true });

await initDatabase();

const app = express();

const drawingStorage = multer.diskStorage({
  destination: (_req, _file, callback) => callback(null, DRAWINGS_DIR),
  filename: (_req, file, callback) => {
    const extension = path.extname(file.originalname).toLowerCase() || '.bin';
    callback(null, `${Date.now()}-${randomUUID()}${extension}`);
  },
});

const drawingUpload = multer({
  storage: drawingStorage,
  limits: { fileSize: FILE_UPLOAD_LIMIT_BYTES },
  fileFilter: (_req, file, callback) => {
    const allowedMimeTypes = [
      'application/pdf',
      'image/png',
      'image/jpeg',
      'image/webp',
    ];

    if (allowedMimeTypes.includes(file.mimetype)) {
      callback(null, true);
      return;
    }

    callback(new Error('图纸仅支持 PDF / PNG / JPG / WEBP。'));
  },
});

app.use(cors());
app.use(express.json({ limit: '12mb' }));
app.use(express.urlencoded({ extended: true }));
app.use('/uploads', express.static(UPLOADS_DIR));
app.use(express.static(PUBLIC_DIR));

function parseQuantity(value, fieldLabel = '数量') {
  const quantity = Number.parseInt(value, 10);

  if (!Number.isInteger(quantity) || quantity <= 0) {
    throw new Error(`${fieldLabel}必须是大于 0 的整数。`);
  }

  return quantity;
}

function parsePieceNumbers(value) {
  const rawValues = Array.isArray(value)
    ? value
    : typeof value === 'string'
      ? value.split(/[,\s]+/)
      : [];

  const pieceNumbers = [...new Set(
    rawValues
      .map((item) => Number.parseInt(item, 10))
      .filter((item) => Number.isInteger(item) && item > 0)
  )].sort((left, right) => left - right);

  if (!pieceNumbers.length) {
    throw new Error('请至少选择一片需要返工的玻璃。');
  }

  return pieceNumbers;
}

function parseOrderInput(body, file, { partial = false } = {}) {
  const payload = {};

  if (!partial || body.customerId !== undefined) {
    payload.customerId = String(body.customerId || '').trim();
  }

  if (!partial || body.glassType !== undefined) {
    payload.glassType = String(body.glassType || '').trim();
  }

  if (!partial || body.thickness !== undefined) {
    payload.thickness = String(body.thickness || '').trim();
  }

  if (!partial || body.quantity !== undefined) {
    payload.quantity = parseQuantity(body.quantity);
  }

  if (body.estimatedCompletionDate !== undefined) {
    payload.estimatedCompletionDate = body.estimatedCompletionDate || null;
  }

  if (body.specialInstructions !== undefined) {
    payload.specialInstructions = String(body.specialInstructions || '').trim();
  }

  if (body.priority !== undefined) {
    payload.priority = String(body.priority || PRIORITIES.NORMAL).trim();
  }

  if (file) {
    payload.drawingPath = `/uploads/drawings/${path.basename(file.path)}`;
    payload.drawingName = file.originalname;
  }

  if (!partial) {
    if (!payload.customerId) {
      throw new Error('请选择客户。');
    }
    if (!payload.glassType) {
      throw new Error('请选择玻璃类型。');
    }
    if (!payload.thickness) {
      throw new Error('请选择厚度。');
    }
  }

  return payload;
}

function parseCustomerInput(body) {
  const companyName = String(body.companyName || '').trim();

  if (!companyName) {
    throw new Error('公司名称不能为空。');
  }

  return {
    companyName,
    contactName: String(body.contactName || '').trim(),
    phone: String(body.phone || '').trim(),
    email: String(body.email || '').trim(),
    notes: String(body.notes || '').trim(),
  };
}

function getSignaturePathFromDataUrl(dataUrl, orderId) {
  const match = String(dataUrl || '').match(/^data:image\/(png|jpeg|jpg|webp);base64,(.+)$/i);

  if (!match) {
    throw new Error('签名格式无效，请重新签字。');
  }

  const extension = match[1] === 'jpeg' ? 'jpg' : match[1].toLowerCase();
  const buffer = Buffer.from(match[2], 'base64');
  const fileName = `${orderId}-${Date.now()}.${extension}`;
  const filePath = path.join(SIGNATURES_DIR, fileName);

  fs.writeFileSync(filePath, buffer);
  return `/uploads/signatures/${fileName}`;
}

async function serializeOptions() {
  return await buildClientOptions();
}

function asyncHandler(handler) {
  return (req, res, next) => {
    Promise.resolve(handler(req, res, next)).catch(next);
  };
}

app.get('/api/health', async (_req, res, next) => {
  try {
    const persistence = await getPersistenceHealth();

    res.json({
      status: 'ok',
      databasePath: persistence.databasePath,
      databaseProvider: persistence.provider,
      targetDatabaseProvider: persistence.targetProvider,
      databaseRuntimeReady: persistence.runtimeReady,
      postgres: persistence.postgres,
      uptimeSeconds: Math.round(process.uptime()),
      now: new Date().toISOString(),
    });
  } catch (error) {
    next(error);
  }
});

app.post('/api/auth/login', asyncHandler(async (req, res) => {
  const email = String(req.body.email || '').trim();
  const password = String(req.body.password || '');

  if (!email || !password) {
    return res.status(400).json({ error: '请输入邮箱和密码。' });
  }

  const user = await authenticateUser(email, password);
  if (!user) {
    return res.status(401).json({ error: '账号或密码错误。' });
  }

  return res.json({
    token: issueToken(user),
    user,
  });
}));

app.get('/api/me', requireAuth(), (req, res) => {
  res.json({ user: req.user });
});

app.get('/api/bootstrap', requireAuth(), asyncHandler(async (req, res) => {
  res.json({
    user: req.user,
    options: await serializeOptions(),
    data: await getWorkspaceBootstrap(req.user),
  });
}));

app.get('/api/customers', requireAuth(), asyncHandler(async (_req, res) => {
  res.json({ customers: await listCustomerDirectory() });
}));

app.get(
  '/api/settings/glass-types',
  requireAuth([ROLES.OFFICE, ROLES.SUPERVISOR]),
  asyncHandler(async (_req, res) => {
    res.json({ glassTypes: await listManageableGlassTypes() });
  })
);

app.post(
  '/api/settings/glass-types',
  requireAuth([ROLES.OFFICE, ROLES.SUPERVISOR]),
  asyncHandler(async (req, res) => {
    res.status(201).json({
      glassType: await createManageableGlassType(req.body.name, req.user.id),
      glassTypes: await listManageableGlassTypes(),
    });
  })
);

app.patch(
  '/api/settings/glass-types/:glassTypeId',
  requireAuth([ROLES.OFFICE, ROLES.SUPERVISOR]),
  asyncHandler(async (req, res) => {
    res.json({
      glassType: await updateManageableGlassType(
        req.params.glassTypeId,
        {
          name: req.body.name,
          isActive: req.body.isActive,
        },
        req.user.id
      ),
      glassTypes: await listManageableGlassTypes(),
    });
  })
);

app.get(
  '/api/settings/notification-templates/:templateKey',
  requireAuth([ROLES.OFFICE, ROLES.SUPERVISOR]),
  asyncHandler(async (req, res) => {
    res.json({ template: await getNotificationTemplateConfig(req.params.templateKey) });
  })
);

app.put(
  '/api/settings/notification-templates/:templateKey',
  requireAuth([ROLES.OFFICE, ROLES.SUPERVISOR]),
  asyncHandler(async (req, res) => {
    res.json({
      template: await updateNotificationTemplateConfig(
        req.params.templateKey,
        {
          subjectTemplate: String(req.body.subjectTemplate || ''),
          bodyTemplate: String(req.body.bodyTemplate || ''),
        },
        req.user.id
      ),
    });
  })
);

app.get(
  '/api/email-logs',
  requireAuth([ROLES.OFFICE, ROLES.SUPERVISOR]),
  asyncHandler(async (req, res) => {
    res.json({ logs: await listRecentEmailLogs(req.query.limit) });
  })
);

app.post(
  '/api/customers',
  requireAuth([ROLES.OFFICE, ROLES.SUPERVISOR]),
  asyncHandler(async (req, res) => {
    const customer = await createCustomerProfile(parseCustomerInput(req.body));
    res.status(201).json({ customer, customers: await listCustomerDirectory() });
  })
);

app.patch(
  '/api/customers/:customerId',
  requireAuth([ROLES.OFFICE, ROLES.SUPERVISOR]),
  asyncHandler(async (req, res) => {
    const customer = await updateCustomerProfile(
      req.params.customerId,
      parseCustomerInput(req.body)
    );
    res.json({ customer, customers: await listCustomerDirectory() });
  })
);

app.get('/api/orders', requireAuth(), asyncHandler(async (req, res) => {
  res.json({
    orders: await listOrderBoard({
      query: req.query.query,
      status: req.query.status,
      priority: req.query.priority,
    }),
  });
}));

app.get('/api/orders/:orderId', requireAuth(), asyncHandler(async (req, res) => {
  const order = await getOrderDetail(req.params.orderId);
  if (!order) {
    return res.status(404).json({ error: '订单不存在。' });
  }

  return res.json({ order });
}));

app.get('/api/orders/:orderId/export', requireAuth(), asyncHandler(async (req, res) => {
  const order = await getOrderDetail(req.params.orderId);
  if (!order) {
    return res.status(404).json({ error: '订单不存在。' });
  }

  const documentType = assertOrderExportAllowed(order, req.query.document);

  sendOrderPdf(res, order, documentType);
  return undefined;
}));

app.post(
  '/api/orders',
  requireAuth([ROLES.OFFICE, ROLES.SUPERVISOR]),
  drawingUpload.single('drawing'),
  asyncHandler(async (req, res) => {
    const input = parseOrderInput(req.body, req.file, { partial: false });
    const order = await createSalesOrder(input, req.user.id);
    res.status(201).json({ order });
  })
);

app.put(
  '/api/orders/:orderId',
  requireAuth([ROLES.OFFICE, ROLES.SUPERVISOR]),
  drawingUpload.single('drawing'),
  asyncHandler(async (req, res) => {
    const input = parseOrderInput(req.body, req.file, { partial: true });
    const order = await updateSalesOrder(req.params.orderId, input, req.user.id);
    res.json({ order });
  })
);

app.post(
  '/api/orders/:orderId/cancel',
  requireAuth([ROLES.OFFICE, ROLES.SUPERVISOR]),
  asyncHandler(async (req, res) => {
    const reason = String(req.body.reason || '').trim();
    res.json({ order: await cancelSalesOrder(req.params.orderId, reason, req.user.id) });
  })
);

app.post(
  '/api/orders/:orderId/entered',
  requireAuth([ROLES.OFFICE, ROLES.SUPERVISOR]),
  asyncHandler(async (req, res) => {
    res.json({ order: await markSalesOrderEntered(req.params.orderId, req.user.id) });
  })
);

app.post(
  '/api/orders/:orderId/steps/:stepKey',
  requireAuth([ROLES.WORKER, ROLES.SUPERVISOR]),
  asyncHandler(async (req, res) => {
    const { stepKey, orderId } = req.params;
    const action = String(req.body.action || '').trim();

    const order = await handleProductionAction({
      action,
      actorUser: req.user,
      note: String(req.body.note || '').trim(),
      orderId,
      pieceNumbers:
        action === 'rework'
          ? parsePieceNumbers(req.body.pieceNumbers ?? req.body.pieces)
          : undefined,
      stepKey,
    });

    return res.json({ order });
  })
);

app.post(
  '/api/orders/:orderId/pickup/approve',
  requireAuth([ROLES.SUPERVISOR]),
  async (req, res, next) => {
    try {
      res.json(await approveOrderPickupAndNotify(req.params.orderId, req.user.id));
    } catch (error) {
      next(error);
    }
  }
);

app.post(
  '/api/orders/:orderId/pickup/send-email',
  requireAuth([ROLES.OFFICE, ROLES.SUPERVISOR]),
  async (req, res, next) => {
    try {
      return res.json(await sendPickupReminder(req.params.orderId, req.user.id));
    } catch (error) {
      return next(error);
    }
  }
);

app.post(
  '/api/orders/:orderId/pickup/signature',
  requireAuth([ROLES.OFFICE, ROLES.SUPERVISOR]),
  asyncHandler(async (req, res) => {
    const signerName = String(req.body.signerName || '').trim();
    const signatureDataUrl = String(req.body.signatureDataUrl || '');

    if (!signerName) {
      return res.status(400).json({ error: '请填写取货人姓名。' });
    }

    const signaturePath = getSignaturePathFromDataUrl(signatureDataUrl, req.params.orderId);
    const order = await recordOrderPickupSignature(
      req.params.orderId,
      {
        signerName,
        signaturePath,
      },
      req.user.id
    );

    return res.json({ order });
  })
);

app.get('/api/notifications', requireAuth(), asyncHandler(async (req, res) => {
  res.json({ notifications: await listUserNotifications(req.user.id) });
}));

app.post('/api/notifications/read', requireAuth(), asyncHandler(async (req, res) => {
  res.json({ notifications: await markUserNotificationsRead(req.user.id) });
}));

app.get('/api/dashboard/summary', requireAuth(), asyncHandler(async (req, res) => {
  res.json({ summary: await getWorkspaceSummary(req.user) });
}));

app.get('*', (req, res, next) => {
  if (req.path.startsWith('/api/')) {
    return next();
  }

  return res.sendFile(path.join(PUBLIC_DIR, 'index.html'));
});

app.use((error, _req, res, _next) => {
  const statusCode = error.statusCode || error.status || 400;
  console.error(error);
  res.status(statusCode).json({
    error: error.message || '请求处理失败。',
  });
});

app.listen(PORT, () => {
  console.log(`Glass Factory app listening on http://localhost:${PORT}`);
});