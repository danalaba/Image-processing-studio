"""PostgreSQL schema for milestone 3. Connections are scoped to each operation."""
import os
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row


@contextmanager
def database():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("Set DATABASE_URL to a PostgreSQL connection URL; see README.md")
    with psycopg.connect(url, row_factory=dict_row, connect_timeout=5) as connection:
        yield connection


def initialize():
    with database() as connection:
        # Serialize initial schema creation if multiple APIs start together.
        connection.execute("SELECT pg_advisory_xact_lock(710032)")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id UUID PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions(user_id);
            CREATE TABLE IF NOT EXISTS auth_limits (
                key TEXT PRIMARY KEY,
                attempts INTEGER NOT NULL,
                window_start TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE TABLE IF NOT EXISTS jobs (
                id UUID PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                status TEXT NOT NULL CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED')),
                target_width INTEGER NOT NULL,
                target_height INTEGER NOT NULL,
                width INTEGER,
                height INTEGER,
                result BYTEA,
                error TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                finished_at TIMESTAMPTZ,
                CHECK (status <> 'COMPLETED' OR result IS NOT NULL)
            );
            CREATE INDEX IF NOT EXISTS jobs_user_created_idx ON jobs(user_id, created_at DESC);
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        if not connection.execute("SELECT 1 FROM schema_migrations WHERE version = 2").fetchone():
            connection.execute("""
                ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_status_check;
                ALTER TABLE jobs ADD CONSTRAINT jobs_status_check CHECK
                    (status IN ('QUEUED', 'RUNNING', 'CANCELLING', 'COMPLETED', 'FAILED', 'CANCELLED'));
                ALTER TABLE jobs ADD COLUMN IF NOT EXISTS progress INTEGER NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100);
                ALTER TABLE jobs ADD COLUMN IF NOT EXISTS stage TEXT NOT NULL DEFAULT 'queued';
                ALTER TABLE jobs ADD COLUMN IF NOT EXISTS input_data BYTEA;
                ALTER TABLE jobs ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
                ALTER TABLE jobs ADD COLUMN IF NOT EXISTS worker_id TEXT;
                ALTER TABLE jobs ADD COLUMN IF NOT EXISTS claim_id UUID;
                ALTER TABLE jobs ADD COLUMN IF NOT EXISTS dispatched_at TIMESTAMPTZ;
                UPDATE jobs SET progress = 100, stage = 'completed' WHERE status = 'COMPLETED';
                UPDATE jobs SET stage = 'failed' WHERE status = 'FAILED';
                UPDATE jobs SET status = 'FAILED', stage = 'failed', finished_at = now(),
                    error = 'Обробку попередньої версії було перервано.' WHERE status = 'RUNNING';
                INSERT INTO schema_migrations(version) VALUES (2);
            """)
        if not connection.execute("SELECT 1 FROM schema_migrations WHERE version = 3").fetchone():
            connection.execute("""
                ALTER TABLE jobs ADD COLUMN file_count INTEGER NOT NULL DEFAULT 1 CHECK (file_count BETWEEN 1 AND 10);
                ALTER TABLE jobs ADD COLUMN processed_files INTEGER NOT NULL DEFAULT 0 CHECK (processed_files BETWEEN 0 AND file_count);
                ALTER TABLE jobs ADD COLUMN result_type TEXT NOT NULL DEFAULT 'image/png' CHECK (result_type IN ('image/png','application/zip'));
                ALTER TABLE jobs ADD COLUMN input_files BYTEA[];
                ALTER TABLE jobs ADD COLUMN file_names TEXT[];
                ALTER TABLE jobs ADD CONSTRAINT jobs_input_files_check CHECK (input_files IS NULL OR cardinality(input_files) = file_count);
                UPDATE jobs SET processed_files = 1 WHERE status = 'COMPLETED';
                INSERT INTO schema_migrations(version) VALUES (3);
            """)
