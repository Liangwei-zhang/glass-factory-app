export const POSTGRES_TABLES = Object.freeze([
  'users',
  'customers',
  'glass_types',
  'notification_templates',
  'orders',
  'order_steps',
  'order_events',
  'notifications',
  'order_versions',
  'rework_requests',
  'email_logs',
]);

export const POSTGRES_TRUNCATE_ORDER = Object.freeze([...POSTGRES_TABLES].reverse());

export const POSTGRES_SCHEMA_SQL = `
  CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    stage TEXT,
    created_at TEXT NOT NULL
  );

  CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY,
    company_name TEXT NOT NULL,
    contact_name TEXT,
    phone TEXT,
    email TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
  );

  CREATE TABLE IF NOT EXISTS glass_types (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    updated_by TEXT REFERENCES users(id)
  );

  CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    order_no TEXT NOT NULL UNIQUE,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    status TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'normal',
    glass_type TEXT NOT NULL,
    thickness TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    estimated_completion_date TEXT,
    special_instructions TEXT,
    drawing_path TEXT,
    drawing_name TEXT,
    created_by TEXT REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    entered_at TEXT,
    completed_at TEXT,
    cancelled_at TEXT,
    cancelled_reason TEXT,
    ready_for_pickup_at TEXT,
    picked_up_at TEXT,
    pickup_approved_at TEXT,
    pickup_approved_by TEXT REFERENCES users(id),
    pickup_signer_name TEXT,
    pickup_signature_path TEXT,
    is_modified INTEGER NOT NULL DEFAULT 0,
    rework_open INTEGER NOT NULL DEFAULT 0,
    last_production_activity_at TEXT,
    version INTEGER NOT NULL DEFAULT 1
  );

  CREATE TABLE IF NOT EXISTS order_steps (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    step_key TEXT NOT NULL,
    step_label TEXT NOT NULL,
    step_index INTEGER NOT NULL,
    status TEXT NOT NULL,
    rework_count INTEGER NOT NULL DEFAULT 0,
    rework_note TEXT,
    rework_unread INTEGER NOT NULL DEFAULT 0,
    started_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE (order_id, step_key)
  );

  CREATE TABLE IF NOT EXISTS order_events (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    message TEXT NOT NULL,
    actor_user_id TEXT REFERENCES users(id),
    metadata_json TEXT,
    created_at TEXT NOT NULL
  );

  CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    order_id TEXT REFERENCES orders(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
  );

  CREATE TABLE IF NOT EXISTS order_versions (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    reason TEXT,
    actor_user_id TEXT REFERENCES users(id),
    snapshot_json TEXT NOT NULL,
    changes_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
  );

  CREATE TABLE IF NOT EXISTS rework_requests (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    source_step_key TEXT NOT NULL,
    source_step_label TEXT NOT NULL,
    piece_numbers_json TEXT NOT NULL,
    piece_count INTEGER NOT NULL,
    note TEXT,
    actor_user_id TEXT REFERENCES users(id),
    is_acknowledged INTEGER NOT NULL DEFAULT 0,
    acknowledged_at TEXT,
    acknowledged_by TEXT REFERENCES users(id),
    created_at TEXT NOT NULL
  );

  CREATE TABLE IF NOT EXISTS notification_templates (
    template_key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    subject_template TEXT NOT NULL,
    body_template TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT REFERENCES users(id)
  );

  CREATE TABLE IF NOT EXISTS email_logs (
    id TEXT PRIMARY KEY,
    template_key TEXT NOT NULL,
    order_id TEXT REFERENCES orders(id) ON DELETE SET NULL,
    customer_email TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL,
    transport TEXT NOT NULL,
    error_message TEXT,
    provider_message_id TEXT,
    actor_user_id TEXT REFERENCES users(id),
    created_at TEXT NOT NULL,
    sent_at TEXT
  );

  CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
  CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
  CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at DESC);
  CREATE UNIQUE INDEX IF NOT EXISTS idx_glass_types_name_unique ON glass_types(LOWER(name));
  CREATE INDEX IF NOT EXISTS idx_glass_types_active_sort ON glass_types(is_active, sort_order, name);
  CREATE INDEX IF NOT EXISTS idx_order_steps_order_id ON order_steps(order_id, step_index);
  CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON notifications(user_id, is_read, created_at DESC);
  CREATE INDEX IF NOT EXISTS idx_order_versions_order ON order_versions(order_id, version_number DESC, created_at DESC);
  CREATE INDEX IF NOT EXISTS idx_rework_requests_order ON rework_requests(order_id, is_acknowledged, created_at DESC);
  CREATE INDEX IF NOT EXISTS idx_email_logs_created_at ON email_logs(created_at DESC);
  CREATE INDEX IF NOT EXISTS idx_email_logs_order ON email_logs(order_id, created_at DESC);
`;