const STORAGE_KEY = 'glass-factory-token';
const REFRESH_TOKEN_STORAGE_KEY = 'glass-factory-refresh-token';
const LOCALE_KEY = 'glass-factory-locale';
const PICKUP_TEMPLATE_KEY = 'ready_for_pickup';
const WORKSPACE_API_PREFIX = '/v1/workspace';

const ROLE_LABELS = {
  operator: 'Operations',
  manager: 'Manager',
  admin: 'Admin',
  super_admin: 'Admin',
  finance: 'Finance',
  inspector: 'Inspector',
  customer: 'Customer',
  customer_viewer: 'Customer Viewer',
};

const DEFAULT_SCOPES_BY_CANONICAL_ROLE = Object.freeze({
  super_admin: [
    'orders:read',
    'orders:write',
    'orders:cancel',
    'inventory:read',
    'inventory:write',
    'production:read',
    'production:write',
    'quality:write',
    'logistics:write',
    'finance:read',
    'finance:write',
    'admin:read',
    'admin:write',
    'system:manage',
  ],
  admin: [
    'orders:read',
    'orders:write',
    'orders:cancel',
    'inventory:read',
    'inventory:write',
    'production:read',
    'production:write',
    'quality:write',
    'logistics:write',
    'finance:read',
    'finance:write',
    'admin:read',
    'admin:write',
    'system:manage',
  ],
  manager: [
    'orders:read',
    'orders:write',
    'orders:cancel',
    'inventory:read',
    'inventory:write',
    'production:read',
    'production:write',
    'quality:write',
    'logistics:write',
    'finance:read',
    'admin:read',
  ],
  finance: ['finance:read', 'finance:write', 'admin:read'],
  operator: [
    'orders:read',
    'orders:write',
    'orders:cancel',
    'inventory:read',
    'production:read',
    'logistics:write',
  ],
  inspector: ['orders:read', 'production:read', 'quality:write'],
  customer: ['orders:read', 'orders:write', 'finance:read'],
  customer_viewer: ['orders:read', 'finance:read'],
});

const TAB_LABELS = {
  dashboard: '概览',
  customers: '客户',
  orders: '订单',
  production: '车间',
  pickup: 'Pickup',
  notifications: '通知',
  settings: '设置',
};

const PRIORITY_RANK = {
  rush: 0,
  rework: 1,
  hold: 2,
  normal: 3,
};

const ACTIVE_ORDER_STATUSES = new Set([
  'received',
  'entered',
  'in_production',
  'completed',
  'shipping',
  'ready_for_pickup',
]);

const LOCALE_OPTIONS = Object.freeze([
  { value: 'zh-CN', label: '中文' },
  { value: 'en', label: 'EN' },
]);

const EN_TEXT_REPLACEMENTS = Object.freeze(
  [
    [
      '先把前台、车间、主管和 Pickup 签字这条主链路跑通。手机、平板、桌面浏览器都可直接使用。',
      'Run the operations desk, shop floor, manager approval, and pickup signature workflow end to end. Works on phone, tablet, and desktop browsers.',
    ],
    ['客户沉淀、订单创建、PDF 图纸上传、Rush 与修改高亮。', 'Customer records, order creation, PDF drawings, rush tags, and modification highlights.'],
    ['按工位推进，返工自动回推切玻璃，并保留时间线。', 'Advance work by station, route rework back to cutting automatically, and keep the full timeline.'],
    ['主管批准后才能签字取货，签名图片自动归档。', 'Pickup signatures unlock only after manager approval, and signature images are archived automatically.'],
    ['确认将该订单标记为“已录入系统”并推送给切玻璃工位？', 'Mark this order as entered and send it to the cutting station?'],
    ['当前还没有返工片号记录。', 'No piece-level rework records yet.'],
    ['还没有邮件发送记录。', 'No email delivery records yet.'],
    ['只有可取货或已取货订单才能发送取货提醒。', 'Only ready-for-pickup or picked-up orders can send pickup reminders.'],
    ['订单尚未批准 pickup，不能签字。', 'This order is not approved for pickup yet, so signature is unavailable.'],
    ['请至少选择一片需要返工的玻璃。', 'Select at least one glass piece for rework.'],
    ['只有已完成订单才能批准 pickup。', 'Only completed orders can be approved for pickup.'],
    ['Ready for Pickup 邮件模板已更新。', 'Ready-for-pickup email template updated.'],
    ['电子签字已保存，订单已完成取货。', 'Signature saved and pickup completed.'],
    ['SMTP 未配置，邮件预览已保存。', 'SMTP is not configured; the email preview was saved.'],
    ['客户未填写邮箱，未实际发送。', 'Customer email is missing, so nothing was sent.'],
    ['但邮件发送失败：', 'But email delivery failed: '],
    ['邮件模板和记录已刷新。', 'Email template and logs refreshed.'],
    ['切玻璃待处理片号：', 'Pending cutting pieces: '],
    ['当前工位返工片号记录：', 'Current station rework pieces: '],
    ['待返工片号：', 'Pending rework pieces: '],
    ['取消原因：', 'Cancellation reason: '],
    ['查看图纸：', 'View drawing: '],
    ['当前图纸：', 'Current drawing: '],
    ['工厂流程台', 'Factory Workspace'],
    ['客户邮件模板', 'Customer Email Template'],
    ['最近邮件记录', 'Recent Email Logs'],
    ['玻璃类型字典', 'Glass Type Dictionary'],
    ['请输入新的玻璃类型名称：', 'Enter a new glass type name:'],
    ['玻璃类型名称不能为空。', 'Glass type name is required.'],
    ['玻璃类型名称不能超过 48 个字符。', 'Glass type name must be 48 characters or less.'],
    ['玻璃类型已存在。', 'Glass type already exists.'],
    ['玻璃类型不存在。', 'Glass type not found.'],
    ['玻璃类型已新增。', 'Glass type added.'],
    ['玻璃类型已更新。', 'Glass type updated.'],
    ['玻璃类型已启用。', 'Glass type activated.'],
    ['玻璃类型已停用。', 'Glass type deactivated.'],
    ['工序已开始。', 'Step started.'],
    ['工序已完成。', 'Step completed.'],
    ['订单已推送到切玻璃工位。', 'Order sent to the cutting station.'],
    ['返工提醒已标记已读。', 'Rework alert marked as read.'],
    ['通知已全部标记为已读。', 'All notifications marked as read.'],
    ['订单 PDF 已开始下载。', 'Order PDF download started.'],
    ['Pickup PDF 已开始下载。', 'Pickup PDF download started.'],
    ['订单已创建。', 'Order created.'],
    ['订单已修改。', 'Order updated.'],
    ['客户已创建。', 'Customer created.'],
    ['客户信息已更新。', 'Customer updated.'],
    ['登录成功。', 'Signed in.'],
    ['数据已刷新。', 'Data refreshed.'],
    ['请先完成电子签字。', 'Please complete the signature first.'],
    ['演示账号', 'Demo Accounts'],
    ['登录系统', 'Sign In'],
    ['进入工厂流程台', 'Enter the Factory Workspace'],
    ['客户与订单', 'Customers and Orders'],
    ['车间状态流转', 'Production Flow'],
    ['Pickup 电子签字', 'Pickup Signature'],
    ['活跃订单', 'Active Orders'],
    ['生产中', 'In Production'],
    ['可取货', 'Ready for Pickup'],
    ['超 5 天未推进', 'Over 5 Days Stalled'],
    ['返工', 'Rework'],
    ['工位队列', 'Station Queue'],
    ['当前可开工', 'Ready to Start'],
    ['活跃客户', 'Active Customers'],
    ['全局视角', 'Global View'],
    ['正在载入工厂流程台…', 'Loading Factory Workspace...'],
    ['处理失败', 'Failed'],
    ['已更新', 'Updated'],
    ['关闭提示', 'Dismiss message'],
    ['最近取货记录', 'Recent Pickup History'],
    ['待主管批准', 'Awaiting Manager Approval'],
    ['时间线', 'Timeline'],
    ['版本记录', 'Version History'],
    ['返工片号记录', 'Rework Piece History'],
    ['工序进度', 'Production Steps'],
    ['订单信息', 'Order Details'],
    ['玻璃类型', 'Glass Type'],
    ['特殊说明', 'Special Instructions'],
    ['预计完成日期', 'Estimated Completion Date'],
    ['图纸 PDF / 图片', 'Drawing PDF / Image'],
    ['数量', 'Quantity'],
    ['厚度', 'Thickness'],
    ['联系人', 'Contact'],
    ['电话', 'Phone'],
    ['邮箱', 'Email'],
    ['密码', 'Password'],
    ['概览', 'Overview'],
    ['客户', 'Customers'],
    ['订单', 'Orders'],
    ['车间', 'Production'],
    ['通知', 'Notifications'],
    ['设置', 'Settings'],
    ['启用中', 'Active'],
    ['已停用', 'Inactive'],
    ['进行中', 'In Progress'],
    ['总订单', 'total orders'],
    ['默认模板', 'Default template'],
    ['系统默认', 'System default'],
    ['最近修改', 'Last updated'],
    ['修改人', 'Updated by'],
    ['可用变量', 'Available variables'],
    ['标题模板', 'Subject template'],
    ['正文模板', 'Body template'],
    ['保存模板', 'Save Template'],
    ['新建类型', 'Add Type'],
    ['重命名', 'Rename'],
    ['停用', 'Deactivate'],
    ['启用', 'Activate'],
    ['搜索', 'Search'],
    ['全部', 'All'],
    ['状态', 'Status'],
    ['标签', 'Priority'],
    ['关闭', 'Close'],
    ['取消', 'Cancel'],
    ['已发送', 'Sent'],
    ['预览已保存', 'Preview Saved'],
    ['已跳过', 'Skipped'],
    ['发送失败', 'Failed'],
    ['未知状态', 'Unknown'],
    ['未设置', 'Not set'],
    ['无订单号', 'No Order No.'],
    ['系统', 'System'],
    ['已接单', 'Received'],
    ['已录入系统', 'Entered'],
    ['已完成', 'Completed'],
    ['已取货', 'Picked Up'],
    ['已取消', 'Cancelled'],
    ['普通', 'Normal'],
    ['加急', 'Rush'],
    ['待处理', 'Pending'],
    ['切玻璃', 'Cutting'],
    ['开切口', 'Edging'],
    ['钢化', 'Tempering'],
    ['完成钢化', 'Finishing'],
  ].sort((left, right) => right[0].length - left[0].length)
);

const TRANSLATION_SKIP_SELECTOR =
  'textarea, input, .email-log-body, [data-no-translate]';

const state = {
  token: localStorage.getItem(STORAGE_KEY),
  refreshToken: localStorage.getItem(REFRESH_TOKEN_STORAGE_KEY),
  user: null,
  options: {
    glassTypes: [],
    thicknessOptions: [],
    priorities: [],
    orderStatuses: [],
    productionSteps: [],
  },
  data: {
    summary: {},
    customers: [],
    orders: [],
    orderDetails: {},
    notifications: [],
    glassTypeCatalog: [],
    notificationTemplate: null,
    emailLogs: [],
  },
  ui: {
    activeTab: 'dashboard',
    locale: localStorage.getItem(LOCALE_KEY) || 'zh-CN',
    flash: null,
    modal: null,
    orderFilters: {
      query: '',
      status: 'all',
      priority: 'all',
    },
    pickupFilters: {
      query: '',
    },
    customerGroup: 'company',
    workerGroup: 'company',
  },
};

let appRoot;
let signaturePad = null;
let refreshTokenRequest = null;

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function translateString(value) {
  const raw = String(value ?? '');
  if (state.ui.locale !== 'en') {
    return raw;
  }

  let translated = raw;
  for (const [source, target] of EN_TEXT_REPLACEMENTS) {
    translated = translated.replaceAll(source, target);
  }

  return translated;
}

function localizeText(value) {
  return translateString(value);
}

function unwrapApiPayload(rawPayload) {
  return rawPayload && typeof rawPayload === 'object' && rawPayload.data !== undefined
    ? rawPayload.data
    : rawPayload;
}

function buildApiError(response, rawPayload) {
  const error = new Error(
    rawPayload?.error?.message || rawPayload?.error || rawPayload?.detail || '请求失败。'
  );

  error.status = response.status;
  error.payload = rawPayload;
  return error;
}

function resolveCanonicalRole(role) {
  const normalized = String(role || '').trim().toLowerCase();
  return normalized || 'operator';
}

function resolveUserScopes(role, scopes = [], stage = null) {
  const canonicalRole = resolveCanonicalRole(role);
  const providedScopes = Array.isArray(scopes)
    ? scopes
        .map((scope) => String(scope || '').trim())
        .filter(Boolean)
    : [];
  const resolvedScopes = new Set(
    providedScopes.length ? providedScopes : DEFAULT_SCOPES_BY_CANONICAL_ROLE[canonicalRole] || []
  );

  if (canonicalRole === 'operator' && stage) {
    resolvedScopes.add('production:read');
    resolvedScopes.add('production:write');
    resolvedScopes.add('orders:read');
  }

  return [...resolvedScopes].sort();
}

function resolveHomePath(role) {
  const canonicalRole = resolveCanonicalRole(role);
  if (['customer', 'customer_viewer'].includes(canonicalRole)) {
    return '/app';
  }
  if (['admin', 'super_admin', 'manager', 'finance'].includes(canonicalRole)) {
    return '/admin';
  }
  return '/platform';
}

function normalizeUser(user) {
  const canonicalRole = String(
    user?.canonicalRole || resolveCanonicalRole(user?.role)
  )
    .trim()
    .toLowerCase();
  const stage = user?.stage || null;
  const homePath = user?.homePath || resolveHomePath(canonicalRole);
  return {
    ...user,
    id: user?.id,
    name: user?.name || user?.display_name || user?.displayName || user?.username || '',
    email: user?.email || '',
    role: canonicalRole,
    canonicalRole,
    scopes: resolveUserScopes(canonicalRole, user?.scopes, stage),
    stage,
    stageLabel: user?.stageLabel || user?.stage_label || stage || null,
    customerId: user?.customerId || user?.customer_id || null,
    homePath,
    shell: user?.shell || (homePath === '/app' ? 'app' : homePath === '/admin' ? 'admin' : 'platform'),
  };
}

function hasScope(scope) {
  return Boolean(state.user?.scopes?.includes(scope));
}

function hasAnyScope(scopes) {
  return scopes.some((scope) => hasScope(scope));
}

function isStageWorker() {
  return Boolean(state.user?.stage);
}

function canManageOrders() {
  return hasScope('orders:write');
}

function canCancelOrders() {
  return hasScope('orders:cancel');
}

function canUsePickup() {
  return hasScope('logistics:write');
}

function canApprovePickupAction() {
  return ['manager', 'admin', 'super_admin'].includes(state.user?.canonicalRole || '');
}

function canOpenSettings() {
  return hasAnyScope(['system:manage', 'admin:write']);
}

function canViewCustomers() {
  return canManageOrders();
}

function canViewOrders() {
  return canManageOrders() || canApprovePickupAction();
}

function getWorkspaceTitle() {
  if (isStageWorker()) {
    return 'Shop Floor';
  }
  return ROLE_LABELS[state.user?.canonicalRole] || 'Operations';
}

function getRoleFocusCopy() {
  if (isStageWorker()) {
    return `你当前在 ${escapeHtml(
      state.user.stageLabel || state.user.stage || '生产工位'
    )}，优先处理高亮返工与加急订单。`;
  }
  if (canApprovePickupAction()) {
    return '经理视角今天重点关注已完成订单的 Pickup 批准，以及所有返工高亮。';
  }
  return '操作端今天重点处理新建订单、录入完成以及 Ready for Pickup 的签字交付。';
}

function persistSession(payload) {
  const nextToken = payload?.token || payload?.access_token || null;
  const nextRefreshToken = payload?.refreshToken || payload?.refresh_token || null;

  if (nextToken) {
    state.token = nextToken;
    localStorage.setItem(STORAGE_KEY, nextToken);
  }

  if (nextRefreshToken) {
    state.refreshToken = nextRefreshToken;
    localStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, nextRefreshToken);
  }

  if (payload?.user) {
    state.user = normalizeUser(payload.user);
  }
}

function shouldResetSession(error) {
  return error?.status === 401;
}

async function requestAccessTokenRefresh() {
  if (!state.refreshToken) {
    throw new Error('Refresh token is unavailable.');
  }

  if (refreshTokenRequest) {
    return refreshTokenRequest;
  }

  const fallbackKey = `idem-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const idempotencyKey = globalThis.crypto?.randomUUID?.() ?? fallbackKey;

  refreshTokenRequest = fetch('/v1/auth/refresh', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Idempotency-Key': idempotencyKey,
    },
    body: JSON.stringify({ refreshToken: state.refreshToken }),
  })
    .then(async (response) => {
      const rawPayload = await response.json().catch(() => ({}));
      const payload = unwrapApiPayload(rawPayload);

      if (!response.ok) {
        throw buildApiError(response, rawPayload);
      }

      persistSession(payload);
      return payload;
    })
    .finally(() => {
      refreshTokenRequest = null;
    });

  return refreshTokenRequest;
}

function syncDocumentLocale() {
  document.documentElement.lang = state.ui.locale === 'en' ? 'en' : 'zh-CN';
}

function applyLocaleToTree(root) {
  syncDocumentLocale();
  if (!root || state.ui.locale !== 'en') {
    return;
  }

  const shouldSkipNode = (node) => node.parentElement?.closest(TRANSLATION_SKIP_SELECTOR);
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      if (!node.nodeValue?.trim()) {
        return NodeFilter.FILTER_REJECT;
      }

      return shouldSkipNode(node) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
    },
  });
  const nodes = [];

  while (walker.nextNode()) {
    nodes.push(walker.currentNode);
  }

  for (const node of nodes) {
    const translated = translateString(node.nodeValue);
    if (translated !== node.nodeValue) {
      node.nodeValue = translated;
    }
  }

  root.querySelectorAll('[placeholder], [aria-label], [title]').forEach((element) => {
    ['placeholder', 'aria-label', 'title'].forEach((attributeName) => {
      const currentValue = element.getAttribute(attributeName);
      if (currentValue) {
        element.setAttribute(attributeName, translateString(currentValue));
      }
    });
  });
}

function renderLocaleSwitch() {
  return `
    <div class="locale-switch" data-no-translate>
      ${LOCALE_OPTIONS.map(
        (localeOption) => `
          <button
            class="locale-button ${state.ui.locale === localeOption.value ? 'is-active' : ''}"
            type="button"
            data-action="switch-locale"
            data-locale="${escapeHtml(localeOption.value)}"
          >
            ${escapeHtml(localeOption.label)}
          </button>
        `
      ).join('')}
    </div>
  `;
}

function formatDate(value, withTime = false) {
  if (!value) {
    return '未设置';
  }

  const date = new Date(value);
  return new Intl.DateTimeFormat(state.ui.locale === 'en' ? 'en-AU' : 'zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: withTime ? '2-digit' : undefined,
    minute: withTime ? '2-digit' : undefined,
  }).format(date);
}

function formatDateInput(value) {
  if (!value) {
    return '';
  }

  return new Date(value).toISOString().slice(0, 10);
}

function formatPieceNumbers(pieceNumbers) {
  const normalized = [...new Set((pieceNumbers || []).map((pieceNumber) => Number(pieceNumber)))]
    .filter((pieceNumber) => Number.isInteger(pieceNumber) && pieceNumber > 0)
    .sort((left, right) => left - right);

  if (!normalized.length) {
    return '未指定';
  }

  return normalized.map((pieceNumber) => `第 ${pieceNumber} 片`).join('、');
}

function buildEmailResultMessage(prefix, emailLog) {
  if (!emailLog) {
    return prefix;
  }

  switch (emailLog.status) {
    case 'sent':
      return `${prefix}客户邮件已发送。`;
    case 'preview':
      return `${prefix}SMTP 未配置，邮件预览已保存。`;
    case 'skipped':
      return `${prefix}客户未填写邮箱，未实际发送。`;
    case 'failed':
      return `${prefix}但邮件发送失败：${emailLog.errorMessage || '请检查 SMTP 配置。'}`;
    default:
      return prefix;
  }
}

function getEmailStatusLabel(status) {
  switch (status) {
    case 'sent':
      return '已发送';
    case 'preview':
      return '预览已保存';
    case 'skipped':
      return '已跳过';
    case 'failed':
      return '发送失败';
    default:
      return status || '未知状态';
  }
}

function setFlash(type, message) {
  state.ui.flash = { type, message: localizeText(message) };
  render();
}

function clearFlash() {
  state.ui.flash = null;
  render();
}

function getTabs() {
  const tabs = ['dashboard'];
  if (canViewCustomers()) {
    tabs.push('customers');
  }
  if (canViewOrders()) {
    tabs.push('orders');
  }
  if (isStageWorker()) {
    tabs.push('production');
  }
  if (canUsePickup()) {
    tabs.push('pickup');
  }
  tabs.push('notifications');
  if (canOpenSettings()) {
    tabs.push('settings');
  }
  return tabs;
}

function ensureActiveTab() {
  const tabs = getTabs();
  if (!tabs.includes(state.ui.activeTab)) {
    state.ui.activeTab = tabs[0] ?? 'dashboard';
  }
}

function getOrderById(orderId) {
  const detailedOrder = state.data.orderDetails?.[orderId];
  if (detailedOrder) {
    return detailedOrder;
  }

  return state.data.orders.find((order) => order.id === orderId) ?? null;
}

function getCustomerById(customerId) {
  return state.data.customers.find((customer) => customer.id === customerId) ?? null;
}

function getCurrentModalOrder() {
  if (!state.ui.modal?.orderId) {
    return null;
  }

  return getOrderById(state.ui.modal.orderId);
}

function getCurrentModalCustomer() {
  if (!state.ui.modal?.customerId) {
    return null;
  }

  return getCustomerById(state.ui.modal.customerId);
}

function compareOrders(left, right) {
  if ((left.status === 'cancelled') !== (right.status === 'cancelled')) {
    return left.status === 'cancelled' ? 1 : -1;
  }

  const priorityDelta =
    (PRIORITY_RANK[left.priority] ?? 99) - (PRIORITY_RANK[right.priority] ?? 99);
  if (priorityDelta !== 0) {
    return priorityDelta;
  }

  if (left.isStale !== right.isStale) {
    return left.isStale ? -1 : 1;
  }

  if (left.reworkOpen !== right.reworkOpen) {
    return left.reworkOpen ? -1 : 1;
  }

  return new Date(right.updatedAt) - new Date(left.updatedAt);
}

function sortOrders(orders) {
  return [...orders].sort(compareOrders);
}

function buildGroups(orders, mode, workerStage = null) {
  const groups = new Map();

  sortOrders(orders).forEach((order) => {
    const groupKey =
      mode === 'date'
        ? (order.estimatedCompletionDate || order.createdAt).slice(0, 10)
        : mode === 'glass'
          ? order.glassType
          : mode === 'thickness'
            ? order.thickness
        : order.customer.companyName;
    const groupLabel = mode === 'date' ? formatDate(groupKey) : groupKey;
    const step = workerStage
      ? order.steps.find((candidate) => candidate.key === workerStage)
      : null;

    const group = groups.get(groupKey) ?? {
      key: groupKey,
      label: groupLabel,
      orders: [],
      total: 0,
      active: 0,
      hasHighlight: false,
    };

    group.orders.push(order);
    group.total += 1;
    if (ACTIVE_ORDER_STATUSES.has(order.status)) {
      group.active += 1;
    }
    if (workerStage) {
      group.hasHighlight ||= Boolean(
        step?.reworkUnread || step?.isAvailable || step?.status === 'in_progress'
      );
    } else {
      group.hasHighlight ||= ACTIVE_ORDER_STATUSES.has(order.status);
    }

    groups.set(groupKey, group);
  });

  return [...groups.values()].sort((left, right) => {
    if (mode === 'date') {
      return left.key < right.key ? 1 : -1;
    }
    if (mode === 'thickness') {
      return Number.parseInt(left.key, 10) - Number.parseInt(right.key, 10);
    }
    return left.label.localeCompare(
      right.label,
      state.ui.locale === 'en' ? 'en' : 'zh-Hans-CN'
    );
  });
}

function getFilteredOrders() {
  const query = state.ui.orderFilters.query.trim().toLowerCase();
  return sortOrders(state.data.orders).filter((order) => {
    const matchesQuery =
      !query ||
      [
        order.orderNo,
        order.customer.companyName,
        order.customer.phone,
        order.customer.email,
      ]
        .join(' ')
        .toLowerCase()
        .includes(query);
    const matchesStatus =
      state.ui.orderFilters.status === 'all' ||
      order.status === state.ui.orderFilters.status;
    const matchesPriority =
      state.ui.orderFilters.priority === 'all' ||
      order.priority === state.ui.orderFilters.priority;
    return matchesQuery && matchesStatus && matchesPriority;
  });
}

function getPickupOrders() {
  const query = state.ui.pickupFilters.query.trim().toLowerCase();
  return sortOrders(state.data.orders).filter((order) => {
    if (!query) {
      return true;
    }

    return [order.orderNo, order.customer.companyName, order.customer.phone, order.customer.email]
      .join(' ')
      .toLowerCase()
      .includes(query);
  });
}

function getWorkerOrders() {
  if (!state.user?.stage) {
    return [];
  }

  return sortOrders(state.data.orders).filter((order) => {
    if (order.status === 'cancelled') {
      return false;
    }

    const step = order.steps.find((candidate) => candidate.key === state.user.stage);
    return step && (step.status !== 'completed' || step.reworkUnread || order.reworkOpen);
  });
}

function renderFlash() {
  if (!state.ui.flash) {
    return '';
  }

  return `
    <div class="flash flash-${escapeHtml(state.ui.flash.type)}">
      <div>
        <strong>${escapeHtml(state.ui.flash.type === 'error' ? '处理失败' : '已更新')}</strong>
        <p>${escapeHtml(state.ui.flash.message)}</p>
      </div>
      <button class="icon-button" data-action="clear-flash" aria-label="关闭提示">×</button>
    </div>
  `;
}

function renderLogin() {
  appRoot.innerHTML = `
    <section class="auth-shell">
      <div class="auth-story">
        <div class="eyebrow">Phase 1 MVP</div>
        <h1>Glass Factory Flow</h1>
        <p class="lead">
          先把前台、车间、主管和 Pickup 签字这条主链路跑通。手机、平板、桌面浏览器都可直接使用。
        </p>
        <div class="story-grid">
          <article>
            <span>01</span>
            <h2>客户与订单</h2>
            <p>客户沉淀、订单创建、PDF 图纸上传、Rush 与修改高亮。</p>
          </article>
          <article>
            <span>02</span>
            <h2>车间状态流转</h2>
            <p>按工位推进，返工自动回推切玻璃，并保留时间线。</p>
          </article>
          <article>
            <span>03</span>
            <h2>Pickup 电子签字</h2>
            <p>主管批准后才能签字取货，签名图片自动归档。</p>
          </article>
        </div>
      </div>

      <div class="auth-panel">
        ${renderLocaleSwitch()}
        <div class="eyebrow">登录</div>
        <h2>进入工厂流程台</h2>
        <form class="stack-form" data-form="login">
          <label>
            <span>邮箱</span>
            <input name="email" type="email" placeholder="请输入邮箱" required />
          </label>
          <label>
            <span>密码</span>
            <input name="password" type="password" placeholder="请输入密码" required />
          </label>
          <button class="primary-button" type="submit">登录系统</button>
        </form>

        <div class="demo-accounts">
          <h3>演示账号</h3>
          <button class="credential-card" type="button" data-action="use-demo" data-email="office@glass.local" data-password="office123">
            <strong>Operations Desk</strong>
            <span>点击填入操作台演示账号</span>
          </button>
          <button class="credential-card" type="button" data-action="use-demo" data-email="cutting@glass.local" data-password="worker123">
            <strong>Cutting Operator</strong>
            <span>点击填入切割工位演示账号</span>
          </button>
          <button class="credential-card" type="button" data-action="use-demo" data-email="supervisor@glass.local" data-password="supervisor123">
            <strong>Production Manager</strong>
            <span>点击填入经理演示账号</span>
          </button>
        </div>
      </div>
    </section>
  `;
}

function renderSummaryCards() {
  const summary = state.data.summary;
  const cards = [
    ['活跃订单', summary.activeOrders ?? 0, 'teal'],
    ['生产中', summary.inProductionOrders ?? 0, 'amber'],
    ['可取货', summary.readyForPickupOrders ?? 0, 'green'],
    ['超 5 天未推进', summary.staleOrders ?? 0, 'red'],
    ['Rush', summary.rushOrders ?? 0, 'gold'],
    ['返工', summary.reworkOrders ?? 0, 'orange'],
  ];

  if (isStageWorker()) {
    cards.unshift(['工位队列', summary.workerQueue ?? 0, 'blue']);
    cards.unshift(['当前可开工', summary.workerReady ?? 0, 'indigo']);
  } else {
    cards.unshift(['活跃客户', summary.activeCustomers ?? 0, 'slate']);
  }

  return `
    <div class="summary-grid">
      ${cards
        .map(
          ([label, value, tone]) => `
            <article class="metric-card tone-${tone}">
              <span>${escapeHtml(label)}</span>
              <strong>${escapeHtml(value)}</strong>
            </article>
          `
        )
        .join('')}
    </div>
  `;
}

function renderOrderBadges(order) {
  const badges = [
    `<span class="badge status-${escapeHtml(order.status)}">${escapeHtml(order.statusLabel)}</span>`,
  ];

  if (order.priority !== 'normal') {
    badges.push(
      `<span class="badge priority-${escapeHtml(order.priority)}">${escapeHtml(
        order.priorityLabel
      )}</span>`
    );
  }
  if (order.isModified) {
    badges.push('<span class="badge badge-warning">已修改</span>');
  }
  if (order.reworkOpen) {
    badges.push('<span class="badge badge-danger">返工中</span>');
  }
  if (order.isStale) {
    badges.push(`<span class="badge badge-danger">${escapeHtml(order.staleDays)} 天未推进</span>`);
  }
  if (order.status === 'ready_for_pickup' && order.pickupWaitingDays > 0) {
    badges.push(
      `<span class="badge badge-muted">待取 ${escapeHtml(order.pickupWaitingDays)} 天</span>`
    );
  }

  return badges.join('');
}

function renderStepsStrip(steps) {
  return `
    <div class="steps-strip">
      ${steps
        .map(
          (step) => `
            <span class="step-pill ${escapeHtml(step.status)} ${
              step.reworkUnread ? 'has-alert' : ''
            }">
              ${escapeHtml(step.label)}
            </span>
          `
        )
        .join('')}
    </div>
  `;
}

function renderOrderCard(order, context = 'orders') {
  const canEdit = canManageOrders() && !['shipping', 'delivered', 'picked_up', 'cancelled'].includes(order.status);
  const canApprovePickup = canApprovePickupAction() && order.status === 'completed';
  const canMarkEntered = canManageOrders() && order.status === 'received';
  const canCancel = canCancelOrders() && !['shipping', 'delivered', 'picked_up', 'cancelled'].includes(order.status) && order.canCancel;
  const canSign = canUsePickup() && order.status === 'ready_for_pickup';
  const canExportPickup = ['ready_for_pickup', 'picked_up'].includes(order.status);
  const canSendPickupEmail = canUsePickup() && ['ready_for_pickup', 'picked_up'].includes(order.status);

  return `
    <article class="order-card ${order.isStale ? 'is-stale' : ''} ${
      order.reworkOpen ? 'is-rework' : ''
    } ${order.status === 'cancelled' ? 'is-cancelled' : ''}">
      <header>
        <div>
          <p class="kicker">${escapeHtml(order.customer.companyName)}</p>
          <h3>${escapeHtml(order.orderNo)}</h3>
        </div>
        <div class="badge-row">${renderOrderBadges(order)}</div>
      </header>

      <div class="order-meta-grid">
        <div>
          <span>玻璃</span>
          <strong>${escapeHtml(order.glassType)}</strong>
        </div>
        <div>
          <span>厚度</span>
          <strong>${escapeHtml(order.thickness)}</strong>
        </div>
        <div>
          <span>数量</span>
          <strong>${escapeHtml(order.quantity)} 片</strong>
        </div>
        <div>
          <span>预计完成</span>
          <strong>${escapeHtml(formatDate(order.estimatedCompletionDate))}</strong>
        </div>
      </div>

      ${renderStepsStrip(order.steps)}

      ${
        order.openReworkPieceSummary
          ? `<p class="warning-note compact-note">待返工片号：${escapeHtml(
              order.openReworkPieceSummary
            )}</p>`
          : ''
      }

      <div class="card-footer">
        <div class="meta-stack">
          <span>录入时间 ${escapeHtml(formatDate(order.createdAt, true))}</span>
          <span>客户电话 ${escapeHtml(order.customer.phone || '未填写')}</span>
        </div>
        <div class="inline-actions">
          <button class="ghost-button" data-action="open-order-detail" data-order-id="${escapeHtml(
            order.id
          )}">详情</button>
          ${
            canEdit
              ? `<button class="ghost-button" data-action="open-order-form" data-order-id="${escapeHtml(
                  order.id
                )}">编辑</button>`
              : ''
          }
          ${
            canCancel
              ? `<button class="ghost-button danger-button" data-action="cancel-order" data-order-id="${escapeHtml(
                  order.id
                )}">${escapeHtml(order.canCancelLabel || '取消订单')}</button>`
              : ''
          }
          ${
            canMarkEntered
              ? `<button class="ghost-button" data-action="mark-entered" data-order-id="${escapeHtml(
                  order.id
                )}">标记已录入</button>`
              : ''
          }
          ${
            canApprovePickup
              ? `<button class="primary-button compact" data-action="approve-pickup" data-order-id="${escapeHtml(
                  order.id
                )}">批准 Pickup</button>`
              : ''
          }
          ${
            canSign
              ? `<button class="primary-button compact" data-action="open-signature" data-order-id="${escapeHtml(
                  order.id
                )}">签字提货</button>`
              : ''
          }
          ${
            context === 'pickup' && canExportPickup
              ? `<button class="ghost-button" data-action="export-pickup-pdf" data-order-id="${escapeHtml(
                  order.id
                )}">Pickup PDF</button>`
              : ''
          }
          ${
            context === 'pickup' && canSendPickupEmail
              ? `<button class="ghost-button" data-action="send-pickup-email" data-order-id="${escapeHtml(
                  order.id
                )}">发送邮件</button>`
              : ''
          }
        </div>
      </div>
    </article>
  `;
}

function renderProductionCard(order) {
  const step = order.steps.find((candidate) => candidate.key === state.user.stage);
  const isTempering = state.user.stage === 'tempering';
  const canStart = step?.status === 'pending' && step.isAvailable && !isTempering;
  const canComplete =
    (step?.status === 'in_progress' && step.isAvailable) ||
    (state.user.stage === 'tempering' && step?.isAvailable && step?.status !== 'completed');
  const canRework =
    !isTempering && state.user.stage !== 'cutting' && ['in_progress', 'completed'].includes(step?.status);
  const canAck = state.user.stage === 'cutting' && step?.reworkUnread;

  return `
    <article class="order-card production-card ${step?.reworkUnread ? 'is-rework' : ''}">
      <header>
        <div>
          <p class="kicker">${escapeHtml(order.customer.companyName)}</p>
          <h3>${escapeHtml(order.orderNo)}</h3>
        </div>
        <div class="badge-row">${renderOrderBadges(order)}</div>
      </header>

      <div class="order-meta-grid compact-grid">
        <div>
          <span>当前工位</span>
          <strong>${escapeHtml(step?.label || '-')}</strong>
        </div>
        <div>
          <span>工位状态</span>
          <strong>${escapeHtml(step?.statusLabel || '-')}</strong>
        </div>
        <div>
          <span>规格</span>
          <strong>${escapeHtml(order.glassType)} / ${escapeHtml(order.thickness)}</strong>
        </div>
        <div>
          <span>数量</span>
          <strong>${escapeHtml(order.quantity)} 片</strong>
        </div>
      </div>

      <p class="worker-hint">
        ${
          step?.isBlocked
            ? '上一个工序还没完成，当前工位暂时不能接单。'
            : isTempering
              ? '钢化工位只保留查看与完结操作，避免多余点击。'
              : '工序开始后可随时标记完成；发现问题可回推返工。'
        }
      </p>

      ${renderStepsStrip(order.steps)}

      ${
        state.user.stage === 'cutting' && order.openReworkPieceSummary
          ? `<p class="warning-note compact-note">切玻璃待处理片号：${escapeHtml(
              order.openReworkPieceSummary
            )}</p>`
          : ''
      }

      ${
        step?.reworkPieceSummary && state.user.stage !== 'cutting'
          ? `<p class="subtle-copy">当前工位返工片号记录：${escapeHtml(step.reworkPieceSummary)}</p>`
          : ''
      }

      <div class="inline-actions worker-actions">
        ${
          canAck
            ? `<button class="ghost-button" data-action="ack-rework" data-order-id="${escapeHtml(
                order.id
              )}">已读返工提醒</button>`
            : ''
        }
        ${
          canStart
            ? `<button class="primary-button compact" data-action="start-step" data-order-id="${escapeHtml(
                order.id
              )}" data-step-key="${escapeHtml(step.key)}">开始生产</button>`
            : ''
        }
        ${
          canComplete
            ? `<button class="primary-button compact" data-action="complete-step" data-order-id="${escapeHtml(
                order.id
              )}" data-step-key="${escapeHtml(step.key)}">生产完成</button>`
            : ''
        }
        ${
          canRework
            ? `<button class="ghost-button" data-action="report-rework" data-order-id="${escapeHtml(
                order.id
              )}" data-step-key="${escapeHtml(step.key)}">返工</button>`
            : ''
        }
        <button class="ghost-button" data-action="open-order-detail" data-order-id="${escapeHtml(
          order.id
        )}">详情</button>
      </div>
    </article>
  `;
}

function renderDashboardView() {
  const urgentOrders = sortOrders(state.data.orders).slice(0, 5);

  return `
    <section class="panel">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">Realtime Overview</p>
          <h2>今天的工厂节奏</h2>
        </div>
        <button class="ghost-button" data-action="refresh-data">刷新数据</button>
      </div>
      ${renderSummaryCards()}
    </section>

    <section class="panel split-panel">
      <div>
        <div class="panel-heading slim">
          <h2>优先处理</h2>
        </div>
        <div class="list-stack">
          ${
            urgentOrders.length
              ? urgentOrders.map((order) => renderOrderCard(order)).join('')
              : '<div class="empty-state">当前还没有订单。</div>'
          }
        </div>
      </div>
      <div>
        <div class="panel-heading slim">
          <h2>当前角色重点</h2>
        </div>
        <div class="guidance-card">
          <p>
            ${
              getRoleFocusCopy()
            }
          </p>
          <ul class="guidance-list">
            <li>Rush 订单默认排在最前。</li>
            <li>超过 5 天未推进的订单会标红。</li>
            <li>订单修改后，车间端会看到高亮提醒。</li>
          </ul>
        </div>
      </div>
    </section>
  `;
}

function renderCustomersView() {
  const groups = buildGroups(state.data.orders, state.ui.customerGroup);

  return `
    <section class="panel">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">Customer Board</p>
          <h2>客户与在制订单汇总</h2>
        </div>
        <div class="inline-actions">
          <label class="mini-select">
            <span>分组</span>
            <select data-field="customer-group">
              <option value="company" ${state.ui.customerGroup === 'company' ? 'selected' : ''}>按公司</option>
              <option value="date" ${state.ui.customerGroup === 'date' ? 'selected' : ''}>按日期</option>
            </select>
          </label>
          <button class="primary-button compact" data-action="open-customer-form">新增客户</button>
        </div>
      </div>
      <div class="group-grid">
        ${
          groups.length
            ? groups
                .map(
                  (group) => `
                    <article class="group-card ${group.hasHighlight ? 'active' : ''}">
                      <strong>${escapeHtml(group.label)}</strong>
                      <span>${escapeHtml(group.active)} 个进行中 / 共 ${escapeHtml(group.total)} 单</span>
                    </article>
                  `
                )
                .join('')
            : '<div class="empty-state">还没有订单分组。</div>'
        }
      </div>
    </section>

    <section class="panel">
      <div class="panel-heading slim">
        <h2>客户列表</h2>
      </div>
      <div class="list-stack">
        ${
          state.data.customers.length
            ? state.data.customers
                .map(
                  (customer) => `
                    <article class="customer-card ${customer.hasActiveOrders ? 'active' : ''}">
                      <div>
                        <p class="kicker">${escapeHtml(customer.contactName || '未填写联系人')}</p>
                        <h3>${escapeHtml(customer.companyName)}</h3>
                        <p>${escapeHtml(customer.phone || '未填写电话')} · ${escapeHtml(
                          customer.email || '未填写邮箱'
                        )}</p>
                      </div>
                      <div class="customer-summary">
                        <span>${escapeHtml(customer.activeOrders)} 个进行中</span>
                        <span>最近订单 ${escapeHtml(formatDate(customer.lastOrderAt))}</span>
                        <button class="ghost-button" data-action="open-customer-form" data-customer-id="${escapeHtml(
                          customer.id
                        )}">编辑</button>
                      </div>
                    </article>
                  `
                )
                .join('')
            : '<div class="empty-state">先新增客户，再开始录订单。</div>'
        }
      </div>
    </section>
  `;
}

function renderOrdersView() {
  const orders = getFilteredOrders();

  return `
    <section class="panel">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">Orders</p>
          <h2>订单管理</h2>
        </div>
        <button class="primary-button compact" data-action="open-order-form">新建订单</button>
      </div>

      <form class="filter-bar" data-form="order-filters">
        <label>
          <span>搜索</span>
          <input name="query" value="${escapeHtml(state.ui.orderFilters.query)}" placeholder="订单号 / 客户 / 电话 / 邮箱" />
        </label>
        <label>
          <span>状态</span>
          <select name="status">
            <option value="all">全部</option>
            ${state.options.orderStatuses
              .map(
                (status) => `
                  <option value="${escapeHtml(status.value)}" ${
                    state.ui.orderFilters.status === status.value ? 'selected' : ''
                  }>${escapeHtml(status.label)}</option>
                `
              )
              .join('')}
          </select>
        </label>
        <label>
          <span>标签</span>
          <select name="priority">
            <option value="all">全部</option>
            ${state.options.priorities
              .map(
                (priority) => `
                  <option value="${escapeHtml(priority.value)}" ${
                    state.ui.orderFilters.priority === priority.value ? 'selected' : ''
                  }>${escapeHtml(priority.label)}</option>
                `
              )
              .join('')}
          </select>
        </label>
        <button class="ghost-button" type="submit">应用筛选</button>
      </form>
    </section>

    <section class="list-stack">
      ${
        orders.length
          ? orders.map((order) => renderOrderCard(order)).join('')
          : '<div class="empty-state">当前筛选条件下没有订单。</div>'
      }
    </section>
  `;
}

function renderProductionView() {
  const groups = buildGroups(getWorkerOrders(), state.ui.workerGroup, state.user.stage);

  return `
    <section class="panel">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">Shop Floor</p>
          <h2>${escapeHtml(state.user.stageLabel || '当前工位')}</h2>
        </div>
        <label class="mini-select">
          <span>查看方式</span>
          <select data-field="worker-group">
            <option value="company" ${state.ui.workerGroup === 'company' ? 'selected' : ''}>按公司</option>
            <option value="date" ${state.ui.workerGroup === 'date' ? 'selected' : ''}>按日期</option>
            <option value="glass" ${state.ui.workerGroup === 'glass' ? 'selected' : ''}>按玻璃类型</option>
            <option value="thickness" ${state.ui.workerGroup === 'thickness' ? 'selected' : ''}>按厚度</option>
          </select>
        </label>
      </div>
      <p class="subtle-copy">有在进行中的订单分组会带亮色边框；返工推回切玻璃后，高亮在已读前不会消失。</p>
    </section>

    <section class="group-stack">
      ${
        groups.length
          ? groups
              .map(
                (group) => `
                  <div class="panel group-panel ${group.hasHighlight ? 'active' : ''}">
                    <div class="panel-heading slim">
                      <h2>${escapeHtml(group.label)}</h2>
                      <span>${escapeHtml(group.active)} 个进行中</span>
                    </div>
                    <div class="list-stack compact-list">
                      ${group.orders.map((order) => renderProductionCard(order)).join('')}
                    </div>
                  </div>
                `
              )
              .join('')
          : '<div class="empty-state">当前工位没有待处理订单。</div>'
      }
    </section>
  `;
}

function renderPickupView() {
  const orders = getPickupOrders();
  const approvalQueue = orders.filter((order) => order.status === 'completed');
  const readyQueue = orders.filter((order) => order.status === 'ready_for_pickup');
  const historyQueue = orders.filter((order) => ['picked_up', 'delivered'].includes(order.status)).slice(0, 10);

  return `
    <section class="panel">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">Pickup Desk</p>
          <h2>取货批准与签字</h2>
        </div>
      </div>

      <form class="filter-bar" data-form="pickup-filters">
        <label>
          <span>搜索</span>
          <input name="query" value="${escapeHtml(state.ui.pickupFilters.query)}" placeholder="订单号 / 客户 / 电话 / 邮箱" />
        </label>
        <button class="ghost-button" type="submit">搜索</button>
      </form>
    </section>

    <section class="panel">
      <div class="panel-heading slim">
        <h2>待主管批准</h2>
        <span>${escapeHtml(approvalQueue.length)} 单</span>
      </div>
      <div class="list-stack compact-list">
        ${
          approvalQueue.length
            ? approvalQueue.map((order) => renderOrderCard(order, 'pickup')).join('')
            : '<div class="empty-state">没有待批准的已完成订单。</div>'
        }
      </div>
    </section>

    <section class="panel">
      <div class="panel-heading slim">
        <h2>可取货</h2>
        <span>${escapeHtml(readyQueue.length)} 单</span>
      </div>
      <div class="list-stack compact-list">
        ${
          readyQueue.length
            ? readyQueue.map((order) => renderOrderCard(order, 'pickup')).join('')
            : '<div class="empty-state">当前没有可签字提货的订单。</div>'
        }
      </div>
    </section>

    <section class="panel">
      <div class="panel-heading slim">
        <h2>最近取货记录</h2>
      </div>
      <div class="list-stack compact-list">
        ${
          historyQueue.length
            ? historyQueue.map((order) => renderOrderCard(order, 'pickup')).join('')
            : '<div class="empty-state">还没有已完成提货的订单记录。</div>'
        }
      </div>
    </section>
  `;
}

function renderNotificationsView() {
  return `
    <section class="panel">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">Notifications</p>
          <h2>系统提醒</h2>
        </div>
        <button class="ghost-button" data-action="mark-notifications-read">全部标记已读</button>
      </div>
      <div class="list-stack">
        ${
          state.data.notifications.length
            ? state.data.notifications
                .map(
                  (item) => `
                    <article class="notification-card ${item.isRead ? 'is-read' : ''} severity-${escapeHtml(
                      item.severity
                    )}">
                      <div>
                        <h3>${escapeHtml(item.title)}</h3>
                        <p>${escapeHtml(item.message)}</p>
                      </div>
                      <div class="meta-stack">
                        <span>${escapeHtml(item.orderNo || '系统消息')}</span>
                        <span>${escapeHtml(formatDate(item.createdAt, true))}</span>
                      </div>
                    </article>
                  `
                )
                .join('')
            : '<div class="empty-state">当前没有通知。</div>'
        }
      </div>
    </section>
  `;
}

function renderTimeline(order) {
  if (!order.timeline.length) {
    return '<div class="empty-state small">还没有时间线记录。</div>';
  }

  return `
    <div class="timeline">
      ${order.timeline
        .map(
          (item) => `
            <article class="timeline-item">
              <span class="timeline-dot"></span>
              <div>
                <strong>${escapeHtml(item.message)}</strong>
                <p>${escapeHtml(item.actorName)} · ${escapeHtml(formatDate(item.createdAt, true))}</p>
              </div>
            </article>
          `
        )
        .join('')}
    </div>
  `;
}

function renderVersionHistory(order) {
  if (!order.versionHistory?.length) {
    return '<div class="empty-state small">还没有版本记录。</div>';
  }

  return `
    <div class="version-stack">
      ${order.versionHistory
        .map(
          (version) => `
            <article class="version-card">
              <div class="version-header">
                <div>
                  <strong>V${escapeHtml(version.versionNumber)} · ${escapeHtml(version.eventLabel)}</strong>
                  <p>${escapeHtml(version.actorName)} · ${escapeHtml(
                    formatDate(version.createdAt, true)
                  )}</p>
                </div>
                ${
                  version.reason
                    ? `<span class="badge badge-muted">${escapeHtml(version.reason)}</span>`
                    : ''
                }
              </div>
              <div class="change-list">
                ${
                  version.changes?.length
                    ? version.changes
                        .map(
                          (change) => `
                            <div class="change-row">
                              <span>${escapeHtml(change.label)}</span>
                              <strong>${escapeHtml(change.before)} → ${escapeHtml(
                                change.after
                              )}</strong>
                            </div>
                          `
                        )
                        .join('')
                    : '<p class="subtle-copy">初始版本，无字段变更。</p>'
                }
              </div>
            </article>
          `
        )
        .join('')}
    </div>
  `;
}

function renderReworkHistory(order) {
  if (!order.reworkRequests?.length) {
    return '<div class="empty-state small">当前还没有返工片号记录。</div>';
  }

  return `
    <div class="rework-request-list">
      ${order.reworkRequests
        .map(
          (request) => `
            <article class="rework-request-card ${request.isAcknowledged ? 'is-acknowledged' : 'is-open'}">
              <div class="version-header">
                <div>
                  <strong>${escapeHtml(request.sourceStepLabel)} → 切玻璃</strong>
                  <p>${escapeHtml(request.actorName)} · ${escapeHtml(
                    formatDate(request.createdAt, true)
                  )}</p>
                </div>
                <span class="badge ${request.isAcknowledged ? 'badge-muted' : 'badge-danger'}">
                  ${escapeHtml(request.isAcknowledged ? '已读' : '待处理')}
                </span>
              </div>
              <div class="change-list">
                <div class="change-row">
                  <span>返工片号</span>
                  <strong>${escapeHtml(request.pieceSummary)}</strong>
                </div>
                ${
                  request.note
                    ? `<div class="change-row"><span>说明</span><strong>${escapeHtml(
                        request.note
                      )}</strong></div>`
                    : ''
                }
                ${
                  request.isAcknowledged && request.acknowledgedAt
                    ? `<div class="change-row"><span>已读时间</span><strong>${escapeHtml(
                        `${request.acknowledgedByName || '切玻璃工位'} · ${formatDate(
                          request.acknowledgedAt,
                          true
                        )}`
                      )}</strong></div>`
                    : ''
                }
              </div>
            </article>
          `
        )
        .join('')}
    </div>
  `;
}

function renderSettingsView() {
  const template = state.data.notificationTemplate;
  const glassTypes = state.data.glassTypeCatalog ?? [];

  return `
    <section class="panel split-panel settings-panel">
      <div class="settings-column">
        <div class="settings-block">
          <div class="panel-heading slim">
            <div>
              <p class="eyebrow">System Dictionary</p>
              <h2>玻璃类型字典</h2>
            </div>
            <button class="ghost-button" data-action="refresh-settings">刷新</button>
          </div>
          <form class="settings-inline-form" data-form="glass-type">
            <label>
              <span>新建类型</span>
              <input name="name" placeholder="例如 Bronze / Mirror" required />
            </label>
            <button class="primary-button compact" type="submit">新增类型</button>
          </form>
          <div class="list-stack compact-list">
            ${
              glassTypes.length
                ? glassTypes
                    .map(
                      (glassType) => `
                        <article class="glass-type-card ${glassType.isActive ? 'is-active' : 'is-inactive'}">
                          <div>
                            <strong>${escapeHtml(glassType.name)}</strong>
                            <p class="subtle-copy">${escapeHtml(
                              `${glassType.activeOrderCount} 进行中 / ${glassType.totalOrderCount} 总订单`
                            )}</p>
                          </div>
                          <div class="inline-actions">
                            <span class="badge ${glassType.isActive ? 'badge-muted' : 'badge-warning'}">${escapeHtml(
                              glassType.isActive ? '启用中' : '已停用'
                            )}</span>
                            <button
                              class="ghost-button compact"
                              type="button"
                              data-action="rename-glass-type"
                              data-glass-type-id="${escapeHtml(glassType.id)}"
                              data-glass-type-name="${escapeHtml(glassType.name)}"
                            >
                              重命名
                            </button>
                            <button
                              class="ghost-button compact"
                              type="button"
                              data-action="toggle-glass-type"
                              data-glass-type-id="${escapeHtml(glassType.id)}"
                              data-glass-type-name="${escapeHtml(glassType.name)}"
                              data-next-active="${glassType.isActive ? '0' : '1'}"
                            >
                              ${escapeHtml(glassType.isActive ? '停用' : '启用')}
                            </button>
                          </div>
                        </article>
                      `
                    )
                    .join('')
                : '<div class="empty-state">还没有玻璃类型字典数据。</div>'
            }
          </div>
        </div>

        <div class="settings-block">
          <div class="panel-heading slim">
            <div>
              <p class="eyebrow">Ready for Pickup</p>
              <h2>客户邮件模板</h2>
            </div>
          </div>
          ${
            template
              ? `
                <form class="stack-form" data-form="notification-template">
                  <label>
                    <span>标题模板</span>
                    <input name="subjectTemplate" value="${escapeHtml(template.subjectTemplate)}" required />
                  </label>
                  <label>
                    <span>正文模板</span>
                    <textarea name="bodyTemplate" rows="12" required>${escapeHtml(
                      template.bodyTemplate
                    )}</textarea>
                  </label>
                  <div class="template-variable-block">
                    <span>可用变量</span>
                    <div class="variable-cluster">
                      ${template.availableVariables
                        .map(
                          (variable) =>
                            `<span class="badge badge-muted">{{${escapeHtml(variable)}}}</span>`
                        )
                        .join('')}
                    </div>
                  </div>
                  <div class="meta-stack settings-meta">
                    <span>模板键 ${escapeHtml(template.templateKey)}</span>
                    <span>最近修改 ${escapeHtml(
                      template.updatedAt ? formatDate(template.updatedAt, true) : '默认模板'
                    )}</span>
                    <span>修改人 ${escapeHtml(template.updatedByName || '系统默认')}</span>
                  </div>
                  <div class="modal-actions">
                    <button class="primary-button" type="submit">保存模板</button>
                  </div>
                </form>
              `
              : '<div class="empty-state">正在加载模板…</div>'
          }
        </div>
      </div>

      <div class="settings-block">
        <div class="panel-heading slim">
          <div>
            <p class="eyebrow">Delivery Log</p>
            <h2>最近邮件记录</h2>
          </div>
        </div>
        <div class="list-stack compact-list">
          ${
            state.data.emailLogs.length
              ? state.data.emailLogs
                  .map(
                    (log) => `
                      <article class="email-log-card status-${escapeHtml(log.status)}">
                        <div>
                          <p class="kicker">${escapeHtml(log.customerEmail)}</p>
                          <h3>${escapeHtml(log.subject)}</h3>
                          <p class="email-log-body">${escapeHtml(log.body)}</p>
                        </div>
                        <div class="meta-stack">
                          <span>${escapeHtml(getEmailStatusLabel(log.status))}</span>
                          <span>${escapeHtml(log.orderNo || '无订单号')} · ${escapeHtml(
                            log.transport
                          )}</span>
                          <span>${escapeHtml(formatDate(log.createdAt, true))}</span>
                          ${
                            log.errorMessage
                              ? `<span class="error-copy">${escapeHtml(log.errorMessage)}</span>`
                              : ''
                          }
                        </div>
                      </article>
                    `
                  )
                  .join('')
              : '<div class="empty-state">还没有邮件发送记录。</div>'
          }
        </div>
      </div>
    </section>
  `;
}

function renderOrderFormModal() {
  const order = getCurrentModalOrder();
  const glassTypes = [...state.options.glassTypes];
  if (order?.glassType && !glassTypes.includes(order.glassType)) {
    glassTypes.unshift(order.glassType);
  }
  const selectedGlassType =
    order?.glassType || (glassTypes.includes('Clear') ? 'Clear' : glassTypes[0] || '');

  return `
    <div class="modal-card wide-modal">
      <header class="modal-header">
        <div>
          <p class="eyebrow">${order ? 'Edit Order' : 'New Order'}</p>
          <h2>${order ? `编辑 ${escapeHtml(order.orderNo)}` : '创建新订单'}</h2>
        </div>
        <button class="icon-button" data-action="close-modal" aria-label="关闭">×</button>
      </header>

      <form class="stack-form" data-form="order" data-order-id="${escapeHtml(order?.id || '')}">
        <div class="two-column-grid">
          <label>
            <span>客户</span>
            <select name="customerId" required>
              <option value="">请选择客户</option>
              ${state.data.customers
                .map(
                  (customer) => `
                    <option value="${escapeHtml(customer.id)}" ${
                      order?.customer.id === customer.id ? 'selected' : ''
                    }>${escapeHtml(customer.companyName)}</option>
                  `
                )
                .join('')}
            </select>
          </label>
          <label>
            <span>Priority</span>
            <select name="priority">
              ${state.options.priorities
                .map(
                  (priority) => `
                    <option value="${escapeHtml(priority.value)}" ${
                      (order?.priority || 'normal') === priority.value ? 'selected' : ''
                    }>${escapeHtml(priority.label)}</option>
                  `
                )
                .join('')}
            </select>
          </label>
          <label>
            <span>玻璃类型</span>
            <select name="glassType" required>
              <option value="" ${selectedGlassType ? '' : 'selected'}>请选择</option>
              ${glassTypes
                .map(
                  (glassType) => `
                    <option value="${escapeHtml(glassType)}" ${
                      selectedGlassType === glassType ? 'selected' : ''
                    }>${escapeHtml(glassType)}</option>
                  `
                )
                .join('')}
            </select>
          </label>
          <label>
            <span>厚度</span>
            <select name="thickness" required>
              <option value="">请选择</option>
              ${state.options.thicknessOptions
                .map(
                  (thickness) => `
                    <option value="${escapeHtml(thickness)}" ${
                      order?.thickness === thickness ? 'selected' : ''
                    }>${escapeHtml(thickness)}</option>
                  `
                )
                .join('')}
            </select>
          </label>
          <label>
            <span>数量</span>
            <input name="quantity" type="number" min="1" required value="${escapeHtml(
              order?.quantity || 1
            )}" />
          </label>
          <label>
            <span>预计完成日期</span>
            <input name="estimatedCompletionDate" type="date" value="${escapeHtml(
              formatDateInput(order?.estimatedCompletionDate)
            )}" />
          </label>
        </div>

        <label>
          <span>特殊说明</span>
          <textarea name="specialInstructions" rows="4" placeholder="例如：可选某片玻璃 HOLD，或 Rush 特别说明">${escapeHtml(
            order?.specialInstructions || ''
          )}</textarea>
        </label>

        <label>
          <span>图纸 PDF / 图片</span>
          <input name="drawing" type="file" accept="application/pdf,image/*" />
          ${
            order?.drawingUrl
              ? `<a class="file-link" href="${escapeHtml(order.drawingUrl)}" target="_blank" rel="noreferrer">当前图纸：${escapeHtml(
                  order.drawingName || '查看附件'
                )}</a>`
              : ''
          }
        </label>

        <div class="modal-actions">
          <button class="ghost-button" type="button" data-action="close-modal">取消</button>
          <button class="primary-button" type="submit">${order ? '保存修改' : '创建订单'}</button>
        </div>
      </form>
    </div>
  `;
}

function renderCustomerFormModal() {
  const customer = getCurrentModalCustomer();

  return `
    <div class="modal-card">
      <header class="modal-header">
        <div>
          <p class="eyebrow">${customer ? 'Edit Customer' : 'New Customer'}</p>
          <h2>${customer ? '编辑客户' : '新增客户'}</h2>
        </div>
        <button class="icon-button" data-action="close-modal" aria-label="关闭">×</button>
      </header>

      <form class="stack-form" data-form="customer" data-customer-id="${escapeHtml(customer?.id || '')}">
        <label>
          <span>公司名称</span>
          <input name="companyName" required value="${escapeHtml(customer?.companyName || '')}" />
        </label>
        <label>
          <span>联系人</span>
          <input name="contactName" value="${escapeHtml(customer?.contactName || '')}" />
        </label>
        <label>
          <span>电话</span>
          <input name="phone" value="${escapeHtml(customer?.phone || '')}" />
        </label>
        <label>
          <span>邮箱</span>
          <input name="email" type="email" value="${escapeHtml(customer?.email || '')}" />
        </label>
        <label>
          <span>备注</span>
          <textarea name="notes" rows="4">${escapeHtml(customer?.notes || '')}</textarea>
        </label>
        <div class="modal-actions">
          <button class="ghost-button" type="button" data-action="close-modal">取消</button>
          <button class="primary-button" type="submit">${customer ? '保存客户' : '创建客户'}</button>
        </div>
      </form>
    </div>
  `;
}

function renderOrderDetailModal() {
  const order = getCurrentModalOrder();
  if (!order) {
    return '';
  }

  const canEdit = canManageOrders() && !['shipping', 'delivered', 'picked_up', 'cancelled'].includes(order.status);
  const canCancel = canCancelOrders() && !['shipping', 'delivered', 'picked_up', 'cancelled'].includes(order.status) && order.canCancel;
  const canApprovePickup = canApprovePickupAction() && order.status === 'completed';
  const canSign = canUsePickup() && order.status === 'ready_for_pickup';
  const canExportPickup = ['ready_for_pickup', 'picked_up'].includes(order.status);
  const canSendPickupEmail = canUsePickup() && ['ready_for_pickup', 'picked_up'].includes(order.status);

  return `
    <div class="modal-card wide-modal">
      <header class="modal-header">
        <div>
          <p class="eyebrow">Order Detail</p>
          <h2>${escapeHtml(order.orderNo)}</h2>
        </div>
        <button class="icon-button" data-action="close-modal" aria-label="关闭">×</button>
      </header>

      <div class="badge-row detail-badges">${renderOrderBadges(order)}</div>

      <div class="detail-grid">
        <section>
          <h3>订单信息</h3>
          <dl class="detail-list">
            <div><dt>客户</dt><dd>${escapeHtml(order.customer.companyName)}</dd></div>
            <div><dt>联系人</dt><dd>${escapeHtml(order.customer.contactName || '未填写')}</dd></div>
            <div><dt>电话</dt><dd>${escapeHtml(order.customer.phone || '未填写')}</dd></div>
            <div><dt>状态</dt><dd>${escapeHtml(order.statusLabel)}</dd></div>
            <div><dt>玻璃</dt><dd>${escapeHtml(order.glassType)}</dd></div>
            <div><dt>厚度</dt><dd>${escapeHtml(order.thickness)}</dd></div>
            <div><dt>数量</dt><dd>${escapeHtml(order.quantity)} 片</dd></div>
            <div><dt>版本</dt><dd>V${escapeHtml(order.version)}</dd></div>
            <div><dt>创建时间</dt><dd>${escapeHtml(formatDate(order.createdAt, true))}</dd></div>
            <div><dt>最后更新</dt><dd>${escapeHtml(formatDate(order.updatedAt, true))}</dd></div>
          </dl>
          <p class="detail-note">${escapeHtml(order.specialInstructions || '无特殊说明。')}</p>
          ${
            order.openReworkPieceSummary
              ? `<p class="detail-note warning-note">待返工片号：${escapeHtml(
                  order.openReworkPieceSummary
                )}</p>`
              : ''
          }
          ${
            order.cancelledReason
              ? `<p class="detail-note warning-note">取消原因：${escapeHtml(order.cancelledReason)}</p>`
              : ''
          }
          ${
            order.drawingUrl
              ? `<a class="file-link" href="${escapeHtml(order.drawingUrl)}" target="_blank" rel="noreferrer">查看图纸：${escapeHtml(
                  order.drawingName || '打开附件'
                )}</a>`
              : '<p class="subtle-copy">当前未上传图纸文件。</p>'
          }
        </section>
        <section>
          <h3>工序进度</h3>
          <div class="progress-list">
            ${order.steps
              .map(
                (step) => `
                  <article class="progress-row ${escapeHtml(step.status)} ${
                    step.reworkUnread ? 'alert' : ''
                  }">
                    <div>
                      <strong>${escapeHtml(step.label)}</strong>
                      <span>${escapeHtml(step.statusLabel)}</span>
                    </div>
                    <div class="meta-stack">
                      <span>开始 ${escapeHtml(formatDate(step.startedAt, true))}</span>
                      <span>完成 ${escapeHtml(formatDate(step.completedAt, true))}</span>
                      ${
                        step.reworkCount
                          ? `<span>返工 ${escapeHtml(step.reworkCount)} 片</span>`
                          : ''
                      }
                      ${
                        step.reworkPieceSummary
                          ? `<span>片号 ${escapeHtml(step.reworkPieceSummary)}</span>`
                          : ''
                      }
                    </div>
                  </article>
                `
              )
              .join('')}
          </div>
        </section>
      </div>

      <section class="timeline-section">
        <h3>返工片号记录</h3>
        ${renderReworkHistory(order)}
      </section>

      <section class="timeline-section">
        <h3>版本记录</h3>
        ${renderVersionHistory(order)}
      </section>

      <section class="timeline-section">
        <h3>时间线</h3>
        ${renderTimeline(order)}
      </section>

      <div class="modal-actions">
        ${
          canEdit
            ? `<button class="ghost-button" data-action="open-order-form" data-order-id="${escapeHtml(
                order.id
              )}">编辑订单</button>`
            : ''
        }
        ${
          canCancel
            ? `<button class="ghost-button danger-button" data-action="cancel-order" data-order-id="${escapeHtml(
                order.id
              )}">${escapeHtml(order.canCancelLabel || '取消订单')}</button>`
            : ''
        }
        ${
          canApprovePickup
            ? `<button class="primary-button compact" data-action="approve-pickup" data-order-id="${escapeHtml(
                order.id
              )}">批准 Pickup</button>`
            : ''
        }
        ${
          canSign
            ? `<button class="primary-button compact" data-action="open-signature" data-order-id="${escapeHtml(
                order.id
              )}">签字提货</button>`
            : ''
        }
        <button class="ghost-button" data-action="export-order-pdf" data-order-id="${escapeHtml(
          order.id
        )}">订单 PDF</button>
        ${
          canExportPickup
            ? `<button class="ghost-button" data-action="export-pickup-pdf" data-order-id="${escapeHtml(
                order.id
              )}">Pickup PDF</button>`
            : ''
        }
        ${
          canSendPickupEmail
            ? `<button class="ghost-button" data-action="send-pickup-email" data-order-id="${escapeHtml(
                order.id
              )}">发送取货邮件</button>`
            : ''
        }
      </div>
    </div>
  `;
}

function renderSignatureModal() {
  const order = getCurrentModalOrder();
  if (!order) {
    return '';
  }

  return `
    <div class="modal-card wide-modal">
      <header class="modal-header">
        <div>
          <p class="eyebrow">Pickup Signature</p>
          <h2>${escapeHtml(order.orderNo)} 签字提货</h2>
        </div>
        <button class="icon-button" data-action="close-modal" aria-label="关闭">×</button>
      </header>

      <div class="signature-layout">
        <div>
          <p class="subtle-copy">
            只有主管批准后才能打开签字页。客户签名保存后，订单会自动变成“已取货”。
          </p>
          <dl class="detail-list compact-detail-list">
            <div><dt>客户</dt><dd>${escapeHtml(order.customer.companyName)}</dd></div>
            <div><dt>状态</dt><dd>${escapeHtml(order.statusLabel)}</dd></div>
            <div><dt>批准时间</dt><dd>${escapeHtml(formatDate(order.pickupApprovedAt, true))}</dd></div>
          </dl>
        </div>
        <form class="stack-form" data-form="signature" data-order-id="${escapeHtml(order.id)}">
          <label>
            <span>取货人姓名</span>
            <input name="signerName" placeholder="请输入现场签字人姓名" required />
          </label>
          <div class="signature-box">
            <canvas id="signature-canvas"></canvas>
          </div>
          <div class="modal-actions left-actions">
            <button class="ghost-button" type="button" data-action="clear-signature">清空签名</button>
            <button class="primary-button" type="submit">保存签字并完成取货</button>
          </div>
        </form>
      </div>
    </div>
  `;
}

function renderReworkModal() {
  const order = getCurrentModalOrder();
  if (!order) {
    return '';
  }

  const step = order.steps.find((candidate) => candidate.key === state.ui.modal?.stepKey);
  const blockedPieces = new Set(
    (order.reworkRequests || [])
      .filter((request) => !request.isAcknowledged)
      .flatMap((request) => request.pieceNumbers)
  );
  const pieceOptions = Array.from({ length: order.quantity }, (_item, index) => index + 1);

  return `
    <div class="modal-card wide-modal">
      <header class="modal-header">
        <div>
          <p class="eyebrow">Piece-level Rework</p>
          <h2>${escapeHtml(order.orderNo)} · ${escapeHtml(step?.label || '返工')}</h2>
        </div>
        <button class="icon-button" data-action="close-modal" aria-label="关闭">×</button>
      </header>

      <form class="stack-form" data-form="rework" data-order-id="${escapeHtml(
        order.id
      )}" data-step-key="${escapeHtml(state.ui.modal?.stepKey || '')}">
        <p class="subtle-copy">
          请选择需要回推切玻璃工位的具体片号。已在返工队列中的片号会禁用，避免重复推送。
        </p>

        ${
          order.openReworkPieceSummary
            ? `<p class="warning-note">当前待处理返工：${escapeHtml(order.openReworkPieceSummary)}</p>`
            : ''
        }

        <div class="piece-grid">
          ${pieceOptions
            .map((pieceNumber) => {
              const isBlocked = blockedPieces.has(pieceNumber);
              return `
                <label class="piece-chip ${isBlocked ? 'is-disabled' : ''}">
                  <input
                    type="checkbox"
                    name="pieceNumber"
                    value="${pieceNumber}"
                    ${isBlocked ? 'disabled' : ''}
                  />
                  <span>${escapeHtml(`第 ${pieceNumber} 片`)}</span>
                </label>
              `;
            })
            .join('')}
        </div>

        <label>
          <span>返工说明</span>
          <textarea name="note" rows="4" placeholder="例如：第 3 片边角崩裂，需要重新切玻璃"></textarea>
        </label>

        <div class="modal-actions">
          <button class="ghost-button" type="button" data-action="close-modal">取消</button>
          <button class="primary-button" type="submit">回推返工</button>
        </div>
      </form>
    </div>
  `;
}

function renderModal() {
  if (!state.ui.modal) {
    return '';
  }

  let content = '';
  switch (state.ui.modal.type) {
    case 'order-form':
      content = renderOrderFormModal();
      break;
    case 'customer-form':
      content = renderCustomerFormModal();
      break;
    case 'order-detail':
      content = renderOrderDetailModal();
      break;
    case 'signature':
      content = renderSignatureModal();
      break;
    case 'rework':
      content = renderReworkModal();
      break;
    default:
      content = '';
  }

  if (!content) {
    return '';
  }

  return `
    <div class="modal-overlay">
      ${content}
    </div>
  `;
}

function renderActiveTab() {
  switch (state.ui.activeTab) {
    case 'dashboard':
      return renderDashboardView();
    case 'customers':
      return renderCustomersView();
    case 'orders':
      return renderOrdersView();
    case 'production':
      return renderProductionView();
    case 'pickup':
      return renderPickupView();
    case 'notifications':
      return renderNotificationsView();
    case 'settings':
      return renderSettingsView();
    default:
      return renderDashboardView();
  }
}

function renderShell() {
  ensureActiveTab();

  appRoot.innerHTML = `
    <div class="shell">
      <header class="topbar">
        <div>
          <p class="eyebrow">Glass Factory Flow</p>
          <h1>${escapeHtml(getWorkspaceTitle())} Workspace</h1>
          <p class="lead-mini">${escapeHtml(state.user.name)} · ${escapeHtml(
            state.user.stageLabel || '全局视角'
          )}</p>
        </div>
        <div class="topbar-actions">
          ${renderLocaleSwitch()}
          <button class="ghost-button" data-action="refresh-data">刷新</button>
          <button class="ghost-button" data-action="logout">退出</button>
        </div>
      </header>

      ${renderFlash()}

      <nav class="tabbar">
        ${getTabs()
          .map(
            (tab) => `
              <button class="tab ${state.ui.activeTab === tab ? 'is-active' : ''}" data-action="switch-tab" data-tab="${escapeHtml(
                tab
              )}">
                ${escapeHtml(TAB_LABELS[tab])}
              </button>
            `
          )
          .join('')}
      </nav>

      <main class="content-stack">
        ${renderActiveTab()}
      </main>
    </div>
    ${renderModal()}
  `;

  document.body.classList.toggle('modal-open', Boolean(state.ui.modal));
  if (state.ui.modal?.type === 'signature') {
    setupSignaturePad();
  } else {
    signaturePad = null;
  }
}

function renderLoading() {
  appRoot.innerHTML = `
    <section class="auth-shell compact-loading">
      <div class="auth-panel loading-panel">
        <div class="spinner"></div>
        <h2>正在载入工厂流程台…</h2>
      </div>
    </section>
  `;
}

function render() {
  if (!appRoot) {
    return;
  }

  syncDocumentLocale();

  if (state.token && !state.user) {
    renderLoading();
    applyLocaleToTree(appRoot);
    return;
  }

  if (!state.token || !state.user) {
    renderLogin();
    applyLocaleToTree(appRoot);
    return;
  }

  renderShell();
  applyLocaleToTree(appRoot);
}

async function api(path, options = {}) {
  const method = String(options.method || 'GET').toUpperCase();
  const config = {
    method,
    headers: {},
  };

  if (options.headers && typeof options.headers === 'object') {
    Object.assign(config.headers, options.headers);
  }

  if (state.token) {
    config.headers.Authorization = `Bearer ${state.token}`;
  }

  if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && !config.headers['Idempotency-Key']) {
    const fallbackKey = `idem-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    config.headers['Idempotency-Key'] =
      options.idempotencyKey || (globalThis.crypto?.randomUUID?.() ?? fallbackKey);
  }

  if (options.body instanceof FormData) {
    config.body = options.body;
  } else if (options.body) {
    config.headers['Content-Type'] = 'application/json';
    config.body = JSON.stringify(options.body);
  }

  const response = await fetch(path, config);
  const rawPayload = await response.json().catch(() => ({}));
  const payload = unwrapApiPayload(rawPayload);

  if (
    response.status === 401 &&
    !options.skipAuthRefresh &&
    state.refreshToken &&
    path !== `${WORKSPACE_API_PREFIX}/auth/login` &&
    path !== '/v1/auth/refresh'
  ) {
    try {
      await requestAccessTokenRefresh();
      return api(path, { ...options, skipAuthRefresh: true });
    } catch (error) {
      if (shouldResetSession(error)) {
        resetSession();
      }
      throw error;
    }
  }

  if (!response.ok) {
    throw buildApiError(response, rawPayload);
  }

  return payload;
}

function resetSession() {
  state.token = null;
  state.refreshToken = null;
  state.user = null;
  localStorage.removeItem(STORAGE_KEY);
  localStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY);
  state.ui.modal = null;
  state.data.orderDetails = {};
  state.data.glassTypeCatalog = [];
  state.data.notificationTemplate = null;
  state.data.emailLogs = [];
}

function mergeBootstrapData(payloadData) {
  const existingOrderDetails = state.data.orderDetails ?? {};
  const knownOrderIds = new Set((payloadData.orders || []).map((order) => order.id));

  return {
    ...payloadData,
    orderDetails: Object.fromEntries(
      Object.entries(existingOrderDetails).filter(([orderId]) => knownOrderIds.has(orderId))
    ),
    glassTypeCatalog: state.data.glassTypeCatalog ?? [],
    notificationTemplate: state.data.notificationTemplate ?? null,
    emailLogs: state.data.emailLogs ?? [],
  };
}

async function refreshData({ silent = false } = {}) {
  const payload = await api(`${WORKSPACE_API_PREFIX}/bootstrap`);
  state.user = normalizeUser(payload.user);
  state.options = payload.options;
  state.data = mergeBootstrapData(payload.data);
  ensureActiveTab();
  if (!silent) {
    render();
  }
}

async function loadOrderDetail(orderId) {
  const payload = await api(`${WORKSPACE_API_PREFIX}/orders/${orderId}`);
  state.data.orderDetails = {
    ...(state.data.orderDetails ?? {}),
    [orderId]: payload.order,
  };
  return payload.order;
}

async function loadSettingsData() {
  const [glassTypesPayload, templatePayload, logsPayload] = await Promise.all([
    api(`${WORKSPACE_API_PREFIX}/settings/glass-types`),
    api(`${WORKSPACE_API_PREFIX}/settings/notification-templates/${PICKUP_TEMPLATE_KEY}`),
    api(`${WORKSPACE_API_PREFIX}/email-logs?limit=20`),
  ]);

  state.data.glassTypeCatalog = glassTypesPayload.glassTypes;
  state.data.notificationTemplate = templatePayload.template;
  state.data.emailLogs = logsPayload.logs;

  return {
    glassTypes: glassTypesPayload.glassTypes,
    template: templatePayload.template,
    logs: logsPayload.logs,
  };
}

async function mutate(task, successMessage, { closeModal = false } = {}) {
  try {
    const result = await task();
    if (closeModal) {
      state.ui.modal = null;
    }
    await refreshData({ silent: true });
    if (!closeModal && state.ui.modal?.orderId) {
      await loadOrderDetail(state.ui.modal.orderId);
    }
    if (state.ui.activeTab === 'settings' || state.data.notificationTemplate) {
      await loadSettingsData();
    }
    const resolvedMessage =
      typeof successMessage === 'function' ? successMessage(result) : successMessage;
    state.ui.flash = resolvedMessage
      ? { type: 'success', message: localizeText(resolvedMessage) }
      : null;
    render();
    return result;
  } catch (error) {
    setFlash('error', error.message);
    return null;
  }
}

async function downloadPdf(orderId, documentType) {
  const response = await fetch(`${WORKSPACE_API_PREFIX}/orders/${orderId}/export?document=${encodeURIComponent(documentType)}`, {
    headers: state.token
      ? {
          Authorization: `Bearer ${state.token}`,
        }
      : {},
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload?.error?.message || payload?.error || payload?.detail || 'PDF 导出失败。');
  }

  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const order = getOrderById(orderId);
  const anchor = document.createElement('a');
  anchor.href = objectUrl;
  anchor.download = `${order?.orderNo || 'order'}-${documentType}.pdf`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
}

function setupSignaturePad() {
  const canvas = document.querySelector('#signature-canvas');
  if (!canvas) {
    signaturePad = null;
    return;
  }

  const context = canvas.getContext('2d');
  let drawing = false;
  let hasStroke = false;

  const resize = () => {
    const rect = canvas.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    canvas.width = rect.width * ratio;
    canvas.height = rect.height * ratio;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.lineCap = 'round';
    context.lineJoin = 'round';
    context.strokeStyle = '#102a43';
    context.lineWidth = 2.4;
  };

  const pointFromEvent = (event) => {
    const rect = canvas.getBoundingClientRect();
    return {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    };
  };

  const begin = (event) => {
    drawing = true;
    hasStroke = true;
    const point = pointFromEvent(event);
    context.beginPath();
    context.moveTo(point.x, point.y);
  };

  const move = (event) => {
    if (!drawing) {
      return;
    }
    const point = pointFromEvent(event);
    context.lineTo(point.x, point.y);
    context.stroke();
  };

  const end = () => {
    drawing = false;
  };

  resize();
  canvas.addEventListener('pointerdown', begin);
  canvas.addEventListener('pointermove', move);
  canvas.addEventListener('pointerup', end);
  canvas.addEventListener('pointerleave', end);

  signaturePad = {
    clear() {
      context.clearRect(0, 0, canvas.width, canvas.height);
      hasStroke = false;
    },
    isEmpty() {
      return !hasStroke;
    },
    toDataUrl() {
      return canvas.toDataURL('image/png');
    },
  };
}

async function handleClick(event) {
  const trigger = event.target.closest('[data-action]');
  if (!trigger) {
    return;
  }

  const {
    action,
    customerId,
    email,
    glassTypeId,
    glassTypeName,
    locale,
    nextActive,
    orderId,
    password,
    stepKey,
    tab,
  } = trigger.dataset;

  switch (action) {
    case 'switch-locale':
      state.ui.locale = locale || 'zh-CN';
      localStorage.setItem(LOCALE_KEY, state.ui.locale);
      render();
      break;
    case 'switch-tab':
      state.ui.activeTab = tab;
      if (tab === 'settings' && state.user && canOpenSettings()) {
        try {
          await loadSettingsData();
        } catch (error) {
          setFlash('error', error.message);
          return;
        }
      }
      render();
      break;
    case 'logout':
      resetSession();
      render();
      break;
    case 'clear-flash':
      clearFlash();
      break;
    case 'open-order-form':
      if (orderId) {
        try {
          await loadOrderDetail(orderId);
        } catch (error) {
          setFlash('error', error.message);
          return;
        }
      }
      state.ui.modal = { type: 'order-form', orderId: orderId || null };
      render();
      break;
    case 'open-customer-form':
      state.ui.modal = { type: 'customer-form', customerId: customerId || null };
      render();
      break;
    case 'open-order-detail':
      try {
        await loadOrderDetail(orderId);
      } catch (error) {
        setFlash('error', error.message);
        return;
      }
      state.ui.modal = { type: 'order-detail', orderId };
      render();
      break;
    case 'open-signature':
      try {
        await loadOrderDetail(orderId);
      } catch (error) {
        setFlash('error', error.message);
        return;
      }
      state.ui.modal = { type: 'signature', orderId };
      render();
      break;
    case 'close-modal':
      state.ui.modal = null;
      render();
      break;
    case 'use-demo': {
      const emailInput = document.querySelector('input[name="email"]');
      const passwordInput = document.querySelector('input[name="password"]');
      if (emailInput && passwordInput) {
        emailInput.value = email;
        passwordInput.value = password;
      }
      break;
    }
    case 'refresh-data':
      mutate(() => refreshData({ silent: true }), '数据已刷新。');
      break;
    case 'refresh-settings':
      mutate(() => loadSettingsData(), '邮件模板和记录已刷新。');
      break;
    case 'rename-glass-type': {
      const nextName = window.prompt(localizeText('请输入新的玻璃类型名称：'), glassTypeName || '');
      if (nextName === null) {
        return;
      }
      mutate(
        () =>
          api(`${WORKSPACE_API_PREFIX}/settings/glass-types/${glassTypeId}`, {
            method: 'PATCH',
            body: { name: nextName },
          }),
        '玻璃类型已更新。'
      );
      break;
    }
    case 'toggle-glass-type': {
      const shouldActivate = nextActive === '1';
      const question = shouldActivate
        ? `确认启用玻璃类型 ${glassTypeName || ''}？`
        : `确认停用玻璃类型 ${glassTypeName || ''}？`;
      if (!window.confirm(localizeText(question))) {
        return;
      }
      mutate(
        () =>
          api(`${WORKSPACE_API_PREFIX}/settings/glass-types/${glassTypeId}`, {
            method: 'PATCH',
            body: { isActive: shouldActivate },
          }),
        shouldActivate ? '玻璃类型已启用。' : '玻璃类型已停用。'
      );
      break;
    }
    case 'mark-entered':
      if (!window.confirm(localizeText('确认将该订单标记为“已录入系统”并推送给切玻璃工位？'))) {
        return;
      }
      mutate(
        () => api(`${WORKSPACE_API_PREFIX}/orders/${orderId}/entered`, { method: 'POST' }),
        '订单已推送到切玻璃工位。'
      );
      break;
    case 'approve-pickup':
      if (!window.confirm(localizeText('确认批准该订单进入 Pickup 签字流程？'))) {
        return;
      }
      mutate(
        () => api(`${WORKSPACE_API_PREFIX}/orders/${orderId}/pickup/approve`, { method: 'POST' }),
        (payload) => buildEmailResultMessage('Pickup 已批准。', payload?.emailLog)
      );
      break;
    case 'cancel-order': {
      const order = getOrderById(orderId);
      const actionLabel = order?.canCancelLabel || '取消订单';
      const reason = window.prompt(localizeText(`${actionLabel}原因（可选）：`), '');
      if (reason === null) {
        return;
      }
      if (!window.confirm(localizeText(`确认${actionLabel} ${order?.orderNo || ''}？`))) {
        return;
      }
      mutate(
        () =>
          api(`${WORKSPACE_API_PREFIX}/orders/${orderId}/cancel`, {
            method: 'POST',
            body: { reason },
          }),
        `${actionLabel}已完成。`
      );
      break;
    }
    case 'start-step':
      mutate(
        () =>
          api(`${WORKSPACE_API_PREFIX}/orders/${orderId}/steps/${stepKey}`, {
            method: 'POST',
            body: { action: 'start' },
          }),
        '工序已开始。'
      );
      break;
    case 'complete-step':
      mutate(
        () =>
          api(`${WORKSPACE_API_PREFIX}/orders/${orderId}/steps/${stepKey}`, {
            method: 'POST',
            body: { action: 'complete' },
          }),
        '工序已完成。'
      );
      break;
    case 'ack-rework':
      mutate(
        () =>
          api(`${WORKSPACE_API_PREFIX}/orders/${orderId}/steps/cutting`, {
            method: 'POST',
            body: { action: 'acknowledge_rework' },
          }),
        '返工提醒已标记已读。'
      );
      break;
    case 'report-rework': {
      try {
        await loadOrderDetail(orderId);
      } catch (error) {
        setFlash('error', error.message);
        return;
      }
      state.ui.modal = { type: 'rework', orderId, stepKey };
      render();
      break;
    }
    case 'mark-notifications-read':
      mutate(
        () => api(`${WORKSPACE_API_PREFIX}/notifications/read`, { method: 'POST' }),
        '通知已全部标记为已读。'
      );
      break;
    case 'export-order-pdf':
      try {
        await downloadPdf(orderId, 'order');
        setFlash('success', '订单 PDF 已开始下载。');
      } catch (error) {
        setFlash('error', error.message);
      }
      break;
    case 'export-pickup-pdf':
    case 'print-slip':
      try {
        await downloadPdf(orderId, 'pickup');
        setFlash('success', 'Pickup PDF 已开始下载。');
      } catch (error) {
        setFlash('error', error.message);
      }
      break;
    case 'send-pickup-email':
      mutate(
        () => api(`${WORKSPACE_API_PREFIX}/orders/${orderId}/pickup/send-email`, { method: 'POST' }),
        (payload) => buildEmailResultMessage('取货邮件已处理。', payload?.emailLog)
      );
      break;
    case 'clear-signature':
      signaturePad?.clear();
      break;
    default:
      break;
  }
}

async function handleSubmit(event) {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) {
    return;
  }

  const formType = form.dataset.form;
  if (!formType) {
    return;
  }

  event.preventDefault();

  try {
    switch (formType) {
      case 'login': {
        const formData = new FormData(form);
        const payload = await api(`${WORKSPACE_API_PREFIX}/auth/login`, {
          method: 'POST',
          body: {
            email: formData.get('email'),
            password: formData.get('password'),
          },
        });

        const nextUser = normalizeUser(payload?.user);
        persistSession(payload);
        if (nextUser.homePath === '/app') {
          window.location.assign('/app');
          return;
        }
        await refreshData({ silent: true });
        state.ui.flash = { type: 'success', message: localizeText('登录成功。') };
        render();
        break;
      }
      case 'customer': {
        const formData = new FormData(form);
        const body = Object.fromEntries(formData.entries());
        const customerId = form.dataset.customerId;
        await mutate(
          () =>
            api(customerId ? `${WORKSPACE_API_PREFIX}/customers/${customerId}` : `${WORKSPACE_API_PREFIX}/customers`, {
              method: customerId ? 'PATCH' : 'POST',
              body,
            }),
          customerId ? '客户信息已更新。' : '客户已创建。',
          { closeModal: true }
        );
        break;
      }
      case 'order': {
        const formData = new FormData(form);
        const orderId = form.dataset.orderId;
        await mutate(
          () =>
            api(orderId ? `${WORKSPACE_API_PREFIX}/orders/${orderId}` : `${WORKSPACE_API_PREFIX}/orders`, {
              method: orderId ? 'PUT' : 'POST',
              body: formData,
            }),
          orderId ? '订单已修改。' : '订单已创建。',
          { closeModal: true }
        );
        break;
      }
      case 'signature': {
        if (!signaturePad || signaturePad.isEmpty()) {
          throw new Error('请先完成电子签字。');
        }
        const formData = new FormData(form);
        const orderId = form.dataset.orderId;
        await mutate(
          () =>
            api(`${WORKSPACE_API_PREFIX}/orders/${orderId}/pickup/signature`, {
              method: 'POST',
              body: {
                signerName: formData.get('signerName'),
                signatureDataUrl: signaturePad.toDataUrl(),
              },
            }),
          '电子签字已保存，订单已完成取货。',
          { closeModal: true }
        );
        break;
      }
      case 'rework': {
        const formData = new FormData(form);
        const orderId = form.dataset.orderId;
        const stepKey = form.dataset.stepKey;
        const pieceNumbers = formData
          .getAll('pieceNumber')
          .map((pieceNumber) => Number.parseInt(pieceNumber, 10))
          .filter((pieceNumber) => Number.isInteger(pieceNumber) && pieceNumber > 0);

        if (!pieceNumbers.length) {
          throw new Error('请至少选择一片需要返工的玻璃。');
        }

        await mutate(
          () =>
            api(`${WORKSPACE_API_PREFIX}/orders/${orderId}/steps/${stepKey}`, {
              method: 'POST',
              body: {
                action: 'rework',
                pieceNumbers,
                note: String(formData.get('note') || ''),
              },
            }),
          `返工片号 ${formatPieceNumbers(pieceNumbers)} 已回推到切玻璃工位。`,
          { closeModal: true }
        );
        break;
      }
      case 'glass-type': {
        const formData = new FormData(form);
        const result = await mutate(
          () =>
            api(`${WORKSPACE_API_PREFIX}/settings/glass-types`, {
              method: 'POST',
              body: {
                name: String(formData.get('name') || ''),
              },
            }),
          '玻璃类型已新增。'
        );
        if (result) {
          form.reset();
        }
        break;
      }
      case 'notification-template': {
        const formData = new FormData(form);
        await mutate(
          () =>
            api(`${WORKSPACE_API_PREFIX}/settings/notification-templates/${PICKUP_TEMPLATE_KEY}`, {
              method: 'PUT',
              body: {
                subjectTemplate: String(formData.get('subjectTemplate') || ''),
                bodyTemplate: String(formData.get('bodyTemplate') || ''),
              },
            }),
          'Ready for Pickup 邮件模板已更新。'
        );
        break;
      }
      case 'order-filters': {
        const formData = new FormData(form);
        state.ui.orderFilters = {
          query: String(formData.get('query') || ''),
          status: String(formData.get('status') || 'all'),
          priority: String(formData.get('priority') || 'all'),
        };
        render();
        break;
      }
      case 'pickup-filters': {
        const formData = new FormData(form);
        state.ui.pickupFilters = {
          query: String(formData.get('query') || ''),
        };
        render();
        break;
      }
      default:
        break;
    }
  } catch (error) {
    if (String(error.message || '').includes('登录已失效')) {
      resetSession();
      render();
      return;
    }
    setFlash('error', error.message);
  }
}

function handleChange(event) {
  const field = event.target.dataset.field;
  if (!field) {
    return;
  }

  switch (field) {
    case 'customer-group':
      state.ui.customerGroup = event.target.value;
      render();
      break;
    case 'worker-group':
      state.ui.workerGroup = event.target.value;
      render();
      break;
    default:
      break;
  }
}

async function bootstrap() {
  render();

  if (!state.token) {
    return;
  }

  try {
    await refreshData({ silent: true });
    render();
  } catch (error) {
    if (error?.status === 403) {
      window.location.assign('/app');
      return;
    }
    if (shouldResetSession(error)) {
      resetSession();
    }
    render();
  }
}

function activateWaitingServiceWorker(registration) {
  if (registration.waiting) {
    registration.waiting.postMessage({ type: 'SKIP_WAITING' });
  }
}

function registerServiceWorker() {
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker
      .register('/sw.js', { updateViaCache: 'none' })
      .then((registration) => {
        activateWaitingServiceWorker(registration);
        registration.update().catch(() => {});
        registration.addEventListener('updatefound', () => {
          const installingWorker = registration.installing;
          if (!installingWorker) {
            return;
          }

          installingWorker.addEventListener('statechange', () => {
            if (installingWorker.state === 'installed') {
              activateWaitingServiceWorker(registration);
            }
          });
        });
      })
      .catch(() => {});
  }
}

function setupPolling() {
  window.setInterval(() => {
    if (!state.token) {
      return;
    }

    refreshData({ silent: true })
      .then(() => render())
      .catch((error) => {
        if (shouldResetSession(error)) {
          resetSession();
          render();
        }
      });
  }, 45000);

  window.addEventListener('focus', () => {
    if (!state.token) {
      return;
    }

    refreshData({ silent: true })
      .then(() => render())
      .catch((error) => {
        if (shouldResetSession(error)) {
          resetSession();
          render();
        }
      });
  });
}

document.addEventListener('DOMContentLoaded', () => {
  appRoot = document.querySelector('#app');
  document.addEventListener('click', handleClick);
  document.addEventListener('submit', handleSubmit);
  document.addEventListener('change', handleChange);
  registerServiceWorker();
  setupPolling();
  bootstrap();
});