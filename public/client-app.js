const TOKEN_KEY = 'glass-factory-token';
const REFRESH_TOKEN_KEY = 'glass-factory-refresh-token';
const APP_API_PREFIX = '/v1/app';
const LOGIN_API = '/v1/workspace/auth/login';

const state = {
  token: localStorage.getItem(TOKEN_KEY),
  refreshToken: localStorage.getItem(REFRESH_TOKEN_KEY),
  user: null,
  options: {
    glassTypes: [],
    thicknessOptions: [],
    priorities: [],
  },
  data: {
    summary: {},
    profile: null,
    credit: null,
    orders: [],
    orderDetails: {},
    notifications: [],
  },
  ui: {
    activeTab: 'dashboard',
    flash: null,
    modal: null,
  },
};

let root;
let refreshRequest = null;

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
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    ...(withTime
      ? {
          hour: '2-digit',
          minute: '2-digit',
        }
      : {}),
  }).format(date);
}

function formatMoney(value) {
  const amount = Number(value || 0);
  return Number.isFinite(amount) ? amount.toFixed(2) : '0.00';
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

function resolveShellForRole(role) {
  if (['customer', 'customer_viewer'].includes(String(role || '').toLowerCase())) {
    return '/app';
  }
  if (['admin', 'manager'].includes(String(role || '').toLowerCase())) {
    return '/admin';
  }
  return '/platform';
}

function resolveHomePathForUser(user) {
  return user?.homePath || resolveShellForRole(user?.role);
}

function normalizeUser(user) {
  const role = String(user?.role || '').toLowerCase();
  return {
    id: user?.id,
    name: user?.name || user?.display_name || user?.displayName || user?.username || '',
    email: user?.email || '',
    role,
    customerId: user?.customerId || user?.customer_id || null,
    homePath: user?.homePath || resolveShellForRole(role),
    shell: user?.shell || (user?.homePath === '/admin' ? 'admin' : user?.homePath === '/app' ? 'app' : 'platform'),
    canCreateOrders:
      user?.canCreateOrders !== undefined ? Boolean(user.canCreateOrders) : role === 'customer',
  };
}

function canCreateOrders() {
  return Boolean(state.user?.canCreateOrders);
}

function getAccessLevelLabel() {
  return canCreateOrders() ? '客户写权限' : '客户只读';
}

function renderCreateOrderAction({ label = '在线下单', compact = false } = {}) {
  if (!canCreateOrders()) {
    return '<span class="subtle-copy">当前账号为只读访客，仅可查看订单、通知与信用信息。</span>';
  }
  return `<button class="${compact ? 'primary-button compact' : 'primary-button'}" data-action="open-order-form">${escapeHtml(label)}</button>`;
}

function persistSession(payload) {
  const accessToken = payload?.token || payload?.access_token || null;
  const refreshToken = payload?.refreshToken || payload?.refresh_token || null;
  if (accessToken) {
    state.token = accessToken;
    localStorage.setItem(TOKEN_KEY, accessToken);
  }
  if (refreshToken) {
    state.refreshToken = refreshToken;
    localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
  }
  if (payload?.user) {
    state.user = normalizeUser(payload.user);
  }
}

function resetSession() {
  state.token = null;
  state.refreshToken = null;
  state.user = null;
  state.data.orderDetails = {};
  state.ui.modal = null;
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
}

async function requestAccessTokenRefresh() {
  if (!state.refreshToken) {
    throw new Error('Refresh token is unavailable.');
  }
  if (refreshRequest) {
    return refreshRequest;
  }

  refreshRequest = fetch('/v1/auth/refresh', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Idempotency-Key': globalThis.crypto?.randomUUID?.() ?? `idem-${Date.now()}`,
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
      refreshRequest = null;
    });

  return refreshRequest;
}

async function api(path, options = {}) {
  const method = String(options.method || 'GET').toUpperCase();
  const config = { method, headers: {} };

  if (state.token) {
    config.headers.Authorization = `Bearer ${state.token}`;
  }
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    config.headers['Idempotency-Key'] =
      options.idempotencyKey || globalThis.crypto?.randomUUID?.() || `idem-${Date.now()}`;
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
    path !== LOGIN_API &&
    path !== '/v1/auth/refresh'
  ) {
    await requestAccessTokenRefresh();
    return api(path, { ...options, skipAuthRefresh: true });
  }

  if (!response.ok) {
    throw buildApiError(response, rawPayload);
  }

  return payload;
}

function setFlash(type, message) {
  state.ui.flash = { type, message };
  render();
}

function getOrder(orderId) {
  return state.data.orderDetails[orderId] || state.data.orders.find((order) => order.id === orderId) || null;
}

function ensureCustomerShell(user) {
  const role = String(user?.role || '').toLowerCase();
  if (!['customer', 'customer_viewer'].includes(role)) {
    window.location.assign(resolveHomePathForUser(user));
    return false;
  }
  return true;
}

async function refreshData({ silent = false } = {}) {
  const payload = await api(`${APP_API_PREFIX}/bootstrap`);
  if (!ensureCustomerShell(payload.user)) {
    return;
  }
  state.user = normalizeUser(payload.user);
  state.options = payload.options;
  state.data.summary = payload.data.summary;
  state.data.profile = payload.data.profile;
  state.data.credit = payload.data.credit;
  state.data.orders = payload.data.orders;
  state.data.notifications = payload.data.notifications;
  if (!silent) {
    render();
  }
}

async function loadOrderDetail(orderId) {
  const payload = await api(`${APP_API_PREFIX}/orders/${orderId}`);
  state.data.orderDetails[orderId] = payload.order;
  return payload.order;
}

function renderFlash() {
  if (!state.ui.flash) {
    return '';
  }
  return `
    <div class="flash flash-${escapeHtml(state.ui.flash.type)}">
      <span>${escapeHtml(state.ui.flash.message)}</span>
      <button class="icon-button" data-action="dismiss-flash" aria-label="关闭">×</button>
    </div>
  `;
}

function renderLogin() {
  root.innerHTML = `
    <section class="auth-shell">
      <div class="auth-panel">
        <p class="eyebrow">Customer Portal</p>
        <h1>登录客户端</h1>
        <p class="lead-copy">在线下单、查看进度、跟踪取货与信用余额。</p>

        <form class="stack-form" data-form="login">
          <label>
            <span>邮箱</span>
            <input name="email" type="email" placeholder="customer@glass.local" required />
          </label>
          <label>
            <span>密码</span>
            <input name="password" type="password" placeholder="customer123" required />
          </label>
          <button class="primary-button" type="submit">进入客户端</button>
        </form>

        <div class="credential-grid">
          <button class="credential-card" type="button" data-action="use-demo" data-email="customer@glass.local" data-password="customer123">
            <strong>Demo Customer</strong>
            <span>customer@glass.local / customer123</span>
          </button>
          <button class="credential-card" type="button" data-action="use-demo" data-email="customer-viewer@glass.local" data-password="viewer123">
            <strong>Demo Customer Viewer</strong>
            <span>customer-viewer@glass.local / viewer123</span>
          </button>
        </div>

        <div class="inline-actions">
          <a class="ghost-button" href="/platform">业务操作端</a>
          <a class="ghost-button" href="/admin">管理端</a>
        </div>
      </div>
    </section>
  `;
}

function renderSummaryCards() {
  const summary = state.data.summary || {};
  const cards = [
    ['总订单', summary.totalOrders || 0],
    ['进行中', summary.activeOrders || 0],
    ['待取货', summary.readyForPickupOrders || 0],
    ['可用额度', formatMoney(summary.availableCredit || 0)],
  ];
  return `
    <div class="stats-grid">
      ${cards
        .map(
          ([label, value]) => `
            <article class="stat-card">
              <span>${escapeHtml(label)}</span>
              <strong>${escapeHtml(value)}</strong>
            </article>
          `
        )
        .join('')}
    </div>
  `;
}

function renderOrderList() {
  if (!state.data.orders.length) {
    return '<div class="empty-state">当前还没有订单。</div>';
  }

  return state.data.orders
    .map(
      (order) => `
        <article class="order-card ${order.status === 'ready_for_pickup' ? 'is-rework' : ''}">
          <header>
            <div>
              <p class="kicker">${escapeHtml(state.data.profile?.companyName || '')}</p>
              <h3>${escapeHtml(order.orderNo)}</h3>
            </div>
            <div class="badge-row"><span class="badge badge-info">${escapeHtml(order.statusLabel)}</span></div>
          </header>
          <div class="order-meta-grid">
            <div><span>玻璃</span><strong>${escapeHtml(order.glassType)}</strong></div>
            <div><span>厚度</span><strong>${escapeHtml(order.thickness)}</strong></div>
            <div><span>数量</span><strong>${escapeHtml(order.quantity)}</strong></div>
            <div><span>预计完成</span><strong>${escapeHtml(formatDate(order.estimatedCompletionDate))}</strong></div>
          </div>
          <div class="card-footer">
            <div class="meta-stack">
              <span>创建于 ${escapeHtml(formatDate(order.createdAt, true))}</span>
              <span>${escapeHtml(order.specialInstructions || '无备注')}</span>
            </div>
            <div class="inline-actions">
              <button class="ghost-button" data-action="open-order-detail" data-order-id="${escapeHtml(order.id)}">详情</button>
            </div>
          </div>
        </article>
      `
    )
    .join('');
}

function renderDashboard() {
  return `
    <section class="panel">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">Customer App</p>
          <h2>${escapeHtml(state.data.profile?.companyName || '客户端概览')}</h2>
        </div>
        <div class="inline-actions">
          <button class="ghost-button" data-action="refresh">刷新</button>
          ${renderCreateOrderAction({ label: '在线下单', compact: true })}
        </div>
      </div>
      ${renderSummaryCards()}
    </section>

    <section class="panel">
      <div class="panel-heading slim">
        <h2>最近订单</h2>
      </div>
      <div class="list-stack">${renderOrderList()}</div>
    </section>
  `;
}

function renderOrders() {
  return `
    <section class="panel">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">Orders</p>
          <h2>我的订单</h2>
        </div>
        ${renderCreateOrderAction({ label: '新建订单', compact: true })}
      </div>
    </section>
    <section class="list-stack">${renderOrderList()}</section>
  `;
}

function renderNotifications() {
  return `
    <section class="panel">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">Notifications</p>
          <h2>消息提醒</h2>
        </div>
        <button class="ghost-button" data-action="mark-read">全部标记已读</button>
      </div>
      <div class="list-stack">
        ${
          state.data.notifications.length
            ? state.data.notifications
                .map(
                  (item) => `
                    <article class="notification-card ${item.isRead ? 'is-read' : ''} severity-${escapeHtml(item.severity)}">
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

function renderProfile() {
  const profile = state.data.profile || {};
  const credit = state.data.credit || {};
  return `
    <section class="panel split-panel">
      <div>
        <div class="panel-heading slim"><h2>客户档案</h2></div>
        <dl class="detail-list">
          <div><dt>公司</dt><dd>${escapeHtml(profile.companyName || '未设置')}</dd></div>
          <div><dt>联系人</dt><dd>${escapeHtml(profile.contactName || '未设置')}</dd></div>
          <div><dt>电话</dt><dd>${escapeHtml(profile.phone || '未设置')}</dd></div>
          <div><dt>邮箱</dt><dd>${escapeHtml(profile.email || '未设置')}</dd></div>
          <div><dt>地址</dt><dd>${escapeHtml(profile.address || '未设置')}</dd></div>
          <div><dt>价格等级</dt><dd>${escapeHtml(profile.priceLevel || 'standard')}</dd></div>
          <div><dt>访问级别</dt><dd>${escapeHtml(getAccessLevelLabel())}</dd></div>
        </dl>
      </div>
      <div>
        <div class="panel-heading slim"><h2>信用额度</h2></div>
        <dl class="detail-list">
          <div><dt>总额度</dt><dd>${escapeHtml(formatMoney(credit.limit))}</dd></div>
          <div><dt>已占用</dt><dd>${escapeHtml(formatMoney(credit.used))}</dd></div>
          <div><dt>可用额度</dt><dd>${escapeHtml(formatMoney(credit.available))}</dd></div>
        </dl>
      </div>
    </section>
  `;
}

function renderOrderFormModal() {
  return `
    <div class="modal-card wide-modal">
      <header class="modal-header">
        <div>
          <p class="eyebrow">New Order</p>
          <h2>在线下单</h2>
        </div>
        <button class="icon-button" data-action="close-modal" aria-label="关闭">×</button>
      </header>
      <form class="stack-form" data-form="order">
        <div class="two-column-grid">
          <label>
            <span>玻璃类型</span>
            <select name="glassType" required>
              <option value="">请选择</option>
              ${state.options.glassTypes.map((glassType) => `<option value="${escapeHtml(glassType)}">${escapeHtml(glassType)}</option>`).join('')}
            </select>
          </label>
          <label>
            <span>厚度</span>
            <select name="thickness" required>
              <option value="">请选择</option>
              ${state.options.thicknessOptions.map((thickness) => `<option value="${escapeHtml(thickness)}">${escapeHtml(thickness)}</option>`).join('')}
            </select>
          </label>
          <label>
            <span>数量</span>
            <input name="quantity" type="number" min="1" required value="1" />
          </label>
          <label>
            <span>优先级</span>
            <select name="priority">
              ${state.options.priorities.map((priority) => `<option value="${escapeHtml(priority.value)}">${escapeHtml(priority.label)}</option>`).join('')}
            </select>
          </label>
          <label>
            <span>预计完成日期</span>
            <input name="estimatedCompletionDate" type="date" />
          </label>
        </div>
        <label>
          <span>备注</span>
          <textarea name="specialInstructions" rows="4" placeholder="补充尺寸、交付要求或现场说明"></textarea>
        </label>
        <label>
          <span>图纸 PDF / 图片</span>
          <input name="drawing" type="file" accept="application/pdf,image/*" />
        </label>
        <div class="modal-actions">
          <button class="ghost-button" type="button" data-action="close-modal">取消</button>
          <button class="primary-button" type="submit">提交订单</button>
        </div>
      </form>
    </div>
  `;
}

function renderOrderDetailModal() {
  const order = getOrder(state.ui.modal?.orderId);
  if (!order) {
    return '';
  }

  return `
    <div class="modal-card wide-modal">
      <header class="modal-header">
        <div>
          <p class="eyebrow">Order Detail</p>
          <h2>${escapeHtml(order.orderNo)}</h2>
        </div>
        <button class="icon-button" data-action="close-modal" aria-label="关闭">×</button>
      </header>
      <div class="detail-grid">
        <section>
          <h3>订单信息</h3>
          <dl class="detail-list">
            <div><dt>状态</dt><dd>${escapeHtml(order.statusLabel)}</dd></div>
            <div><dt>玻璃类型</dt><dd>${escapeHtml(order.glassType)}</dd></div>
            <div><dt>厚度</dt><dd>${escapeHtml(order.thickness)}</dd></div>
            <div><dt>数量</dt><dd>${escapeHtml(order.quantity)}</dd></div>
            <div><dt>预计完成</dt><dd>${escapeHtml(formatDate(order.estimatedCompletionDate))}</dd></div>
            <div><dt>创建时间</dt><dd>${escapeHtml(formatDate(order.createdAt, true))}</dd></div>
          </dl>
          <p class="detail-note">${escapeHtml(order.specialInstructions || '无备注')}</p>
          ${
            order.drawingUrl
              ? `<a class="file-link" href="${escapeHtml(order.drawingUrl)}" target="_blank" rel="noreferrer">查看图纸：${escapeHtml(order.drawingName || '打开附件')}</a>`
              : '<p class="subtle-copy">当前未上传图纸。</p>'
          }
        </section>
        <section>
          <h3>时间线</h3>
          <div class="progress-list">
            ${
              order.timeline?.length
                ? order.timeline
                    .map(
                      (event) => `
                        <article class="progress-row completed">
                          <div>
                            <strong>${escapeHtml(event.type || event.message || '事件')}</strong>
                            <span>${escapeHtml(event.message || '')}</span>
                          </div>
                          <div class="meta-stack">
                            <span>${escapeHtml(formatDate(event.createdAt, true))}</span>
                          </div>
                        </article>
                      `
                    )
                    .join('')
                : '<div class="empty-state small">还没有时间线记录。</div>'
            }
          </div>
        </section>
      </div>
    </div>
  `;
}

function renderModal() {
  if (!state.ui.modal) {
    return '';
  }
  if (state.ui.modal.type === 'order-form') {
    return `<div class="modal-backdrop">${renderOrderFormModal()}</div>`;
  }
  if (state.ui.modal.type === 'order-detail') {
    return `<div class="modal-backdrop">${renderOrderDetailModal()}</div>`;
  }
  return '';
}

function renderActiveTab() {
  switch (state.ui.activeTab) {
    case 'orders':
      return renderOrders();
    case 'notifications':
      return renderNotifications();
    case 'profile':
      return renderProfile();
    default:
      return renderDashboard();
  }
}

function renderShell() {
  root.innerHTML = `
    <div class="shell">
      <header class="topbar">
        <div>
          <p class="eyebrow">Glass Factory App</p>
          <h1>客户中心</h1>
          <p class="lead-mini">${escapeHtml(state.user?.name || '')} · ${escapeHtml(state.data.profile?.companyName || '')} · ${escapeHtml(getAccessLevelLabel())}</p>
        </div>
        <div class="topbar-actions">
          <button class="ghost-button" data-action="refresh">刷新</button>
          <button class="ghost-button" data-action="logout">退出</button>
        </div>
      </header>

      ${renderFlash()}

      <nav class="tabbar">
        ${[
          ['dashboard', '概览'],
          ['orders', '订单'],
          ['notifications', '通知'],
          ['profile', '个人中心'],
        ]
          .map(
            ([tab, label]) => `
              <button class="tab ${state.ui.activeTab === tab ? 'is-active' : ''}" data-action="switch-tab" data-tab="${escapeHtml(tab)}">
                ${escapeHtml(label)}
              </button>
            `
          )
          .join('')}
      </nav>

      <main class="content-stack">${renderActiveTab()}</main>
    </div>
    ${renderModal()}
  `;
  document.body.classList.toggle('modal-open', Boolean(state.ui.modal));
}

function renderLoading() {
  root.innerHTML = `
    <section class="auth-shell compact-loading">
      <div class="auth-panel loading-panel">
        <div class="spinner"></div>
        <h2>正在载入客户端…</h2>
      </div>
    </section>
  `;
}

function render() {
  if (!root) {
    return;
  }
  if (state.token && !state.user) {
    renderLoading();
    return;
  }
  if (!state.token || !state.user) {
    renderLogin();
    return;
  }
  renderShell();
}

async function handleClick(event) {
  const trigger = event.target.closest('[data-action]');
  if (!trigger) {
    return;
  }

  const { action, email, password, orderId, tab } = trigger.dataset;
  if (action === 'use-demo') {
    const emailInput = document.querySelector('input[name="email"]');
    const passwordInput = document.querySelector('input[name="password"]');
    if (emailInput && passwordInput) {
      emailInput.value = email || '';
      passwordInput.value = password || '';
    }
    return;
  }

  if (action === 'switch-tab') {
    state.ui.activeTab = tab || 'dashboard';
    render();
    return;
  }

  if (action === 'dismiss-flash') {
    state.ui.flash = null;
    render();
    return;
  }

  if (action === 'logout') {
    resetSession();
    render();
    return;
  }

  if (action === 'refresh') {
    try {
      await refreshData();
    } catch (error) {
      setFlash('error', error.message);
    }
    return;
  }

  if (action === 'open-order-form') {
    if (!canCreateOrders()) {
      setFlash('error', '当前账号为只读访客，不能创建订单。');
      return;
    }
    state.ui.modal = { type: 'order-form' };
    render();
    return;
  }

  if (action === 'open-order-detail') {
    try {
      await loadOrderDetail(orderId);
      state.ui.modal = { type: 'order-detail', orderId };
      render();
    } catch (error) {
      setFlash('error', error.message);
    }
    return;
  }

  if (action === 'close-modal') {
    state.ui.modal = null;
    render();
    return;
  }

  if (action === 'mark-read') {
    try {
      await api(`${APP_API_PREFIX}/notifications/read`, { method: 'POST' });
      await refreshData();
      setFlash('success', '通知已全部标记已读。');
    } catch (error) {
      setFlash('error', error.message);
    }
  }
}

async function handleSubmit(event) {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) {
    return;
  }

  event.preventDefault();
  const formType = form.dataset.form;
  try {
    if (formType === 'login') {
      const formData = new FormData(form);
      const payload = await api(LOGIN_API, {
        method: 'POST',
        body: {
          email: formData.get('email'),
          password: formData.get('password'),
        },
      });
      persistSession(payload);
      if (!ensureCustomerShell(payload.user)) {
        return;
      }
      await refreshData({ silent: true });
      state.ui.flash = { type: 'success', message: '登录成功。' };
      render();
      return;
    }

    if (formType === 'order') {
      if (!canCreateOrders()) {
        setFlash('error', '当前账号为只读访客，不能创建订单。');
        return;
      }
      const formData = new FormData(form);
      const createdOrder = await api('/v1/orders', {
        method: 'POST',
        body: {
          glassType: String(formData.get('glassType') || '').trim(),
          thickness: String(formData.get('thickness') || '').trim(),
          quantity: Number(formData.get('quantity') || 0),
          priority: String(formData.get('priority') || 'normal').trim() || 'normal',
          estimatedCompletionDate: String(formData.get('estimatedCompletionDate') || '').trim() || null,
          specialInstructions: String(formData.get('specialInstructions') || ''),
        },
      });
      const drawing = formData.get('drawing');
      if (drawing instanceof File && drawing.size > 0) {
        const drawingPayload = new FormData();
        drawingPayload.set('drawing', drawing);
        await api(`/v1/orders/${createdOrder.id}/drawing`, {
          method: 'POST',
          body: drawingPayload,
        });
      }
      state.ui.modal = null;
      await refreshData({ silent: true });
      state.ui.flash = { type: 'success', message: '订单已创建。' };
      render();
    }
  } catch (error) {
    if (error.status === 401) {
      resetSession();
      render();
      return;
    }
    if (error.status === 403) {
      if (state.user && ['customer', 'customer_viewer'].includes(String(state.user.role || '').toLowerCase())) {
        setFlash('error', error.message);
        return;
      }
      window.location.assign(state.user ? resolveHomePathForUser(state.user) : '/platform');
      return;
    }
    setFlash('error', error.message);
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
    if (error.status === 403) {
      window.location.assign(state.user ? resolveHomePathForUser(state.user) : '/platform');
      return;
    }
    if (error.status === 401) {
      resetSession();
    }
    render();
  }
}

root = document.querySelector('#app');
document.addEventListener('click', (event) => {
  handleClick(event).catch((error) => setFlash('error', error.message));
});
document.addEventListener('submit', (event) => {
  handleSubmit(event).catch((error) => setFlash('error', error.message));
});
bootstrap();