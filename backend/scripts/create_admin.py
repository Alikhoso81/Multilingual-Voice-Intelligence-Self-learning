"""
Seed an organization + its first admin user directly in the database.

Use this to bootstrap a deployment where ALLOW_OPEN_REGISTRATION is off.

    cd backend
    .venv/Scripts/python scripts/create_admin.py "ACME Telecom" admin@acme.com 'a-strong-password' --industry telecom
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.organization import Organization
from app.models.user import User, UserRole


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("org_name")
    ap.add_argument("email")
    ap.add_argument("password")
    ap.add_argument("--full-name", default="Administrator")
    ap.add_argument("--industry", default=None)
    args = ap.parse_args()

    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == args.email).first():
            print(f"user {args.email} already exists")
            return 1
        org = Organization(name=args.org_name, industry=args.industry)
        db.add(org)
        db.flush()
        user = User(
            organization_id=org.id,
            full_name=args.full_name,
            email=args.email,
            hashed_password=hash_password(args.password),
            role=UserRole.admin,
        )
        db.add(user)
        db.commit()
        print(f"created org {org.id}  admin {user.id} <{user.email}>")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
