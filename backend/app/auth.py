"""Opaque bearer sessions: only their SHA-256 digests are stored in PostgreSQL."""
import hashlib
import re
import secrets
from typing import Annotated
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, Field, field_validator

from .database import database

router = APIRouter(prefix="/api/auth", tags=["auth"])
passwords = PasswordHasher()
# Perform the same expensive check for unknown users, too.
dummy_hash = passwords.hash(secrets.token_urlsafe(32))
bearer = HTTPBearer(auto_error=False)


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value):
        value = value.lower()
        if not re.fullmatch(r"[a-z0-9_-]{3,40}", value):
            raise ValueError("Use 3–40 Latin letters, digits, _ or -")
        return value


def token_digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def throttle(request, username):
    # Shared counters survive restarts and work across API instances. Do not trust
    # arbitrary X-Forwarded-For; configure trusted proxies when adding Nginx.
    source = request.client.host if request.client else "unknown"
    exceeded = False
    with database() as connection:
        connection.execute("DELETE FROM auth_limits WHERE window_start < now() - interval '5 minutes'")
        for key, limit in (("ip:" + source, 30), ("user:" + username, 10)):
            count = connection.execute("""
                INSERT INTO auth_limits(key, attempts) VALUES (%s, 1)
                ON CONFLICT (key) DO UPDATE SET
                    attempts = CASE WHEN auth_limits.window_start < now() - interval '1 minute'
                        THEN 1 ELSE auth_limits.attempts + 1 END,
                    window_start = CASE WHEN auth_limits.window_start < now() - interval '1 minute'
                        THEN now() ELSE auth_limits.window_start END
                RETURNING attempts
            """, (token_digest(key),)).fetchone()["attempts"]
            exceeded = exceeded or count > limit
    # Raise after commit so rejected attempts cannot roll back the counters.
    if exceeded:
        raise HTTPException(429, "Забагато спроб входу. Зачекайте хвилину.", headers={"Retry-After": "60"})


def current_user(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    if credentials is not None and len(credentials.credentials) <= 128:
        with database() as connection:
            user = connection.execute("""
                SELECT u.id, u.username, s.token_hash FROM users u
                JOIN sessions s ON s.user_id = u.id
                WHERE s.token_hash = %s AND s.expires_at > now()
            """, (token_digest(credentials.credentials),)).fetchone()
        if user:
            return user
    raise HTTPException(401, "Увійдіть у свій обліковий запис.", headers={"WWW-Authenticate": "Bearer"})


User = Annotated[dict, Depends(current_user)]


def create_session(connection, user_id):
    # Lock also makes the five-session limit reliable across API instances.
    connection.execute("SELECT id FROM users WHERE id = %s FOR UPDATE", (user_id,))
    connection.execute("DELETE FROM sessions WHERE user_id = %s AND expires_at <= now()", (user_id,))
    connection.execute("""
        DELETE FROM sessions WHERE token_hash IN (
            SELECT token_hash FROM sessions WHERE user_id = %s
            ORDER BY created_at DESC OFFSET 4
        )
    """, (user_id,))
    token = secrets.token_urlsafe(32)
    connection.execute("""
        INSERT INTO sessions(token_hash, user_id, expires_at)
        VALUES (%s, %s, now() + interval '24 hours')
    """, (token_digest(token), user_id))
    return {"access_token": token, "token_type": "bearer", "expires_in": 86400}


@router.post("/register", status_code=201)
def register(data: Credentials, response: Response, request: Request):
    throttle(request, data.username)
    encoded = passwords.hash(data.password)
    try:
        with database() as connection:
            user_id = uuid4()
            connection.execute("INSERT INTO users(id, username, password_hash) VALUES (%s, %s, %s)",
                               (user_id, data.username, encoded))
            session = create_session(connection, user_id)
    except UniqueViolation:
        raise HTTPException(409, "Таке ім’я вже зайняте.") from None
    response.headers["Cache-Control"] = "no-store"
    return session


@router.post("/login")
def login(data: Credentials, response: Response, request: Request):
    throttle(request, data.username)
    with database() as connection:
        user = connection.execute("SELECT * FROM users WHERE username = %s", (data.username,)).fetchone()
        try:
            passwords.verify(user["password_hash"] if user else dummy_hash, data.password)
        except VerificationError:
            raise HTTPException(401, "Неправильне ім’я або пароль.") from None
        if not user:
            raise HTTPException(401, "Неправильне ім’я або пароль.")
        session = create_session(connection, user["id"])
    response.headers["Cache-Control"] = "no-store"
    return session


@router.get("/me")
def me(user: User, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return {"id": user["id"], "username": user["username"]}


@router.post("/logout", status_code=204)
def logout(user: User):
    with database() as connection:
        connection.execute("DELETE FROM sessions WHERE token_hash = %s", (user["token_hash"],))
