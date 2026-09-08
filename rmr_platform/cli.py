from __future__ import annotations

import argparse
import getpass
import json
import sys

from sqlalchemy import func, select

from .backup import create_backup, restore_backup
from .db import db_session
from .migrations import migrate, migration_status
from .models import ServiceCatalog, Tenant, User
from .security import hash_password, verify_password
from .seed import seed_demo, seed_reference_data


def main() -> int:
    parser = argparse.ArgumentParser(description="RMR Platform maintenance CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate")
    sub.add_parser("seed")
    sub.add_parser("seed-reference")
    sub.add_parser("reset-demo")
    sub.add_parser("status")
    backup_parser = sub.add_parser("backup")
    backup_parser.add_argument("--output", default=None)
    restore_parser = sub.add_parser("restore")
    restore_parser.add_argument("source")
    recover_parser = sub.add_parser("recover-owner", help="Securely reset an RMR Owner password from the server console")
    recover_parser.add_argument("--email", required=True)
    args = parser.parse_args()

    from .config import settings
    if args.command in {"seed", "reset-demo"} and settings.environment == "production":
        parser.error("Demo seeding is disabled in production; use migrate for reference data.")

    if args.command == "migrate":
        migrate()
        print(json.dumps(migration_status(), indent=2))
        return 0
    if args.command == "seed-reference":
        migrate()
        with db_session() as db:
            seed_reference_data(db)
        print("Governed reference data is present.")
        return 0
    if args.command == "seed":
        migrate()
        with db_session() as db:
            seed_demo(db, reset=False)
        print("Demo/reference data is present.")
        return 0
    if args.command == "reset-demo":
        migrate()
        with db_session() as db:
            seed_demo(db, reset=True)
        print("Demo/reference data reset complete.")
        return 0
    if args.command == "status":
        from .migrations import require_current_schema
        require_current_schema()
        with db_session() as db:
            users = db.scalar(select(func.count(User.id))) or 0
            tenants = db.scalar(select(func.count(Tenant.id))) or 0
            services = db.scalar(select(func.count(ServiceCatalog.id))) or 0
        print(json.dumps({"migrations": migration_status(), "users": users, "tenants": tenants, "services": services}, indent=2))
        return 0
    if args.command == "backup":
        path = create_backup(args.output)
        print(path)
        return 0
    if args.command == "restore":
        safety = restore_backup(args.source)
        print(f"Restore complete. Pre-restore safety backup: {safety}")
        return 0
    if args.command == "recover-owner":
        migrate()
        email = args.email.strip().lower()
        password = getpass.getpass("New RMR Owner password (minimum 12 characters): ")
        confirm = getpass.getpass("Confirm new password: ")
        if password != confirm:
            print("Passwords do not match.", file=sys.stderr)
            return 2
        if len(password) < 12:
            print("Password must contain at least 12 characters.", file=sys.stderr)
            return 2
        with db_session() as db:
            user = db.scalar(select(User).where(User.email == email, User.global_role == "RMR_OWNER"))
            if not user:
                print("RMR Owner account not found.", file=sys.stderr)
                return 3
            user.password_hash = hash_password(password)
            user.must_change_password = False
            if not verify_password(password, user.password_hash):
                print("Password verification failed; no change was committed.", file=sys.stderr)
                return 4
        print("RMR Owner password reset successfully. The password was not displayed or logged.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
