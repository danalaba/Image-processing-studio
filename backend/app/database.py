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
