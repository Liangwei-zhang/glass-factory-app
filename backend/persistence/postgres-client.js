import { Client } from 'pg';

import {
  isDirectRun,
  POSTGRES_DATABASE_URL,
  requirePostgresDatabaseUrl,
} from '../config.js';

function parsePostgresUrl(connectionString) {
  try {
    return new URL(connectionString);
  } catch {
    return null;
  }
}

export function isPostgresConfigured() {
  return Boolean(POSTGRES_DATABASE_URL);
}

export function getPostgresConnectionInfo(connectionString = POSTGRES_DATABASE_URL) {
  if (!connectionString) {
    return null;
  }

  const parsedUrl = parsePostgresUrl(connectionString);
  if (!parsedUrl) {
    return {
      summary: 'invalid-postgres-url',
      database: null,
      host: null,
      port: null,
      user: null,
    };
  }

  return {
    summary: `${parsedUrl.protocol}//${parsedUrl.username || 'user'}@${parsedUrl.hostname}:${parsedUrl.port || '5432'}${parsedUrl.pathname}`,
    database: parsedUrl.pathname ? parsedUrl.pathname.replace(/^\//, '') : null,
    host: parsedUrl.hostname || null,
    port: parsedUrl.port || '5432',
    user: parsedUrl.username || null,
  };
}

export async function pingPostgres(connectionString = requirePostgresDatabaseUrl()) {
  const client = new Client({ connectionString });
  const startedAt = Date.now();

  await client.connect();
  try {
    const result = await client.query('SELECT NOW() AS server_now');

    return {
      configured: true,
      reachable: true,
      latencyMs: Date.now() - startedAt,
      connection: getPostgresConnectionInfo(connectionString),
      serverNow: result.rows[0]?.server_now ?? null,
    };
  } finally {
    await client.end();
  }
}

export async function getPostgresHealth(connectionString = POSTGRES_DATABASE_URL) {
  if (!connectionString) {
    return {
      configured: false,
      reachable: false,
      latencyMs: null,
      connection: null,
      error: null,
    };
  }

  try {
    return await pingPostgres(connectionString);
  } catch (error) {
    return {
      configured: true,
      reachable: false,
      latencyMs: null,
      connection: getPostgresConnectionInfo(connectionString),
      error: error.message || 'PostgreSQL ping failed.',
    };
  }
}

if (isDirectRun(import.meta)) {
  getPostgresHealth()
    .then((health) => {
      console.log(JSON.stringify(health, null, 2));
      process.exit(health.reachable ? 0 : 1);
    })
    .catch((error) => {
      console.error(error.message || error);
      process.exit(1);
    });
}