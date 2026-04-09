import Database from 'better-sqlite3';
import bcrypt from 'bcryptjs';
import { v4 as uuidv4 } from 'uuid';

const db = new Database('./glass_factory.db');

// Initialize tables
db.exec(`
  -- Users table
  CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('office', 'worker', 'supervisor', 'admin')),
    name TEXT,
    phone TEXT,
    email TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
  );

  -- Customers table
  CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY,
    company_name TEXT NOT NULL,
    contact_name TEXT,
    phone TEXT,
    email TEXT,
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
  );

  -- Glass types
  CREATE TABLE IF NOT EXISTS glass_types (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
  );

  -- Orders table
  CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    order_number TEXT UNIQUE NOT NULL,
    customer_id TEXT NOT NULL,
    glass_type TEXT NOT NULL,
    thickness TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    drawing_path TEXT,
    special_instructions TEXT,
    priority TEXT DEFAULT 'normal' CHECK(priority IN ('normal', 'rush', 'rework')),
    status TEXT DEFAULT 'received' CHECK(status IN ('received', 'drawing', 'production', 'completed', 'ready_pickup', 'picked_up')),
    estimated_completion_date DATE,
    created_by TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(id),
    FOREIGN KEY (created_by) REFERENCES users(id)
  );

  -- Production stages
  CREATE TABLE IF NOT EXISTS production_stages (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    stage TEXT NOT NULL CHECK(stage IN ('cut', 'edge', 'tempering', 'finished')),
    status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'in_progress', 'completed', 'rework')),
    worker_id TEXT,
    started_at DATETIME,
    completed_at DATETIME,
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (order_id) REFERENCES orders(id),
    FOREIGN KEY (worker_id) REFERENCES users(id)
  );

  -- Pickup records
  CREATE TABLE IF NOT EXISTS pickup_records (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    signed_by TEXT,
    signature_data TEXT,
    pickup_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    picked_by TEXT,
    notes TEXT,
    FOREIGN KEY (order_id) REFERENCES orders(id)
  );

  -- Order history
  CREATE TABLE IF NOT EXISTS order_history (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    action TEXT NOT NULL,
    user_id TEXT,
    details TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (order_id) REFERENCES orders(id)
  );
`);

// Insert default glass types
const defaultGlassTypes = ['Clear', 'Rain', 'Pinhead', 'Grey', 'Frosted', 'Low-E', 'Mirror'];
const insertGlassType = db.prepare('INSERT OR IGNORE INTO glass_types (id, name) VALUES (?, ?)');
defaultGlassTypes.forEach(type => insertGlassType.run(uuidv4(), type));

// Insert admin user (password: admin123)
const adminExists = db.prepare('SELECT id FROM users WHERE username = ?').get('admin');
if (!adminExists) {
  const hashedPassword = bcrypt.hashSync('admin123', 10);
  db.prepare('INSERT INTO users (id, username, password, role, name) VALUES (?, ?, ?, ?, ?)').run(
    uuidv4(), 'admin', hashedPassword, 'admin', 'System Admin'
  );
  console.log('Admin user created: admin / admin123');
}

export default db;