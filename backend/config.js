import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import dotenv from 'dotenv';

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export const ROOT_DIR = path.resolve(__dirname, '..');
export const DATA_DIR = path.join(ROOT_DIR, 'data');
export const PUBLIC_DIR = path.join(ROOT_DIR, 'public');
export const UPLOADS_DIR = path.join(ROOT_DIR, 'uploads');
export const DRAWINGS_DIR = path.join(UPLOADS_DIR, 'drawings');
export const SIGNATURES_DIR = path.join(UPLOADS_DIR, 'signatures');

export const SUPPORTED_DATABASE_PROVIDERS = Object.freeze(['sqlite', 'postgres']);

function resolveDatabaseProvider() {
  const provider = String(process.env.DATABASE_PROVIDER || 'sqlite')
    .trim()
    .toLowerCase();

  if (!SUPPORTED_DATABASE_PROVIDERS.includes(provider)) {
    throw new Error(
      `DATABASE_PROVIDER 必须是 ${SUPPORTED_DATABASE_PROVIDERS.join(' / ')}。`
    );
  }

  return provider;
}

export const PORT = Number(process.env.PORT || 3000);
export const DATABASE_PROVIDER = resolveDatabaseProvider();
export const JWT_SECRET = process.env.JWT_SECRET || 'glass-factory-dev-secret';
export const JWT_EXPIRES_IN = process.env.JWT_EXPIRES_IN || '12h';
export const SQLITE_DATABASE_PATH =
  process.env.SQLITE_DATABASE_PATH || path.join(DATA_DIR, 'glass-factory.db');
export const POSTGRES_DATABASE_URL = String(
  process.env.POSTGRES_DATABASE_URL || process.env.DATABASE_URL || ''
).trim();

export const SMTP_CONFIG = Object.freeze({
  host: String(process.env.SMTP_HOST || '').trim(),
  port: Number(process.env.SMTP_PORT || 587),
  secure: String(process.env.SMTP_SECURE || 'false') === 'true',
  user: String(process.env.SMTP_USER || '').trim(),
  pass: String(process.env.SMTP_PASS || '').trim(),
  from: String(process.env.SMTP_FROM || '').trim(),
});

export function requirePostgresDatabaseUrl() {
  if (!POSTGRES_DATABASE_URL) {
    throw new Error('POSTGRES_DATABASE_URL 或 DATABASE_URL 未配置。');
  }

  return POSTGRES_DATABASE_URL;
}

export function isDirectRun(importMeta) {
  return Boolean(process.argv[1]) && importMeta.url === pathToFileURL(process.argv[1]).href;
}