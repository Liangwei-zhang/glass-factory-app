import Database from 'better-sqlite3';
import { Client } from 'pg';

import {
  isDirectRun,
  requirePostgresDatabaseUrl,
  SQLITE_DATABASE_PATH,
} from '../backend/config.js';
import { POSTGRES_SCHEMA_SQL, POSTGRES_TABLES, POSTGRES_TRUNCATE_ORDER } from './postgres-schema.js';

function quoteIdentifier(identifier) {
  return `"${String(identifier).replaceAll('"', '""')}"`;
}

async function insertRow(client, tableName, row) {
  const columns = Object.keys(row);
  if (!columns.length) {
    return;
  }

  const placeholders = columns.map((_, index) => `$${index + 1}`).join(', ');
  const sql = `
    INSERT INTO ${quoteIdentifier(tableName)} (${columns.map(quoteIdentifier).join(', ')})
    VALUES (${placeholders})
  `;

  await client.query(sql, columns.map((columnName) => row[columnName]));
}

export async function syncSqliteToPostgres({
  sqlitePath = SQLITE_DATABASE_PATH,
  connectionString = requirePostgresDatabaseUrl(),
} = {}) {
  const sqlite = new Database(sqlitePath, { readonly: true, fileMustExist: true });
  const client = new Client({ connectionString });
  const counts = {};

  await client.connect();

  try {
    await client.query('BEGIN');
    await client.query(POSTGRES_SCHEMA_SQL);
    await client.query(
      `TRUNCATE TABLE ${POSTGRES_TRUNCATE_ORDER.map(quoteIdentifier).join(', ')} CASCADE`
    );

    for (const tableName of POSTGRES_TABLES) {
      const rows = sqlite.prepare(`SELECT * FROM ${tableName}`).all();
      counts[tableName] = rows.length;

      for (const row of rows) {
        await insertRow(client, tableName, row);
      }
    }

    await client.query('COMMIT');
    return counts;
  } catch (error) {
    await client.query('ROLLBACK');
    throw error;
  } finally {
    sqlite.close();
    await client.end();
  }
}

if (isDirectRun(import.meta)) {
  syncSqliteToPostgres()
    .then((counts) => {
      console.log(JSON.stringify(counts, null, 2));
    })
    .catch((error) => {
      console.error(error.message || error);
      process.exit(1);
    });
}