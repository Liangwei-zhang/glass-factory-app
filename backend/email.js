import nodemailer from 'nodemailer';

import { SMTP_CONFIG } from './config.js';
import { createEmailLog, getNotificationTemplate } from './persistence/index.js';

const READY_FOR_PICKUP_TEMPLATE_KEY = 'ready_for_pickup';

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function formatDate(value, withTime = false) {
  if (!value) {
    return '未设置';
  }

  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: withTime ? '2-digit' : undefined,
    minute: withTime ? '2-digit' : undefined,
  }).format(new Date(value));
}

function renderTemplate(template, variables) {
  return String(template || '').replace(/\{\{\s*([a-zA-Z0-9_]+)\s*\}\}/g, (_match, key) => {
    return variables[key] ?? '';
  });
}

function buildHtmlBody(body) {
  return `
    <div style="font-family: 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif; color: #102a43; line-height: 1.65;">
      ${String(body || '')
        .split(/\n{2,}/)
        .map(
          (paragraph) =>
            `<p style="margin: 0 0 14px;">${escapeHtml(paragraph).replaceAll('\n', '<br />')}</p>`
        )
        .join('')}
    </div>
  `;
}

function createTransport() {
  if (!SMTP_CONFIG.host) {
    return null;
  }

  return nodemailer.createTransport({
    host: SMTP_CONFIG.host,
    port: SMTP_CONFIG.port,
    secure: SMTP_CONFIG.secure,
    auth:
      SMTP_CONFIG.user && SMTP_CONFIG.pass
        ? {
            user: SMTP_CONFIG.user,
            pass: SMTP_CONFIG.pass,
          }
        : undefined,
  });
}

function buildReadyForPickupVariables(order) {
  return {
    customerCompany: order.customer.companyName || '客户',
    customerContact: order.customer.contactName || '客户',
    customerPhone: order.customer.phone || '未填写',
    orderNo: order.orderNo,
    glassType: order.glassType,
    thickness: order.thickness,
    quantity: `${order.quantity}`,
    specialInstructions: order.specialInstructions || '无',
    pickupApprovedAt: formatDate(order.pickupApprovedAt, true),
    estimatedCompletionDate: formatDate(order.estimatedCompletionDate),
    statusLabel: order.statusLabel,
  };
}

export async function deliverReadyForPickupEmail(order, actorUserId) {
  const template = await getNotificationTemplate(READY_FOR_PICKUP_TEMPLATE_KEY);
  const variables = buildReadyForPickupVariables(order);
  const subject = renderTemplate(template.subjectTemplate, variables).trim();
  const body = renderTemplate(template.bodyTemplate, variables).trim();
  const customerEmail = String(order.customer.email || '').trim();

  if (!customerEmail) {
    return await createEmailLog({
      templateKey: READY_FOR_PICKUP_TEMPLATE_KEY,
      orderId: order.id,
      customerEmail: '未填写邮箱',
      subject,
      body,
      status: 'skipped',
      transport: 'none',
      errorMessage: '客户未填写邮箱，未发送提醒。',
      actorUserId,
      createdAt: new Date().toISOString(),
      sentAt: null,
    });
  }

  const transport = createTransport();
  if (!transport) {
    return await createEmailLog({
      templateKey: READY_FOR_PICKUP_TEMPLATE_KEY,
      orderId: order.id,
      customerEmail,
      subject,
      body,
      status: 'preview',
      transport: 'log',
      errorMessage: 'SMTP 未配置，已保存邮件预览。',
      actorUserId,
      createdAt: new Date().toISOString(),
      sentAt: null,
    });
  }

  try {
    const sentAt = new Date().toISOString();
    const info = await transport.sendMail({
      from: SMTP_CONFIG.from || SMTP_CONFIG.user || 'glass-factory@example.local',
      to: customerEmail,
      subject,
      text: body,
      html: buildHtmlBody(body),
    });

    return await createEmailLog({
      templateKey: READY_FOR_PICKUP_TEMPLATE_KEY,
      orderId: order.id,
      customerEmail,
      subject,
      body,
      status: 'sent',
      transport: 'smtp',
      errorMessage: '',
      providerMessageId: info.messageId || '',
      actorUserId,
      createdAt: sentAt,
      sentAt,
    });
  } catch (error) {
    return await createEmailLog({
      templateKey: READY_FOR_PICKUP_TEMPLATE_KEY,
      orderId: order.id,
      customerEmail,
      subject,
      body,
      status: 'failed',
      transport: 'smtp',
      errorMessage: error.message || '邮件发送失败。',
      actorUserId,
      createdAt: new Date().toISOString(),
      sentAt: null,
    });
  }
}