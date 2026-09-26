"""
CIPHER — Authentication Layer
Password hashing, user creation, login verification, and role checks.
Sits directly on core/db.py — no raw sqlite3 calls here either.
"""

import hashlib
import hmac
import os
import logging
from datetime import datetime

from core.db import fetch_one, fetch_all, execute
from core.audit import log_action   # NEW

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# PBKDF2 params — no external deps (bcrypt/passlib) needed, keeps setup simple for judges
_HASH_ALGO = "sha256"
_ITERATIONS = 260_000
_SALT_BYTES = 16

VALID_ROLES = ("Field Investigator", "Admin")


def _hash_password(password: str, salt: bytes | None = None) -> str:
    """
    Returns a string of the form: pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>
    Storing algo+iterations+salt alongside the hash means we can change
    _ITERATIONS later without breaking old stored hashes.
    """
    if salt is None:
        salt = os.urandom(_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac(_HASH_ALGO, password.encode("utf-8"), salt, _ITERATIONS)
    return f"pbkdf2_{_HASH_ALGO}${_ITERATIONS}${salt.hex()}${dk.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    """Recompute the hash with the stored salt/iterations and compare in constant time."""
    try:
        algo_tag, iterations, salt_hex, hash_hex = stored_hash.split("$")
        algo = algo_tag.replace("pbkdf2_", "")
        salt = bytes.fromhex(salt_hex)
        iterations = int(iterations)
    except (ValueError, AttributeError):
        logger.error("Malformed password hash encountered during verification.")
        return False

    dk = hashlib.pbkdf2_hmac(algo, password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(dk.hex(), hash_hex)


def create_user(username: str, password: str, role: str, full_name: str = "") -> int:
    if role not in VALID_ROLES:
        raise ValueError(f"role must be one of {VALID_ROLES}, got {role!r}")
    if not username or not password:
        raise ValueError("username and password are required")

    password_hash = _hash_password(password)
    try:
        user_id = execute(
            "INSERT INTO users (username, password_hash, role, full_name) VALUES (?, ?, ?, ?)",
            (username, password_hash, role, full_name),
        )
    except Exception as e:
        if "UNIQUE" in str(e):
            raise ValueError(f"username '{username}' already exists") from e
        raise

    logger.info(f"User created: {username} ({role})")
    log_action("SYSTEM", "USER_CREATE", target=username, details=f"role={role}")  # NEW
    return user_id


def authenticate(username: str, password: str) -> dict | None:
    user = fetch_one("SELECT * FROM users WHERE username = ?", (username,))
    if user is None:
        logger.warning(f"Login attempt for unknown username: {username}")
        log_action(username, "LOGIN_FAILED", details="unknown username")  # NEW
        return None
    if not user["is_active"]:
        logger.warning(f"Login attempt for deactivated user: {username}")
        log_action(username, "LOGIN_FAILED", details="account inactive")  # NEW
        return None
    if not _verify_password(password, user["password_hash"]):
        logger.warning(f"Failed login attempt for user: {username}")
        log_action(username, "LOGIN_FAILED", details="bad password")  # NEW
        return None

    user.pop("password_hash", None)
    log_action(username, "LOGIN_SUCCESS")  # NEW
    return user


def get_user_by_username(username: str) -> dict | None:
    user = fetch_one("SELECT * FROM users WHERE username = ?", (username,))
    if user:
        user.pop("password_hash", None)
    return user


def list_users(active_only: bool = True) -> list[dict]:
    query = "SELECT id, username, role, full_name, created_at, is_active FROM users"
    if active_only:
        query += " WHERE is_active = 1"
    query += " ORDER BY username"
    return fetch_all(query)


def deactivate_user(username: str) -> None:
    execute("UPDATE users SET is_active = 0 WHERE username = ?", (username,))
    logger.info(f"User deactivated: {username}")
    log_action("SYSTEM", "USER_DEACTIVATE", target=username)  # NEW


def is_admin(user: dict) -> bool:
    return user.get("role") == "Admin"


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")

    # Quick self-test: create an admin if none exists, then verify login works
    existing = list_users(active_only=False)
    print(f"Existing users: {[u['username'] for u in existing]}")

    if not any(u["username"] == "admin" for u in existing):
        create_user("admin", "ChangeMe123!", "Admin", full_name="Default Admin")
        print("Created default admin user (username=admin, password=ChangeMe123!)")

    result = authenticate("admin", "ChangeMe123!")
    print("Authenticate success:" if result else "Authenticate FAILED:", result)

    result_bad = authenticate("admin", "wrongpassword")
    print("Wrong password correctly rejected:", result_bad is None)