import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import jwt from 'jsonwebtoken';
import multer from 'multer';
import path from 'path';
import { fileURLToPath } from 'url';
import { v4 as uuidv4 } from 'uuid';
import db from './db.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

dotenv.config();
const app = express();
const PORT = process.env.PORT || 3000;
const JWT_SECRET = process.env.JWT_SECRET || 'glass-factory-secret-key';

app.use(cors());
app.use(express.json());
app.use('/uploads', express.static(path.join(__dirname, 'uploads')));

// Multer for file uploads
const storage = multer.diskStorage({
  destination: (req, file, cb) => cb(null, path.join(__dirname, 'uploads')),
  filename: (req, file, cb) => cb(null, `${Date.now()}-${file.originalname}`)
});
const upload = multer({ storage });

// Auth middleware
const authenticate = (req, res, next) => {
  const token = req.headers.authorization?.split(' ')[1];
  if (!token) return res.status(401).json({ error: 'No token provided' });
  
  try {
    const decoded = jwt.verify(token, JWT_SECRET);
    req.user = decoded;
    next();
  } catch (err) {
    res.status(401).json({ error: 'Invalid token' });
  }
};

// Role check middleware
const checkRole = (...roles) => (req, res, next) => {
  if (!roles.includes(req.user.role)) {
    return res.status(403).json({ error: 'Insufficient permissions' });
  }
  next();
};

// ============ AUTH ROUTES ============
app.post('/api/auth/login', (req, res) => {
  const { username, password } = req.body;
  const user = db.prepare('SELECT * FROM users WHERE username = ?').get(username);
  
  if (!user || !bcrypt.compareSync(password, user.password)) {
    return res.status(401).json({ error: 'Invalid credentials' });
  }
  
  const token = jwt.sign({ id: user.id, username: user.username, role: user.role }, JWT_SECRET, { expiresIn: '7d' });
  res.json({ token, user: { id: user.id, username: user.username, role: user.role, name: user.name } });
});

// ============ CUSTOMER ROUTES ============
app.get('/api/customers', authenticate, (req, res) => {
  const customers = db.prepare('SELECT * FROM customers ORDER BY company_name').all();
  res.json(customers);
});

app.post('/api/customers', authenticate, checkRole('office', 'admin'), (req, res) => {
  const { company_name, contact_name, phone, email, notes } = req.body;
  const id = uuidv4();
  db.prepare('INSERT INTO customers (id, company_name, contact_name, phone, email, notes) VALUES (?, ?, ?, ?, ?, ?)')
    .run(id, company_name, contact_name, phone, email, notes);
  res.json({ id, company_name, contact_name, phone, email, notes });
});

app.put('/api/customers/:id', authenticate, checkRole('office', 'admin'), (req, res) => {
  const { company_name, contact_name, phone, email, notes } = req.body;
  db.prepare('UPDATE customers SET company_name = ?, contact_name = ?, phone = ?, email = ?, notes = ? WHERE id = ?')
    .run(company_name, contact_name, phone, email, notes, req.params.id);
  res.json({ success: true });
});

// ============ ORDER ROUTES ============
app.get('/api/orders', authenticate, (req, res) => {
  const { status, customer_id, date_from, date_to } = req.query;
  let query = `
    SELECT o.*, c.company_name, c.contact_name, c.phone
    FROM orders o
    JOIN customers c ON o.customer_id = c.id
    WHERE 1=1
  `;
  const params = [];
  
  if (status) { query += ' AND o.status = ?'; params.push(status); }
  if (customer_id) { query += ' AND o.customer_id = ?'; params.push(customer_id); }
  if (date_from) { query += ' AND o.created_at >= ?'; params.push(date_from); }
  if (date_to) { query += ' AND o.created_at <= ?'; params.push(date_to); }
  
  query += ' ORDER BY o.created_at DESC';
  const orders = db.prepare(query).all(...params);
  res.json(orders);
});

app.get('/api/orders/:id', authenticate, (req, res) => {
  const order = db.prepare(`
    SELECT o.*, c.company_name, c.contact_name, c.phone, c.email
    FROM orders o
    JOIN customers c ON o.customer_id = c.id
    WHERE o.id = ?
  `).get(req.params.id);
  
  if (!order) return res.status(404).json({ error: 'Order not found' });
  
  const stages = db.prepare('SELECT * FROM production_stages WHERE order_id = ? ORDER BY stage').all(req.params.id);
  res.json({ ...order, stages });
});

app.post('/api/orders', authenticate, checkRole('office', 'admin'), upload.single('drawing'), (req, res) => {
  const { customer_id, glass_type, thickness, quantity, special_instructions, priority, estimated_completion_date } = req.body;
  const id = uuidv4();
  const order_number = `GF-${Date.now().toString(36).toUpperCase()}`;
  const drawing_path = req.file ? `/uploads/${req.file.filename}` : null;
  
  db.prepare(`
    INSERT INTO orders (id, order_number, customer_id, glass_type, thickness, quantity, drawing_path, special_instructions, priority, estimated_completion_date, created_by)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).run(id, order_number, customer_id, glass_type, thickness, quantity, drawing_path, special_instructions, priority, estimated_completion_date, req.user.id);
  
  // Create production stages
  const stages = ['cut', 'edge', 'tempering', 'finished'];
  stages.forEach(stage => {
    db.prepare('INSERT INTO production_stages (id, order_id, stage) VALUES (?, ?, ?)').run(uuidv4(), id, stage);
  });
  
  // Log history
  db.prepare('INSERT INTO order_history (id, order_id, action, user_id, details) VALUES (?, ?, ?, ?, ?)')
    .run(uuidv4(), id, 'created', req.user.id, 'Order created');
  
  res.json({ id, order_number, success: true });
});

app.put('/api/orders/:id', authenticate, checkRole('office', 'admin'), upload.single('drawing'), (req, res) => {
  const { glass_type, thickness, quantity, special_instructions, priority, estimated_completion_date, status } = req.body;
  const drawing_path = req.file ? `/uploads/${req.file.filename}` : null;
  
  let query = 'UPDATE orders SET ';
  const params = [];
  
  if (glass_type) { query += 'glass_type = ?, '; params.push(glass_type); }
  if (thickness) { query += 'thickness = ?, '; params.push(thickness); }
  if (quantity) { query += 'quantity = ?, '; params.push(quantity); }
  if (drawing_path) { query += 'drawing_path = ?, '; params.push(drawing_path); }
  if (special_instructions) { query += 'special_instructions = ?, '; params.push(special_instructions); }
  if (priority) { query += 'priority = ?, '; params.push(priority); }
  if (estimated_completion_date) { query += 'estimated_completion_date = ?, '; params.push(estimated_completion_date); }
  if (status) { query += 'status = ?, '; params.push(status); }
  
  query += 'updated_at = CURRENT_TIMESTAMP WHERE id = ?';
  params.push(req.params.id);
  
  db.prepare(query).run(...params);
  res.json({ success: true });
});

app.patch('/api/orders/:id/status', authenticate, (req, res) => {
  const { status } = req.body;
  db.prepare('UPDATE orders SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?').run(status, req.params.id);
  db.prepare('INSERT INTO order_history (id, order_id, action, user_id, details) VALUES (?, ?, ?, ?, ?)')
    .run(uuidv4(), req.params.id, `status_changed_to_${status}`, req.user.id, `Status changed to ${status}`);
  res.json({ success: true });
});

// ============ PRODUCTION STAGES ============
app.get('/api/orders/:id/stages', authenticate, (req, res) => {
  const stages = db.prepare('SELECT * FROM production_stages WHERE order_id = ? ORDER BY stage').all(req.params.id);
  res.json(stages);
});

app.patch('/api/stages/:id', authenticate, checkRole('worker', 'supervisor', 'admin'), (req, res) => {
  const { status, notes } = req.body;
  db.prepare('UPDATE production_stages SET status = ?, worker_id = ?, started_at = COALESCE(started_at, CURRENT_TIMESTAMP), completed_at = ?, notes = ? WHERE id = ?')
    .run(status, req.user.id, status === 'completed' ? new Date().toISOString() : null, notes, req.params.id);
  res.json({ success: true });
});

// ============ PICKUP ============
app.get('/api/orders/ready-pickup', authenticate, (req, res) => {
  const orders = db.prepare(`
    SELECT o.*, c.company_name, c.contact_name, c.phone
    FROM orders o
    JOIN customers c ON o.customer_id = c.id
    WHERE o.status = 'ready_pickup'
    ORDER BY o.updated_at DESC
  `).all();
  res.json(orders);
});

app.post('/api/orders/:id/pickup', authenticate, checkRole('office', 'supervisor', 'admin'), (req, res) => {
  const { signed_by, signature_data, picked_by, notes } = req.body;
  const id = uuidv4();
  
  db.prepare('INSERT INTO pickup_records (id, order_id, signed_by, signature_data, picked_by, notes) VALUES (?, ?, ?, ?, ?, ?)')
    .run(id, req.params.id, signed_by, signature_data, picked_by, notes);
  db.prepare('UPDATE orders SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?').run('picked_up', req.params.id);
  
  res.json({ success: true, pickup_id: id });
});

app.get('/api/pickup-records', authenticate, (req, res) => {
  const records = db.prepare(`
    SELECT p.*, o.order_number, c.company_name
    FROM pickup_records p
    JOIN orders o ON p.order_id = o.id
    JOIN customers c ON o.customer_id = c.id
    ORDER BY p.pickup_time DESC
  `).all();
  res.json(records);
});

// ============ DASHBOARD ============
app.get('/api/dashboard/stats', authenticate, (req, res) => {
  const totalOrders = db.prepare('SELECT COUNT(*) as count FROM orders').get().count;
  const pendingOrders = db.prepare("SELECT COUNT(*) as count FROM orders WHERE status NOT IN ('ready_pickup', 'picked_up')").get().count;
  const completedToday = db.prepare("SELECT COUNT(*) as count FROM orders WHERE status = 'completed' AND date(updated_at) = date('now')").get().count;
  const readyPickup = db.prepare("SELECT COUNT(*) as count FROM orders WHERE status = 'ready_pickup'").get().count;
  
  const recentOrders = db.prepare(`
    SELECT o.*, c.company_name
    FROM orders o
    JOIN customers c ON o.customer_id = c.id
    ORDER BY o.created_at DESC
    LIMIT 10
  `).all();
  
  res.json({
    totalOrders,
    pendingOrders,
    completedToday,
    readyPickup,
    recentOrders
  });
});

// ============ GLASS TYPES ============
app.get('/api/glass-types', authenticate, (req, res) => {
  const types = db.prepare('SELECT * FROM glass_types ORDER BY name').all();
  res.json(types);
});

// ============ PRODUCTION VIEW (Worker) ============
app.get('/api/production/by-company', authenticate, checkRole('worker', 'supervisor', 'admin'), (req, res) => {
  const orders = db.prepare(`
    SELECT o.*, c.company_name,
           (SELECT stage FROM production_stages WHERE order_id = o.id AND status != 'completed' ORDER BY stage LIMIT 1) as current_stage
    FROM orders o
    JOIN customers c ON o.customer_id = c.id
    WHERE o.status IN ('received', 'drawing', 'production')
    ORDER BY c.company_name, o.created_at
  `).all();
  
  // Group by company
  const grouped = {};
  orders.forEach(order => {
    if (!grouped[order.company_name]) {
      grouped[order.company_name] = [];
    }
    grouped[order.company_name].push(order);
  });
  
  res.json(grouped);
});

app.get('/api/production/by-date', authenticate, checkRole('worker', 'supervisor', 'admin'), (req, res) => {
  const orders = db.prepare(`
    SELECT o.*, c.company_name,
           (SELECT stage FROM production_stages WHERE order_id = o.id AND status != 'completed' ORDER BY stage LIMIT 1) as current_stage
    FROM orders o
    JOIN customers c ON o.customer_id = c.id
    WHERE o.status IN ('received', 'drawing', 'production')
    ORDER BY o.created_at DESC
  `).all();
  res.json(orders);
});

// Create uploads directory
import fs from 'fs';
if (!fs.existsSync('./uploads')) {
  fs.mkdirSync('./uploads');
}

app.listen(PORT, () => {
  console.log(`Glass Factory API running on http://localhost:${PORT}`);
  console.log('Default admin: admin / admin123');
});

export default app;