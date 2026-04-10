import { Client } from 'pg';

import { isDirectRun, requirePostgresDatabaseUrl } from '../backend/config.js';
import { POSTGRES_SCHEMA_SQL } from './postgres-schema.js';

export async function applyPostgresSchema(connectionString = requirePostgresDatabaseUrl()) {
  const client = new Client({ connectionString });
  await client.connect();

  try {
    await client.query(POSTGRES_SCHEMA_SQL);
  } finally {
    await client.end();
  }
}

if (isDirectRun(import.meta)) {
  applyPostgresSchema()
    .then(() => {
      console.log('PostgreSQL schema initialized.');
    })
    .catch((error) => {
      console.error(error.message || error);
      process.exit(1);
    });
}