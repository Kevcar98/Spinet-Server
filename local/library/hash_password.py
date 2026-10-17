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


if __name__ == "__main__":
    first = getpass.getpass("New password: ")
    if len(first) < 8:
        sys.exit("Use at least 8 characters.")
    if getpass.getpass("Type it again: ") != first:
        sys.exit("The two didn't match. Nothing was changed.")
    print()
    print("Put this line in your .env file, replacing any SPINET_PASSWORD line:")
    print()
    print(f"SPINET_PASSWORD_HASH='{hash_password(first)}'")
