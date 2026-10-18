#!/usr/bin/env python3
"""
One-shot script to create the initial admin user.
Run inside the container:
    docker compose exec app python -m backend.create_admin
"""
import asyncio
import sys
from sqlalchemy import select
from backend.database import AsyncSessionLocal, engine, Base
from backend.models import User
from backend.auth import hash_password


async def main():
    username = input("Admin username: ").strip()
    if not username:
        print("Username cannot be empty.")
        sys.exit(1)

    name = input("Full name (optional): ").strip() or None
    email = input("Email (optional): ").strip() or None

    import getpass
    password = getpass.getpass("Password: ")
    if len(password) < 8:
        print("Password must be at least 8 characters.")
        sys.exit(1)
    password2 = getpass.getpass("Confirm password: ")
    if password != password2:
        print("Passwords do not match.")
        sys.exit(1)

    async with AsyncSessionLocal() as db:
        existing = await db.execute(select(User).where(User.username == username))
        if existing.scalar_one_or_none():
            print(f"User '{username}' already exists.")
            sys.exit(1)

        admin = User(
            username=username,
            name=name,
            email=email,
            hashed_password=hash_password(password),
            is_admin=True,
            must_change_password=False,
        )
        db.add(admin)
        await db.commit()
        print(f"\nAdmin user '{username}' created successfully.")


if __name__ == "__main__":
    asyncio.run(main())
