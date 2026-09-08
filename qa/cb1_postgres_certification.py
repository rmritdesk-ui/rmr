from __future__ import annotations
import json, os, sys, uuid
from pathlib import Path
from sqlalchemy import inspect, text

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from rmr_platform import db
from rmr_platform.cb1_migration import apply as apply_migration

result={"status":"failed","release":"5.3.1-final-production-corrections-po1","checks":[]}
def check(cid,ok,detail=""):
    result["checks"].append({"id":cid,"pass":bool(ok),"detail":detail})
    if not ok: raise AssertionError(f"{cid}: {detail}")
try:
    check("PG-001",db.engine.dialect.name=="postgresql",db.engine.dialect.name)
    apply_migration()
    names=set(inspect(db.engine).get_table_names())
    required={"cb1_audit_events","cb1_client_admin_invites","cb1_order_forms","cb1_entitlements","cb1_provider_connections","cb1_campaigns","cb1_messages","cb1_social_content","cb1_export_jobs"}
    check("PG-002",required.issubset(names),"missing="+",".join(sorted(required-names)))
    marker="cb1-pg-"+uuid.uuid4().hex
    with db.engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS cb1_postgres_certification (marker text primary key)"))
        conn.execute(text("INSERT INTO cb1_postgres_certification(marker) VALUES (:m)"),{"m":marker})
        found=conn.execute(text("SELECT marker FROM cb1_postgres_certification WHERE marker=:m"),{"m":marker}).scalar_one()
    check("PG-003",found==marker,found)
    result.update(status="passed",passed=len(result["checks"]),failed=0)
except Exception as exc:
    result.update(error=str(exc),passed=sum(1 for c in result["checks"] if c["pass"]),failed=1)
Path("/data/cb1-postgres-certification.json").write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
raise SystemExit(0 if result["status"]=="passed" else 1)
