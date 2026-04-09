// ========== State Management ==========
const state = {
  currentUser: null,
  currentPage: 'dashboard',
  isLoggedIn: false
};

// ========== DOM Elements ==========
const loginPage = document.getElementById('login-page');
const mainLayout = document.getElementById('main-layout');
const loginForm = document.getElementById('login-form');
const navItems = document.querySelectorAll('.nav-item');
const contentPages = document.querySelectorAll('.content-page');

// ========== Login Handler ==========
loginForm.addEventListener('submit', (e) => {
  e.preventDefault();
  const username = document.getElementById('username').value;
  const password = document.getElementById('password').value;
  
  // Demo login (replace with API call in production)
  if (username === 'admin' && password === 'admin123') {
    state.isLoggedIn = true;
    state.currentUser = { username: 'admin', role: 'admin', name: '管理員' };
    loginPage.style.display = 'none';
    mainLayout.classList.add('active');
    document.getElementById('user-info').textContent = state.currentUser.name;
  } else {
    alert('無效的用戶名或密碼');
  }
});

// ========== Navigation ==========
navItems.forEach(item => {
  item.addEventListener('click', (e) => {
    e.preventDefault();
    const page = item.dataset.page;
    navigateTo(page);
  });
});

function navigateTo(page) {
  // Update nav
  navItems.forEach(nav => nav.classList.remove('active'));
  document.querySelector(`[data-page="${page}"]`).classList.add('active');
  
  // Update page
  contentPages.forEach(p => p.classList.remove('active'));
  document.getElementById(page).classList.add('active');
  
  state.currentPage = page;
}

// ========== Logout ==========
document.getElementById('logout-btn').addEventListener('click', () => {
  state.isLoggedIn = false;
  state.currentUser = null;
  mainLayout.classList.remove('active');
  loginPage.style.display = 'flex';
  document.getElementById('username').value = '';
  document.getElementById('password').value = '';
});

// ========== Modal Functions ==========
function showModal(modalId) {
  document.getElementById(modalId).classList.remove('hidden');
}

function closeModal(modalId) {
  document.getElementById(modalId).classList.add('hidden');
}

function showNewOrderModal() {
  showModal('new-order-modal');
}

function showPickupModal() {
  showModal('pickup-modal');
}

function showNewCustomerModal() {
  // TODO: Implement customer modal
  alert('客戶管理功能即將推出');
}

// ========== Production View Toggle ==========
function toggleProductionView(view) {
  const btns = document.querySelectorAll('.btn-toggle');
  btns.forEach(btn => btn.classList.remove('active'));
  event.target.classList.add('active');
  
  if (view === 'company') {
    document.getElementById('production-by-company').classList.remove('hidden');
    document.getElementById('production-by-date').classList.add('hidden');
  } else {
    document.getElementById('production-by-company').classList.add('hidden');
    document.getElementById('production-by-date').classList.remove('hidden');
  }
}

// ========== Signature Pad ==========
let canvas, ctx, isDrawing = false;

function initSignaturePad() {
  canvas = document.getElementById('signature-canvas');
  if (!canvas) return;
  
  ctx = canvas.getContext('2d');
  ctx.strokeStyle = '#000';
  ctx.lineWidth = 2;
  ctx.lineCap = 'round';
  
  canvas.addEventListener('mousedown', startDrawing);
  canvas.addEventListener('mousemove', draw);
  canvas.addEventListener('mouseup', stopDrawing);
  canvas.addEventListener('mouseout', stopDrawing);
  
  // Touch support
  canvas.addEventListener('touchstart', handleTouch);
  canvas.addEventListener('touchmove', handleTouch);
  canvas.addEventListener('touchend', stopDrawing);
}

function startDrawing(e) {
  isDrawing = true;
  ctx.beginPath();
  const rect = canvas.getBoundingClientRect();
  ctx.moveTo(e.clientX - rect.left, e.clientY - rect.top);
}

function draw(e) {
  if (!isDrawing) return;
  const rect = canvas.getBoundingClientRect();
  ctx.lineTo(e.clientX - rect.left, e.clientY - rect.top);
  ctx.stroke();
}

function stopDrawing() {
  isDrawing = false;
}

function handleTouch(e) {
  e.preventDefault();
  const touch = e.touches[0];
  const mouseEvent = new MouseEvent(
    e.type === 'touchstart' ? 'mousedown' :
    e.type === 'touchmove' ? 'mousemove' : 'mouseup',
    {
      clientX: touch.clientX,
      clientY: touch.clientY
    }
  );
  canvas.dispatchEvent(mouseEvent);
}

function clearSignature() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
}

function confirmPickup() {
  const signerName = document.getElementById('signer-name').value;
  if (!signerName) {
    alert('請輸入簽名人姓名');
    return;
  }
  
  // Get signature data
  const signatureData = canvas.toDataURL();
  
  // In production, this would be an API call
  alert(`取貨確認！\n簽名人: ${signerName}\n簽名已保存`);
  
  closeModal('pickup-modal');
  clearSignature();
  document.getElementById('signer-name').value = '';
}

// ========== Order Form Handler ==========
document.getElementById('new-order-form').addEventListener('submit', (e) => {
  e.preventDefault();
  const formData = new FormData(e.target);
  
  // In production, this would be an API call
  const orderData = {
    customer: formData.get('customer'),
    glass_type: formData.get('glass_type'),
    thickness: formData.get('thickness'),
    quantity: formData.get('quantity'),
    priority: formData.get('priority'),
    special_instructions: formData.get('special_instructions'),
    estimated_date: formData.get('estimated_date')
  };
  
  console.log('Order submitted:', orderData);
  alert('訂單已建立！');
  closeModal('new-order-modal');
  e.target.reset();
});

// ========== Table Row Actions ==========
document.querySelectorAll('.data-table').forEach(table => {
  table.addEventListener('click', (e) => {
    if (e.target.classList.contains('btn-small')) {
      const action = e.target.textContent;
      if (action === '取貨簽字') {
        showPickupModal();
      } else if (action === '查看') {
        // TODO: Show order details
        alert('訂單詳情功能即將推出');
      } else if (action === '編輯') {
        alert('編輯功能即將推出');
      }
    }
  });
});

// ========== Initialize ==========
document.addEventListener('DOMContentLoaded', () => {
  initSignaturePad();
});

// ========== Search & Filter ==========
document.getElementById('search-orders').addEventListener('input', (e) => {
  const searchTerm = e.target.value.toLowerCase();
  const rows = document.querySelectorAll('#orders-table-body tr');
  
  rows.forEach(row => {
    const text = row.textContent.toLowerCase();
    row.style.display = text.includes(searchTerm) ? '' : 'none';
  });
});

document.getElementById('filter-status').addEventListener('change', (e) => {
  const status = e.target.value;
  const rows = document.querySelectorAll('#orders-table-body tr');
  
  rows.forEach(row => {
    if (!status) {
      row.style.display = '';
    } else {
      const hasStatus = row.textContent.includes(getStatusText(status));
      row.style.display = hasStatus ? '' : 'none';
    }
  });
});

function getStatusText(status) {
  const statusMap = {
    'received': '已接單',
    'drawing': '畫圖',
    'production': '生產中',
    'completed': '已完成',
    'ready_pickup': '可取貨',
    'picked_up': '已取'
  };
  return statusMap[status] || status;
}

// ========== Production Stage Actions ==========
document.querySelectorAll('.production-card').forEach(card => {
  const actions = card.querySelectorAll('.card-actions .btn-small');
  
  actions.forEach(btn => {
    btn.addEventListener('click', () => {
      const orderNumber = card.querySelector('.order-number').textContent;
      
      if (btn.textContent === '標記完成') {
        alert(`訂單 ${orderNumber} 狀態已更新`);
      } else if (btn.textContent === '需重做') {
        alert(`訂單 ${orderNumber} 已標記為需重做`);
      } else if (btn.textContent === '更新') {
        alert(`訂單 ${orderNumber} 更新界面`);
      }
    });
  });
});

// Close modal on outside click
window.addEventListener('click', (e) => {
  if (e.target.classList.contains('modal') && !e.target.classList.contains('hidden')) {
    e.target.classList.add('hidden');
  }
});