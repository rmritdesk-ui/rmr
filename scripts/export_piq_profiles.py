"""Operator-only read-only export for a single ACTIVE canonical PIQ mapping.

Run with --database PATH --tenant-id UUID --instance ID --issuer HTTPS_ORIGIN.
Output contains profile data, not authentication material. Store it privately.
"""
import argparse
import json
import sqlite3
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rmr_platform.prospectiq_bridge.profile_export import serialize_export

def validate_issuer(issuer):
    url = urlsplit(issuer)
    if url.scheme != 'https' or not url.netloc or url.path not in ('', '/') or url.query or url.fragment or url.username:
        raise ValueError('An HTTPS issuer origin is required')

def export_profiles(database, tenant_id, instance, issuer):
    validate_issuer(issuer)
    with sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        mappings = db.execute('SELECT * FROM prospectiq_client_mappings WHERE tenant_id=? AND integration_instance_id=? AND status=?',
                              (tenant_id, instance, 'active')).fetchall()
        profiles = [dict(row) for row in db.execute('SELECT * FROM piq_target_profiles WHERE tenant_id=? ORDER BY id', (tenant_id,))]
        return serialize_export(mappings, profiles, issuer)

def export_postgres(database_url, tenant_id, instance, issuer):
    """Explicit operator export: repeatable read, read-only transaction, no ORM hooks."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    validate_issuer(issuer)
    url = make_url(database_url)
    if url.drivername != 'postgresql+psycopg': raise ValueError('PostgreSQL psycopg URL required')
    engine = create_engine(url, isolation_level='REPEATABLE READ')
    try:
        with engine.connect() as db, db.begin():
            db.exec_driver_sql('SET TRANSACTION READ ONLY')
            mappings = db.execute(text('SELECT * FROM prospectiq_client_mappings WHERE tenant_id=:tenant AND integration_instance_id=:instance AND status=:status'),
                                  {'tenant': tenant_id, 'instance': instance, 'status': 'active'}).mappings().all()
            profiles = db.execute(text('SELECT * FROM piq_target_profiles WHERE tenant_id=:tenant ORDER BY id'), {'tenant': tenant_id}).mappings().all()
            return serialize_export(mappings, profiles, issuer)
    finally: engine.dispose()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--database')
    source.add_argument('--database-url-env', help='Environment variable name, never a DSN argument')
    for flag in ('tenant-id', 'instance', 'issuer'):
        parser.add_argument('--' + flag, required=True)
    args = parser.parse_args()
    try:
        result = (export_postgres(os.environ[args.database_url_env], args.tenant_id, args.instance, args.issuer)
                  if args.database_url_env else export_profiles(args.database, args.tenant_id, args.instance, args.issuer))
    except Exception:
        raise SystemExit('Profile export failed; verify database access, issuer and active mapping. No credentials displayed.') from None
    print(json.dumps(result))
