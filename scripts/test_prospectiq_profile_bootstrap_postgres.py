"""Run coordinator cases on the existing guarded disposable PostgreSQL fixture."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from test_prospectiq_profile_bootstrap import *  # noqa
from test_prospectiq_provisioning_postgres import federation_engine
