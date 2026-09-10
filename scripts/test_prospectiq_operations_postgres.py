"""Run Phase 4 proofs against guarded disposable PG only."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tests"))
from test_prospectiq_operations import *
from test_prospectiq_federation_postgres import federation_engine
