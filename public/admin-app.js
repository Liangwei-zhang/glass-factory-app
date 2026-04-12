const TOKEN_KEY = 'glass-factory-token';
const REFRESH_TOKEN_KEY = 'glass-factory-refresh-token';

const state = {
  token: localStorage.getItem(TOKEN_KEY),
  refreshToken: localStorage.getItem(REFRESH_TOKEN_KEY),
  user: null,
  data: {
    overview: null,
    runtime: null,
    alerts: [],
    users: [],
  },
  ui: {
    activeTab: 'overview',
    flash: null,
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
    ...(withTime ? { hour: '2-digit', minute: '2-digit' } : {}),
  }).format(date);
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

function normalizeUser(user) {
  const canonicalRole = String(user?.canonicalRole || user?.role || '')
    .trim()
    .toLowerCase() || 'operator';
  const homePath = user?.homePath || resolveShellForRole(canonicalRole);
  return {
    ...user,
    id: user?.id,
    name: user?.display_name || user?.displayName || user?.name || user?.username || '',
    role: canonicalRole,
    canonicalRole,
    email: user?.email || '',
    stage: user?.stage || '',
    customerId: user?.customerId || user?.customer_id || null,
    customerName: user?.customerName || '',
    homePath,
    shell: user?.shell || (homePath === '/app' ? 'app' : homePath === '/admin' ? 'admin' : 'platform'),
  };
}

function resolveShellForRole(role) {
  const normalized = String(role || '').toLowerCase();
  if (['admin', 'super_admin', 'manager', 'finance'].includes(normalized)) {
    return '/admin';
  }
  if (['customer', 'customer_viewer'].includes(normalized)) {
    return '/app';
  }
  return '/platform';
}

function resolveHomePathForUser(user) {
  return user?.homePath || resolveShellForRole(user?.canonicalRole || user?.role);
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
    config.headers['Content-Type'] = 'application/json';
    config.headers['Idempotency-Key'] = globalThis.crypto?.randomUUID?.() ?? `idem-${Date.now()}`;
  }
  if (options.body) {
    config.body = JSON.stringify(options.body);
  }

  const response = await fetch(path, config);
  const rawPayload = await response.json().catch(() => ({}));
  const payload = unwrapApiPayload(rawPayload);

  if (
    response.status === 401 &&
    !options.skipAuthRefresh &&
    state.refreshToken &&
    path !== '/v1/auth/login' &&
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

function ensureAdminShell(user) {
  const role = String(user?.canonicalRole || user?.role || '').toLowerCase();
  if (!['admin', 'super_admin', 'manager'].includes(role)) {
    window.location.assign(resolveHomePathForUser(user));
    return false;
  }
  return true;
}

async function refreshData({ silent = false } = {}) {
  const [overview, runtime, alerts, users] = await Promise.all([
    api('/v1/admin/analytics/overview'),
    api('/v1/admin/runtime/health'),
    api('/v1/admin/runtime/alerts?limit=20'),
    api('/v1/admin/users?limit=20'),
  ]);
  state.data.overview = overview;
  state.data.runtime = runtime;
  state.data.alerts = alerts.items || [];
  state.data.users = (users.items || []).map((user) => normalizeUser(user));
  if (!silent) {
    render();
  }
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
        <p class="eyebrow">Admin Console</p>
        <h1>登录管理端</h1>
        <p class="lead-copy">查看经营概览、运行告警与用户列表。</p>
        <form class="stack-form" data-form="login">
          <label>
            <span>邮箱</span>
            <input name="email" type="email" placeholder="请输入邮箱" required />
          </label>
          <label>
            <span>密码</span>
            <input name="password" type="password" placeholder="请输入密码" required />
          </label>
          <button class="primary-button" type="submit">进入管理端</button>
        </form>
        <div class="credential-grid">
          <button class="credential-card" type="button" data-action="use-demo" data-email="supervisor@glass.local" data-password="supervisor123">
            <strong>Production Manager</strong>
            <span>点击填入管理端演示账号</span>
          </button>
        </div>
        <div class="inline-actions">
          <a class="ghost-button" href="/app">客户端</a>
          <a class="ghost-button" href="/platform">业务操作端</a>
        </div>
      </div>
    </section>
  `;
}

function renderOverview() {
  const kpis = state.data.overview?.kpis || {};
  const runtime = state.data.runtime || {};
  const cards = [
    ['今日订单', kpis.orders_today || 0],
    ['总订单', kpis.total_orders || 0],
    ['生产中', kpis.producing_orders || 0],
    ['活动工单', kpis.active_work_orders || 0],
  ];
  return `
    <section class="panel">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">Admin Overview</p>
          <h2>经营与运行概览</h2>
        </div>
        <button class="ghost-button" data-action="refresh">刷新</button>
      </div>
      <div class="stats-grid">
        ${cards.map(([label, value]) => `<article class="stat-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></article>`).join('')}
      </div>
    </section>
    <section class="panel split-panel">
      <div>
        <div class="panel-heading slim"><h2>运行时健康</h2></div>
        <pre class="detail-note" data-no-translate>${escapeHtml(JSON.stringify(runtime, null, 2))}</pre>
      </div>
      <div>
        <div class="panel-heading slim"><h2>最新告警</h2></div>
        <div class="list-stack compact-list">
          ${
            state.data.alerts.length
              ? state.data.alerts
                  .slice(0, 5)
                  .map(
                    (alert) => `
                      <article class="notification-card severity-warning">
                        <div>
                          <h3>${escapeHtml(alert.topic || 'Outbox Alert')}</h3>
                          <p>${escapeHtml(alert.last_error || alert.status || '暂无错误描述')}</p>
                        </div>
                        <div class="meta-stack">
                          <span>${escapeHtml(alert.status || 'unknown')}</span>
                          <span>${escapeHtml(formatDate(alert.created_at, true))}</span>
                        </div>
                      </article>
                    `
                  )
                  .join('')
              : '<div class="empty-state">当前没有告警。</div>'
          }
        </div>
      </div>
    </section>
  `;
}

function renderAlerts() {
  return `
    <section class="panel">
      <div class="panel-heading slim"><h2>运行告警</h2></div>
      <div class="list-stack">
        ${
          state.data.alerts.length
            ? state.data.alerts
                .map(
                  (alert) => `
                    <article class="notification-card severity-warning">
                      <div>
                        <h3>${escapeHtml(alert.topic || 'Outbox Event')}</h3>
                        <p>${escapeHtml(alert.last_error || '无详细错误')}</p>
                      </div>
                      <div class="meta-stack">
                        <span>attempt ${escapeHtml(alert.attempt_count || 0)} / ${escapeHtml(alert.max_attempts || 0)}</span>
                        <span>${escapeHtml(formatDate(alert.created_at, true))}</span>
                      </div>
                    </article>
                  `
                )
                .join('')
            : '<div class="empty-state">当前没有失败事件。</div>'
        }
      </div>
    </section>
  `;
}

function renderUsers() {
  return `
    <section class="panel">
      <div class="panel-heading slim"><h2>用户列表</h2></div>
      <div class="list-stack">
        ${
          state.data.users.length
            ? state.data.users
                .map(
                  (user) => `
                    <article class="customer-card ${user.is_active ? 'active' : ''}">
                      <div>
                        <p class="kicker">${escapeHtml(user.canonicalRole || user.role)}</p>
                        <h3>${escapeHtml(user.name || user.display_name || user.username)}</h3>
                        <p>${escapeHtml(user.email || '未设置邮箱')}</p>
                        ${user.customerName ? `<p class="subtle-copy">绑定客户：${escapeHtml(user.customerName)}</p>` : ''}
                      </div>
                      <div class="customer-summary">
                        <span>${escapeHtml(user.stage ? `工位 ${user.stage}` : `入口 ${user.homePath || '--'}`)}</span>
                        <span>${escapeHtml(user.customerId ? `客户ID ${user.customerId}` : '未绑定客户')}</span>
                        <span>${user.is_active ? '启用中' : '已停用'}</span>
                        <span>${escapeHtml(formatDate(user.created_at, true))}</span>
                      </div>
                    </article>
                  `
                )
                .join('')
            : '<div class="empty-state">没有可显示的用户。</div>'
        }
      </div>
    </section>
  `;
}

function renderActiveTab() {
  switch (state.ui.activeTab) {
    case 'alerts':
      return renderAlerts();
    case 'users':
      return renderUsers();
    default:
      return renderOverview();
  }
}

function renderShell() {
  root.innerHTML = `
    <div class="shell">
      <header class="topbar">
        <div>
          <p class="eyebrow">Glass Factory Admin</p>
          <h1>管理端控制台</h1>
          <p class="lead-mini">${escapeHtml(state.user?.name || '')} · ${escapeHtml(state.user?.canonicalRole || state.user?.role || '')}</p>
        </div>
        <div class="topbar-actions">
          <button class="ghost-button" data-action="refresh">刷新</button>
          <button class="ghost-button" data-action="logout">退出</button>
        </div>
      </header>
      ${renderFlash()}
      <nav class="tabbar">
        ${[
          ['overview', '概览'],
          ['alerts', '告警'],
          ['users', '用户'],
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
  `;
}

function renderLoading() {
  root.innerHTML = `
    <section class="auth-shell compact-loading">
      <div class="auth-panel loading-panel">
        <div class="spinner"></div>
        <h2>正在载入管理端…</h2>
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
  const { action, tab, email, password } = trigger.dataset;
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
    state.ui.activeTab = tab || 'overview';
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
      state.ui.flash = { type: 'error', message: error.message };
      render();
    }
  }
}

async function handleSubmit(event) {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) {
    return;
  }
  event.preventDefault();
  try {
    const formData = new FormData(form);
    const payload = await api('/v1/auth/login', {
      method: 'POST',
      body: {
        email: formData.get('email'),
        password: formData.get('password'),
      },
    });
    persistSession(payload);
    if (!ensureAdminShell(state.user)) {
      return;
    }
    await refreshData({ silent: true });
    state.ui.flash = { type: 'success', message: '登录成功。' };
    render();
  } catch (error) {
    if (error.status === 401) {
      resetSession();
      render();
      return;
    }
    state.ui.flash = { type: 'error', message: error.message };
    render();
  }
}

async function bootstrap() {
  render();
  if (!state.token) {
    return;
  }
  try {
    const me = await api('/v1/workspace/me');
    state.user = normalizeUser(me.user);
    if (!ensureAdminShell(state.user)) {
      return;
    }
    await refreshData({ silent: true });
    render();
  } catch {
    resetSession();
    render();
    return;
  }
}

root = document.querySelector('#app');
document.addEventListener('click', (event) => {
  handleClick(event).catch((error) => {
    state.ui.flash = { type: 'error', message: error.message };
    render();
  });
});
document.addEventListener('submit', (event) => {
  handleSubmit(event).catch((error) => {
    state.ui.flash = { type: 'error', message: error.message };
    render();
  });
});
bootstrap();