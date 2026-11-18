"""Manage dashboard logins.

    python manage_users.py add <username> [--name "Full Name"]   # prompts for password
    python manage_users.py passwd <username>                     # reset password
"""
import argparse
import getpass

from db import auth

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["add", "passwd"])
    parser.add_argument("username")
    parser.add_argument("--name", default=None)
    args = parser.parse_args()
    password = getpass.getpass("Password (min 8 chars): ")
    if password != getpass.getpass("Repeat password: "):
        raise SystemExit("Passwords do not match.")
    auth.set_password(args.username, password, args.name)
    print(f"User '{args.username}' saved.")
