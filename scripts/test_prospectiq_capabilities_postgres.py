"""Phase 2 matrix on the guarded disposable PostgreSQL infrastructure."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tests"))
from test_prospectiq_capabilities import *  # noqa
from test_prospectiq_federation_postgres import federation_engine
