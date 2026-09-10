"""Phase 3 proof: reuse Phase 2 isolated RMR/bootstrap; never an installed runtime."""
import json, os, secrets, sys
from uuid import uuid4
from federation_workflow_proof import ROOT, initialize, run_rmr
if sys.argv[1] == "init":
    initialize()
    f=json.loads((ROOT/"fixture.json").read_text())
    f.update(crm_secret=secrets.token_hex(32), publicA=str(uuid4()), publicB=str(uuid4()))
    (ROOT/"fixture.json").write_text(json.dumps(f))
    path=ROOT/"nginx.conf"
    path.write_text(path.read_text().replace("phase2","phase3"))
elif sys.argv[1] == "rmr":
    f=json.loads((ROOT/"fixture.json").read_text())
    os.environ["RMR_PROSPECTIQ_CRM_KEYS_JSON"]=json.dumps({"crm-proof":f["crm_secret"]})
    run_rmr()
elif sys.argv[1] == "inspect":
    import sqlite3
    f=json.loads((ROOT/"fixture.json").read_text())
    db=sqlite3.connect("file:/tmp/federation-rmr/app.db?mode=ro",uri=True)
    counts={table:db.execute("SELECT COUNT(*) FROM "+table).fetchone()[0]
            for table in ["leads","accounts","contacts","opportunities","prospectiq_crm_receipts","prospectiq_crm_events"]}
    assert counts=={"leads":1,"accounts":0,"contacts":0,"opportunities":0,"prospectiq_crm_receipts":1,"prospectiq_crm_events":1},counts
    assert db.execute("SELECT tenant_id,source,assigned_user_id FROM leads").fetchone()==(f["tenant"],"ProspectIQ",f["user"])
    print(json.dumps({"result":"PASS","counts":counts,"tenant_and_actor_correct":True}))
else:
    raise SystemExit("Unknown isolated Phase 3 action")
