"""Explicit-only research SQL gate; same disposable DB guard as Phase 4.1."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
from scripts.test_piq_phase41_postgres import db
import test_piq_phase5_research as research

api = research.api
live = research.live
cfg = research.cfg
no_real_provider_network = research.no_real_provider_network


def test_concurrent_confirmation(db, live, api, cfg):
    research.test_concurrent_confirmation(db, live, api, cfg)


def test_complete_evidence_usage_and_move(db, live, api, cfg, monkeypatch):
    research.test_success_usage_evidence_base_and_crm(db, live, api, cfg, monkeypatch)


def test_durable_receipt_recovery(db, live, api, cfg):
    research.test_durable_receipt_recovery_without_provider(db, live, api, cfg)


def test_expired_lease_fences_late_result(db, live, api, cfg):
    research.test_lease_expiry_fences_late_result_and_reserves_unknown_cost(db, live, api, cfg)
