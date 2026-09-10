"""Phase 3 real receiver/concurrency on guarded disposable PostgreSQL 16."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tests"))
from test_prospectiq_crm import *  # noqa
from test_prospectiq_federation_postgres import federation_engine
