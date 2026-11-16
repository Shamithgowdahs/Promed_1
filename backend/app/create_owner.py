import getpass
import re

from sqlalchemy import select

from backend.app.auth import hash_password
from backend.app.db import SessionLocal, initialize_database
from backend.app.models import AccountUser


def main() -> None:
    initialize_database()
    email = input("Owner email: ").strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise SystemExit("Enter a valid email address.")
    display_name = input("Owner name: ").strip()
    if not display_name or len(display_name) > 160:
        raise SystemExit("Owner name must contain 1 to 160 characters.")
    password = getpass.getpass("Owner password (minimum 12 characters): ")
    if len(password) < 12 or len(password) > 128:
        raise SystemExit("Password must contain 12 to 128 characters.")
    if password != getpass.getpass("Confirm password: "):
        raise SystemExit("Passwords did not match.")

    with SessionLocal() as db:
        if db.scalar(select(AccountUser.id).where(AccountUser.role == "owner").limit(1)) is not None:
            raise SystemExit("An owner account already exists.")
        if db.scalar(select(AccountUser.id).where(AccountUser.email == email)) is not None:
            raise SystemExit("An account already uses that email.")
        db.add(
            AccountUser(
                email=email,
                display_name=display_name,
                password_hash=hash_password(password),
                role="owner",
            )
        )
        db.commit()
    print("Owner account created. Sign in through the PROMED staff entry point.")


if __name__ == "__main__":
    main()
