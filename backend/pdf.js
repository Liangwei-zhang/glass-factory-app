import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

import PDFDocument from 'pdfkit';
import { fonts } from '@embedpdf/fonts-sc';

import { PRIORITY_LABELS, STATUS_LABELS } from './constants.js';

const require = createRequire(import.meta.url);
const FONT_PACKAGE_DIR = path.resolve(require.resolve('@embedpdf/fonts-sc'), '..', '..');
const FONT_REGULAR_PATH = path.join(
  FONT_PACKAGE_DIR,
  'fonts',
  fonts.find((font) => font.weight === 400)?.file || 'NotoSansHans-Regular.otf'
);
const FONT_BOLD_PATH = path.join(
  FONT_PACKAGE_DIR,
  'fonts',
  fonts.find((font) => font.weight === 700)?.file || 'NotoSansHans-Bold.otf'
);

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ROOT_DIR = path.resolve(__dirname, '..');
const UPLOADS_DIR = path.join(ROOT_DIR, 'uploads');

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

function sanitizeFileName(value) {
  return (
    String(value ?? 'export')
      .replace(/[^a-zA-Z0-9._-]+/g, '-')
      .replace(/-+/g, '-')
      .replace(/^-|-$/g, '') || 'export'
  );
}

function ensurePageSpace(doc, minimumHeight = 80) {
  const pageBottom = doc.page.height - doc.page.margins.bottom;
  if (doc.y + minimumHeight > pageBottom) {
    doc.addPage();
  }
}

function drawSectionTitle(doc, title, eyebrow = '') {
  ensurePageSpace(doc, 54);

  if (eyebrow) {
    doc.font('regular').fontSize(9).fillColor('#6B7280').text(eyebrow.toUpperCase());
  }

  doc.font('bold').fontSize(14).fillColor('#102A43').text(title);
  doc.moveDown(0.35);
}

function drawHero(doc, order, title, subtitle) {
  const x = doc.page.margins.left;
  const y = doc.y;
  const width = doc.page.width - doc.page.margins.left - doc.page.margins.right;
  const height = 86;

  doc.roundedRect(x, y, width, height, 18).fillAndStroke('#F3F7F8', '#D9E2EC');
  doc.font('bold').fontSize(21).fillColor('#102A43').text(title, x + 18, y + 16);
  doc.font('regular').fontSize(10).fillColor('#486581').text(subtitle, x + 18, y + 44, {
    width: width - 36,
  });
  doc.font('bold').fontSize(15).fillColor('#0F766E').text(order.orderNo, x + 18, y + 60);
  doc.y = y + height + 16;
}

function drawInfoCards(doc, items, columns = 2) {
  const gap = 12;
  const cardHeight = 60;
  const availableWidth = doc.page.width - doc.page.margins.left - doc.page.margins.right;
  const cardWidth = (availableWidth - gap * (columns - 1)) / columns;
  const rows = Math.ceil(items.length / columns);
  const blockHeight = rows * cardHeight + Math.max(0, rows - 1) * gap;
  const startX = doc.page.margins.left;
  const startY = doc.y;

  ensurePageSpace(doc, blockHeight + 8);

  items.forEach((item, index) => {
    const row = Math.floor(index / columns);
    const column = index % columns;
    const x = startX + column * (cardWidth + gap);
    const y = startY + row * (cardHeight + gap);

    doc.roundedRect(x, y, cardWidth, cardHeight, 14).fillAndStroke('#FFFFFF', '#D9E2EC');
    doc.font('regular').fontSize(8).fillColor('#6B7280').text(item.label, x + 12, y + 10, {
      width: cardWidth - 24,
    });
    doc.font('bold').fontSize(12).fillColor('#102A43').text(item.value, x + 12, y + 28, {
      width: cardWidth - 24,
      height: 20,
    });
  });

  doc.y = startY + blockHeight + 12;
}

function drawTextPanel(doc, title, body) {
  const x = doc.page.margins.left;
  const width = doc.page.width - doc.page.margins.left - doc.page.margins.right;
  const content = body || '无';
  const textHeight = doc.heightOfString(content, {
    width: width - 24,
    align: 'left',
  });
  const panelHeight = Math.max(74, textHeight + 38);
  const y = doc.y;

  ensurePageSpace(doc, panelHeight + 8);

  doc.roundedRect(x, y, width, panelHeight, 16).fillAndStroke('#FFFFFF', '#D9E2EC');
  doc.font('bold').fontSize(11).fillColor('#102A43').text(title, x + 12, y + 12);
  doc.font('regular').fontSize(10).fillColor('#334E68').text(content, x + 12, y + 32, {
    width: width - 24,
    align: 'left',
  });
  doc.y = y + panelHeight + 12;
}

function drawNarrativeCards(doc, items) {
  const x = doc.page.margins.left;
  const width = doc.page.width - doc.page.margins.left - doc.page.margins.right;

  for (const item of items) {
    const subtitle = item.subtitle || '';
    const body = item.body || '无';
    const subtitleHeight = subtitle
      ? doc.heightOfString(subtitle, { width: width - 24, align: 'left' })
      : 0;
    const bodyHeight = doc.heightOfString(body, { width: width - 24, align: 'left' });
    const cardHeight = Math.max(78, 30 + subtitleHeight + bodyHeight);
    const y = doc.y;

    ensurePageSpace(doc, cardHeight + 8);

    doc.roundedRect(x, y, width, cardHeight, 16).fillAndStroke('#FFFFFF', '#D9E2EC');
    doc.font('bold').fontSize(11).fillColor('#102A43').text(item.title, x + 12, y + 12);
    if (subtitle) {
      doc.font('regular').fontSize(9).fillColor('#6B7280').text(subtitle, x + 12, y + 30, {
        width: width - 24,
        align: 'left',
      });
    }
    doc.font('regular').fontSize(10).fillColor('#334E68').text(body, x + 12, y + 48, {
      width: width - 24,
      align: 'left',
    });
    doc.y = y + cardHeight + 10;
  }
}

function resolveUploadPath(publicPath) {
  if (!publicPath || typeof publicPath !== 'string' || !publicPath.startsWith('/uploads/')) {
    return null;
  }

  const resolvedPath = path.resolve(ROOT_DIR, `.${publicPath}`);
  if (!resolvedPath.startsWith(`${UPLOADS_DIR}${path.sep}`) && resolvedPath !== UPLOADS_DIR) {
    return null;
  }

  return fs.existsSync(resolvedPath) ? resolvedPath : null;
}

function drawSteps(doc, order) {
  drawSectionTitle(doc, '工序进度', 'Production');

  const items = order.steps.map((step) => {
    const reworkLine = step.reworkPieceSummary
      ? `\n返工片号 ${step.reworkPieceSummary}`
      : step.reworkCount
        ? `\n返工 ${step.reworkCount} 片`
        : '';
    return {
      title: `${step.label} · ${step.statusLabel}`,
      subtitle: `开始 ${formatDate(step.startedAt, true)} · 完成 ${formatDate(step.completedAt, true)}`,
      body: step.reworkNote ? `${step.reworkNote}${reworkLine}` : `当前状态：${step.statusLabel}${reworkLine}`,
    };
  });

  drawNarrativeCards(doc, items);
}

function drawVersionHistory(doc, versions) {
  if (!versions?.length) {
    return;
  }

  drawSectionTitle(doc, '订单版本记录', 'Version History');
  drawNarrativeCards(
    doc,
    versions.slice(0, 6).map((version) => ({
      title: `V${version.versionNumber} · ${version.eventLabel}`,
      subtitle: `${version.actorName} · ${formatDate(version.createdAt, true)}${
        version.reason ? ` · ${version.reason}` : ''
      }`,
      body:
        version.changes?.length > 0
          ? version.changes
              .map((change) => `${change.label}: ${change.before} -> ${change.after}`)
              .join('\n')
          : '初始录入。',
    }))
  );
}

function drawTimeline(doc, timeline) {
  if (!timeline?.length) {
    return;
  }

  drawSectionTitle(doc, '操作时间线', 'Timeline');
  drawNarrativeCards(
    doc,
    timeline.slice(0, 8).map((item) => ({
      title: item.message,
      subtitle: `${item.actorName} · ${formatDate(item.createdAt, true)}`,
      body: Object.keys(item.metadata || {}).length ? JSON.stringify(item.metadata, null, 2) : '系统事件。',
    }))
  );
}

function drawPickupSignature(doc, order) {
  drawSectionTitle(doc, '取货签字记录', 'Pickup');

  const x = doc.page.margins.left;
  const width = doc.page.width - doc.page.margins.left - doc.page.margins.right;
  const signaturePath = resolveUploadPath(order.pickupSignatureUrl);
  const height = signaturePath ? 210 : 132;
  const y = doc.y;

  ensurePageSpace(doc, height + 8);

  doc.roundedRect(x, y, width, height, 16).fillAndStroke('#FFFFFF', '#D9E2EC');
  doc.font('bold').fontSize(11).fillColor('#102A43').text('签字信息', x + 12, y + 12);
  doc.font('regular').fontSize(10).fillColor('#334E68').text(
    [
      `状态：${STATUS_LABELS[order.status] ?? order.status}`,
      `取货人：${order.pickupSignerName || '未签字'}`,
      `批准时间：${formatDate(order.pickupApprovedAt, true)}`,
      `提货时间：${formatDate(order.pickedUpAt, true)}`,
    ].join('\n'),
    x + 12,
    y + 36,
    { width: width - 250 }
  );

  if (signaturePath) {
    try {
      doc.roundedRect(x + width - 226, y + 26, 214, 156, 14).fillAndStroke('#F8FAFC', '#D9E2EC');
      doc.image(signaturePath, x + width - 214, y + 36, {
        fit: [190, 132],
        align: 'center',
        valign: 'center',
      });
    } catch {
      doc.font('regular').fontSize(10).fillColor('#6B7280').text('签字图片读取失败。', x + width - 214, y + 92, {
        width: 190,
        align: 'center',
      });
    }
  } else {
    doc.font('regular').fontSize(10).fillColor('#6B7280').text('当前还没有现场签字图片。', x + 12, y + 92, {
      width: width - 24,
      align: 'left',
    });
  }

  doc.y = y + height + 10;
}

function renderOrderPdf(doc, order) {
  drawHero(
    doc,
    order,
    '订单导出单',
    `${order.customer.companyName} · ${STATUS_LABELS[order.status] ?? order.status} · ${
      PRIORITY_LABELS[order.priority] ?? order.priority
    }`
  );

  drawSectionTitle(doc, '订单概览', 'Order');
  drawInfoCards(doc, [
    { label: '客户', value: order.customer.companyName },
    { label: '联系人', value: order.customer.contactName || '未填写' },
    { label: '电话', value: order.customer.phone || '未填写' },
    { label: '邮箱', value: order.customer.email || '未填写' },
    { label: '玻璃类型', value: order.glassType },
    { label: '厚度', value: order.thickness },
    { label: '数量', value: `${order.quantity} 片` },
    { label: '预计完成', value: formatDate(order.estimatedCompletionDate) },
    { label: '录入时间', value: formatDate(order.createdAt, true) },
    { label: '最后更新', value: formatDate(order.updatedAt, true) },
    { label: '当前版本', value: `V${order.version}` },
    { label: '图纸文件', value: order.drawingName || '未上传' },
  ]);

  drawTextPanel(doc, '特殊说明', order.specialInstructions || '无特殊说明。');

  if (order.cancelledReason) {
    drawTextPanel(doc, '取消说明', order.cancelledReason);
  }

  drawSteps(doc, order);
  drawVersionHistory(doc, order.versionHistory);
  drawTimeline(doc, order.timeline);
}

function renderPickupPdf(doc, order) {
  drawHero(
    doc,
    order,
    'Pickup 记录单',
    `${order.customer.companyName} · ${STATUS_LABELS[order.status] ?? order.status}`
  );

  drawSectionTitle(doc, '取货概览', 'Pickup');
  drawInfoCards(doc, [
    { label: '客户', value: order.customer.companyName },
    { label: '电话', value: order.customer.phone || '未填写' },
    { label: '玻璃类型', value: order.glassType },
    { label: '厚度', value: order.thickness },
    { label: '数量', value: `${order.quantity} 片` },
    { label: '订单状态', value: STATUS_LABELS[order.status] ?? order.status },
    { label: '主管批准', value: formatDate(order.pickupApprovedAt, true) },
    { label: '实际提货', value: formatDate(order.pickedUpAt, true) },
    { label: '取货人', value: order.pickupSignerName || '未签字' },
    { label: '订单版本', value: `V${order.version}` },
  ]);

  drawTextPanel(doc, '特殊说明', order.specialInstructions || '无特殊说明。');
  drawPickupSignature(doc, order);
  drawTimeline(doc, order.timeline);
}

export function sendOrderPdf(res, order, documentType = 'order') {
  const safeDocumentType = documentType === 'pickup' ? 'pickup' : 'order';
  const fileName = `${sanitizeFileName(order.orderNo)}-${safeDocumentType}.pdf`;

  res.setHeader('Content-Type', 'application/pdf');
  res.setHeader('Content-Disposition', `attachment; filename="${fileName}"`);

  const doc = new PDFDocument({
    size: 'A4',
    margin: 40,
    info: {
      Title: `${order.orderNo} ${safeDocumentType === 'pickup' ? 'Pickup Record' : 'Order Slip'}`,
      Author: 'Glass Factory Flow',
      Subject: safeDocumentType === 'pickup' ? 'Pickup Record' : 'Order Export',
    },
  });

  doc.registerFont('regular', FONT_REGULAR_PATH);
  doc.registerFont('bold', FONT_BOLD_PATH);
  doc.font('regular');
  doc.pipe(res);

  if (safeDocumentType === 'pickup') {
    renderPickupPdf(doc, order);
  } else {
    renderOrderPdf(doc, order);
  }

  ensurePageSpace(doc, 40);
  doc.moveDown(0.5);
  doc.font('regular').fontSize(9).fillColor('#6B7280').text(
    `Generated by Glass Factory Flow · ${formatDate(new Date().toISOString(), true)}`,
    doc.page.margins.left,
    doc.y,
    {
      width: doc.page.width - doc.page.margins.left - doc.page.margins.right,
      align: 'right',
    }
  );

  doc.end();
}