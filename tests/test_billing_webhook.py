"""Offline SetupIntent reconciliation; no Stripe/network or application DB use."""
import asyncio
import hashlib
import hmac
import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from rmr_platform.routes import billing
from rmr_platform.models import AuditEvent, BillingOperation, BillingSubscription, Tenant, TenantBillingProfile, User


class BillingWebhookTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Tenant.__table__.create(self.engine)
        User.__table__.create(self.engine)
        TenantBillingProfile.__table__.create(self.engine)
        AuditEvent.__table__.create(self.engine)
        BillingOperation.__table__.create(self.engine)
        BillingSubscription.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.db.add(Tenant(id="tenant", name="Billing test", slug="billing-test"))
        self.db.commit()
        self.profile = TenantBillingProfile(
            id="profile", tenant_id="tenant", stripe_customer_id="cus_test",
            provider="stripe", setup_status="setup_pending",
        )
        self.db.add(self.profile)
        self.db.commit()
        self.client = Mock()
        self.client.v1.setup_intents.retrieve.return_value = SimpleNamespace(
            id="seti_test", customer="cus_test", status="succeeded", payment_method="pm_test", livemode=False, created=int(time.time()),
        )
        self.client.v1.payment_methods.retrieve.return_value = SimpleNamespace(
            customer="cus_test", card=SimpleNamespace(
                brand="visa", last4="4242", exp_month=12, exp_year=2030,
            ),
        )
        async def inline(function, *args):
            return function(*args)
        for target, value in (
            ("_stripe_client", lambda: self.client),
            ("settings", SimpleNamespace(payment_provider="stripe", stripe_env="test", live_charging_enabled=False,
                monthly_billing_enabled=True, ar_billing_mode="track_only",
                stripe_webhook_secret="whsec_fixture", stripe_secret_key="sk_test_fixture", stripe_publishable_key="pk_test_fixture")),
            ("run_in_threadpool", inline),
        ):
            patcher = patch.object(billing, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)

    def deliver(self, customer="cus_test", valid=True):
        body = json.dumps({
            "id": "evt_test", "object": "event", "livemode": False, "type": "setup_intent.succeeded",
            "data": {"object": {"id": "seti_test", "object": "setup_intent", "customer": customer}},
        }).encode()
        timestamp = str(int(time.time()))
        signature = hmac.new(b"whsec_fixture", timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        async def receive():
            return {"type": "http.request", "body": body}
        request = Request({"type": "http", "headers": [
            (b"stripe-signature", f't={timestamp},v1={signature if valid else "invalid"}'.encode()),
        ]}, receive)
        return asyncio.run(billing.stripe_webhook(request, self.db))

    def test_success_reconciles_stale_state(self):
        self.assertEqual(self.deliver(), {"ok": True})
        self.db.expire_all()
        self.assertEqual(self.profile.setup_status, "ready")
        self.assertEqual(self.profile.default_payment_method_id, "pm_test")
        self.assertEqual((self.profile.card_brand, self.profile.card_last4,
                          self.profile.card_exp_month, self.profile.card_exp_year),
                         ("visa", "4242", 12, 2030))
        self.client.v1.customers.update.assert_called_once_with(
            "cus_test", {"invoice_settings": {"default_payment_method": "pm_test"}},
            options={"idempotency_key": "rmr-default-profile-seti_test"},
        )

    def test_duplicate_safe_even_after_later_replacement(self):
        self.deliver()
        self.profile.default_payment_method_id = "pm_later"
        self.db.commit()
        self.deliver()
        self.assertEqual(self.profile.default_payment_method_id, "pm_later")
        self.assertEqual(self.client.v1.customers.update.call_count, 1)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(AuditEvent)), 1)

    def test_invalid_signature_rejected(self):
        with self.assertRaises(HTTPException) as raised:
            self.deliver(valid=False)
        self.assertEqual(raised.exception.status_code, 400)
        self.client.v1.setup_intents.retrieve.assert_not_called()
        self.assertEqual(self.profile.setup_status, "setup_pending")

    def test_unmapped_and_wrong_customer_cannot_change_tenant(self):
        self.assertTrue(self.deliver(customer="cus_other")["ignored"])
        self.client.v1.setup_intents.retrieve.assert_not_called()
        self.client.v1.setup_intents.retrieve.return_value.customer = "cus_other"
        with self.assertRaises(HTTPException):
            self.deliver()
        self.assertIsNone(self.profile.default_payment_method_id)
        self.client.v1.customers.update.assert_not_called()

    def test_already_ready_matching_method_safe(self):
        self.profile.default_payment_method_id = "pm_test"
        self.profile.setup_status = "ready"
        self.profile.card_last4 = "4242"
        self.db.commit()
        self.deliver()
        self.deliver()
        self.assertEqual(self.profile.setup_status, "ready")
        self.assertEqual(self.profile.default_payment_method_id, "pm_test")
        self.assertEqual(self.client.v1.customers.update.call_count, 1)


    def test_browser_completion_then_webhook(self):
        user = SimpleNamespace(id=None, tenant_id="tenant", tenant_role="CLIENT_ADMIN", global_role=None)
        request = Request({"type":"http", "method":"POST", "headers":[(b"x-rmr-request",b"1")]})
        billing.complete_payment_method("tenant", billing.SetupIntentComplete(setup_intent_id="seti_test"), request, user, self.db)
        self.deliver()
        self.assertEqual(self.client.v1.customers.update.call_count, 1)

    def test_delayed_unprocessed_older_intent_cannot_replace_newer_card(self):
        self.deliver()
        newer = self.profile.default_payment_method_id
        self.client.v1.setup_intents.retrieve.return_value = SimpleNamespace(
            id="seti_older", customer="cus_test", status="succeeded", payment_method="pm_old", livemode=False, created=1,
        )
        billing._reconcile_setup_intent(self.db, "cus_test", "seti_older")
        self.assertEqual(self.profile.default_payment_method_id, newer)
        self.assertEqual(self.client.v1.customers.update.call_count, 1)

    def test_missing_webhook_secret_fails_closed(self):
        billing.settings.stripe_webhook_secret = ""
        with self.assertRaises(HTTPException) as raised:
            self.deliver()
        self.assertEqual(raised.exception.status_code, 503)

    def test_wrong_payment_method_customer_rejected(self):
        self.client.v1.payment_methods.retrieve.return_value.customer = "cus_wrong"
        with self.assertRaises(HTTPException):
            self.deliver()
        self.client.v1.customers.update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
