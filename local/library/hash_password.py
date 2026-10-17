import base64
import getpass
import hashlib
import os
import sys


def hash_password(password: str, iterations: int = 600_000) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return "pbkdf2_sha256:%d:%s:%s" % (
        iterations, base64.b64encode(salt).decode(), base64.b64encode(digest).decode())


def ask_password() -> str:
    first = getpass.getpass("New password: ")
    if len(first) < 8:
        sys.exit("Use at least 8 characters.")
    if getpass.getpass("Type it again: ") != first:
        sys.exit("The two didn't match. Nothing was changed.")
    return first


def write_env(path: str, password_hash: str) -> None:
    lines = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    kept = [l for l in lines if not l.strip().startswith(("SPINET_PASSWORD=", "SPINET_PASSWORD_HASH="))]
    has_user = any(l.strip().startswith("SPINET_USERNAME=") and l.split("=", 1)[1].strip() for l in kept)
    if not has_user:
        username = input("Username: ").strip()
        if not username:
            sys.exit("A username is needed. Nothing was changed.")
        kept = [l for l in kept if not l.strip().startswith("SPINET_USERNAME=")]
        kept.append(f"SPINET_USERNAME={username}")
    kept.append(f"SPINET_PASSWORD_HASH='{password_hash}'")
    with open(path, "r+" if os.path.exists(path) else "w", encoding="utf-8") as f:
        f.seek(0)
        f.write("\n".join(kept) + "\n")
        f.truncate()


if __name__ == "__main__":
    password_hash = hash_password(ask_password())
    if len(sys.argv) > 1:
        write_env(sys.argv[1], password_hash)
        print(f"Saved to {sys.argv[1]}. Restart the server to use it.")
    else:
        print()
        print("Put this line in your .env file, replacing any SPINET_PASSWORD line:")
        print()
        print(f"SPINET_PASSWORD_HASH='{password_hash}'")
