"""Offline tenant-wide billing exemption regressions; no Stripe requests."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from starlette.requests import Request

from rmr_platform import billing_policy, billing_subscriptions as monthly, billing_renewals
from rmr_platform.models import (AuditEvent, BillingOperation, BillingSubscription,
                                 ServiceCatalog, Tenant, TenantBillingProfile, TenantService, User)
from rmr_platform.routes import billing
from rmr_platform.migrations import apply_billing_exemption_schema


class BillingExemptionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        self.addCleanup(self.engine.dispose)
        for model in (Tenant, User, TenantBillingProfile, ServiceCatalog, TenantService,
                      BillingOperation, BillingSubscription, AuditEvent):
            model.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.addCleanup(self.db.close)
        self.db.add_all([Tenant(id="one", name="One", slug="one"),
                         Tenant(id="two", name="Two", slug="two"),
                         ServiceCatalog(code="crm", name="CRM")])
        self.db.flush()
        self.db.add(TenantService(tenant_id="one", service_code="crm", status="active",
                                  cadence="monthly", contract_price_cents=1000))
        self.db.commit()
        self.owner = NS(id=None, global_role="RMR_OWNER")
        self.client = NS(id="client", global_role=None, tenant_id="one", tenant_role="CLIENT_ADMIN")
        self.request = Request({"type": "http", "method": "PATCH",
                                "headers": [(b"x-rmr-request", b"1")]})
        self.settings = NS(monthly_billing_enabled=True, ar_billing_mode="post_run")
        policy_patch = patch.object(billing_policy, "settings", self.settings)
        policy_patch.start(); self.addCleanup(policy_patch.stop)

    def toggle(self, value):
        return billing.update_billing_exemption("one", billing.BillingExemptionUpdate(
            billing_exempt=value), self.request, self.owner, self.db)

    def test_default_and_global_off_keep_existing_non_charge_behavior(self):
        self.assertFalse(billing_policy.effective_billing_policy(self.db, "one")["billing_exempt"])
        self.settings.monthly_billing_enabled = False
        self.settings.ar_billing_mode = "track_only"
        self.assertFalse(billing_policy.effective_billing_policy(self.db, "one")["payment_method_required"])
        with patch.object(monthly, "settings", self.settings):
            self.assertFalse(monthly.onboarding_required(self.db, self.client))
            monthly.require_paid_service(self.db, "one", "crm", self.client)

    def test_additive_migration_preserves_existing_rows_and_defaults_false(self):
        legacy = create_engine("sqlite:///:memory:")
        try:
            with legacy.begin() as connection:
                connection.execute(text("CREATE TABLE tenant_billing_profiles (id VARCHAR(36) PRIMARY KEY, tenant_id VARCHAR(36) NOT NULL UNIQUE)"))
                connection.execute(text("INSERT INTO tenant_billing_profiles (id, tenant_id) VALUES ('old', 'one')"))
            apply_billing_exemption_schema(bind=legacy)
            apply_billing_exemption_schema(bind=legacy)
            with legacy.connect() as connection:
                self.assertEqual(connection.execute(text(
                    "SELECT billing_exempt FROM tenant_billing_profiles WHERE id='old'"
                )).scalar_one(), 0)
        finally:
            legacy.dispose()

    def test_exempt_client_skips_card_and_monthly_gate_other_client_keeps_mode(self):
        self.toggle(True)
        policy = billing_policy.effective_billing_policy(self.db, "one")
        self.assertEqual((policy["ar_billing_mode"], policy["monthly_billing_required"],
                          policy["payment_method_required"]), ("track_only", False, False))
        with patch.object(monthly, "settings", self.settings):
            self.assertFalse(monthly.onboarding_required(self.db, self.client))
            monthly.require_paid_service(self.db, "one", "crm", self.client)
        state = billing.billing_status("one", self.client, self.db)
        self.assertEqual(state["monthly"]["stage"], "billing_exempt")
        self.assertFalse(state["monthly"]["billing_required"])
        self.assertFalse(state["subscription_activation_available"])
        with self.assertRaises(HTTPException) as blocked:
            billing.activate_subscription("one", billing.ActivateSubscription(
                operation_id="unused", confirmed=True, quote_hash="unused"),
                self.request, self.client, self.db)
        self.assertEqual(blocked.exception.status_code, 403)
        with self.assertRaises(HTTPException) as blocked:
            billing.prepare_operation("setup", "one", billing.PrepareOperation(),
                                      self.request, self.client, self.db)
        self.assertEqual(blocked.exception.status_code, 403)
        billing_renewals.record_change(self.db, "one")
        billing_renewals.reconcile(self.db, "one")
        self.assertEqual(list(self.db.scalars(select(BillingOperation))), [])
        self.assertTrue(billing_policy.effective_billing_policy(self.db, "two")["payment_method_required"])
        with self.assertRaises(HTTPException) as error:
            billing_policy.require_billing_allowed(self.db, "one")
        self.assertEqual(error.exception.status_code, 403)
        self.assertEqual(self.db.scalar(select(AuditEvent).where(
            AuditEvent.event_type == "billing.exemption_changed")).tenant_id, "one")

    def test_client_cannot_change_exemption_and_removal_is_not_retroactive(self):
        with self.assertRaises(HTTPException) as error:
            billing.update_billing_exemption("one", billing.BillingExemptionUpdate(
                billing_exempt=True), self.request, self.client, self.db)
        self.assertEqual(error.exception.status_code, 403)
        self.toggle(True)
        # Old track-only runs have no settlement operation; policy changes affect new runs only.
        self.toggle(False)
        self.assertEqual(billing_policy.effective_billing_policy(self.db, "one")["ar_billing_mode"], "post_run")

    def test_active_subscription_blocks_exemption(self):
        operation = BillingOperation(tenant_id="one", kind="subscription", mode="test",
                                     result_data={"subscription_id": "sub_existing"})
        self.db.add(operation); self.db.flush()
        self.db.add(BillingSubscription(tenant_id="one", mode="test", operation_id=operation.id,
                                        stripe_customer_id="cus_existing", stripe_subscription_id="sub_existing",
                                        monthly_amount_cents=1000, status="active"))
        self.db.commit()
        with self.assertRaises(HTTPException) as error:
            self.toggle(True)
        self.assertEqual(error.exception.status_code, 409)
        self.assertFalse(billing_policy.effective_billing_policy(self.db, "one")["billing_exempt"])

    def test_uncertain_stripe_operation_blocks_exemption(self):
        self.db.add(BillingOperation(tenant_id="one", kind="piq_ar_post_run", mode="test",
                                     active_slot="pending", result_data={"status": "payment_attempted"}))
        self.db.commit()
        with self.assertRaises(HTTPException) as error:
            self.toggle(True)
        self.assertEqual(error.exception.status_code, 409)
        self.assertFalse(billing_policy.effective_billing_policy(self.db, "one")["billing_exempt"])


if __name__ == "__main__":
    unittest.main()
