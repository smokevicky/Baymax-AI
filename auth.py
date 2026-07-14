import os
import re
import hashlib
import sqlite3
from typing import Tuple

DB_PATH = "/tmp/users.db" if os.environ.get("VERCEL") else "users.db"

def init_db():
    """
    Initializes the SQLite database, creates the users table if it does not exist,
    and migrates the schema if required.
    """
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Migration: Check if email column exists
        cursor.execute("PRAGMA table_info(users)")
        columns = [info[1] for info in cursor.fetchall()]
        if "email" not in columns:
            try:
                cursor.execute("ALTER TABLE users ADD COLUMN email TEXT")
                cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email)")
            except Exception as e:
                print(f"Migration error (adding email column): {e}")
        conn.commit()

# Initialize database immediately upon import
init_db()

def hash_password(password: str, salt: str = None) -> Tuple[str, str]:
    """
    Hashes a password using PBKDF2-HMAC-SHA256 with 100,000 iterations.
    If no salt is provided, a new one is generated.
    Returns: (password_hash_hex, salt_hex)
    """
    if salt is None:
        # Generate 16 bytes cryptographically secure salt
        salt_bytes = os.urandom(16)
        salt = salt_bytes.hex()
    else:
        salt_bytes = bytes.fromhex(salt)

    iterations = 100000
    hash_bytes = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_bytes,
        iterations
    )
    return hash_bytes.hex(), salt

def create_user(username: str, email: str) -> Tuple[bool, str]:
    """
    Creates a new user account with unique username and email.
    Validates username and email format.
    Returns: (success_status, message)
    """
    username = username.strip()
    
    # Validate username: alphanumeric and underscores, length 3 to 20
    if not re.match(r"^[a-zA-Z0-9_]{3,20}$", username):
        return False, "Username must be between 3 and 20 characters and contain only letters, numbers, or underscores."

    # Validate email format
    if not email:
        return False, "Email address is required."
    
    email = email.strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return False, "Invalid email address format."

    password_hash, salt = "", ""

    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (username, password_hash, salt, email) VALUES (?, ?, ?, ?)",
                (username.lower(), password_hash, salt, email)
            )
            conn.commit()
        return True, "User registered successfully."
    except sqlite3.IntegrityError as e:
        error_msg = str(e).lower()
        if "email" in error_msg:
            return False, "Email address is already linked to another account."
        return False, "Username is already taken."
    except Exception as e:
        return False, f"Database error: {str(e)}"

def verify_user(email: str) -> bool:
    """
    Verifies user credentials by checking if the email exists.
    Returns True if valid, False otherwise.
    """
    email = email.strip().lower()
    if not email:
        return False

    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM users WHERE email = ?",
                (email,)
            )
            row = cursor.fetchone()
            
        return row is not None
    except Exception as e:
        print(f"Error during verification: {e}")
        return False

def link_email(username: str, email: str) -> Tuple[bool, str]:
    """
    Links/updates the email address for a given user.
    Checks for email format validation and database integrity (uniqueness).
    """
    username = username.strip().lower()
    email = email.strip().lower() if email else ""

    if not email:
        try:
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE users SET email = NULL WHERE username = ?",
                    (username,)
                )
                conn.commit()
            return True, "Email unlinked successfully."
        except Exception as e:
            return False, f"Database error: {str(e)}"

    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return False, "Invalid email address format."

    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET email = ? WHERE username = ?",
                (email, username)
            )
            conn.commit()
        return True, "Email linked successfully."
    except sqlite3.IntegrityError:
        return False, "Email address is already linked to another account."
    except Exception as e:
        return False, f"Database error: {str(e)}"

def get_user_profile(username: str) -> Tuple[bool, dict]:
    """
    Retrieves the username and email details for the user.
    """
    username = username.strip().lower()
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT username, email FROM users WHERE username = ?",
                (username,)
            )
            row = cursor.fetchone()
        if row:
            return True, {"username": row[0], "email": row[1] or ""}
        return False, {"message": "User not found"}
    except Exception as e:
        return False, {"message": f"Database error: {str(e)}"}

def get_username_by_identifier(identifier: str) -> str:
    """
    Finds the canonical lowercase username for a given username or email identifier.
    """
    identifier = identifier.strip().lower()
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT username FROM users WHERE username = ? OR email = ?",
                (identifier, identifier)
            )
            row = cursor.fetchone()
        if row:
            return row[0]
        return identifier
    except Exception:
        return identifier

def hmac_compare(a: str, b: str) -> bool:
    """
    Constant time comparison helper.
    """
    return hashlib.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
