"""Offline Stripe activation and sandbox/live isolation checks."""
import asyncio
import hashlib
import hmac
import json
import time
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.requests import Request

from rmr_platform.models import Tenant, TenantBillingProfile, TenantLiveBillingProfile
from rmr_platform.routes import billing


class StripeActivationTests(unittest.TestCase):
    def setUp(self):
        self.settings = NS(payment_provider="stripe", stripe_env="test", live_charging_enabled=False,
            stripe_secret_key="sk_test_fixture", stripe_publishable_key="pk_test_fixture",
            stripe_webhook_secret="whsec_fixture", monthly_billing_enabled=False,
            ar_billing_mode="track_only")
        p = patch.object(billing, "settings", self.settings)
        p.start()
        self.addCleanup(p.stop)

    def test_demo_test_live_controls_are_independent_and_fail_closed(self):
        self.assertEqual(billing._stripe_mode(), "test")
        self.assertTrue(billing.stripe_readiness()["configuration_ready"])
        self.assertFalse(self.settings.monthly_billing_enabled)
        self.assertEqual(self.settings.ar_billing_mode, "track_only")
        self.settings.ar_billing_mode = "post_run"
        self.assertFalse(self.settings.monthly_billing_enabled)
        self.settings.monthly_billing_enabled = True
        self.assertEqual(self.settings.ar_billing_mode, "post_run")
        self.settings.stripe_env = "live"
        self.settings.stripe_secret_key = "sk_live_fixture"
        self.settings.stripe_publishable_key = "pk_live_fixture"
        self.assertIsNone(billing._stripe_mode())  # Live keys alone cannot charge.
        self.assertEqual(billing.stripe_readiness()["reason"], "live_charging_not_enabled")
        self.settings.live_charging_enabled = True
        self.assertEqual(billing._stripe_mode(), "live")
        self.settings.stripe_webhook_secret = ""
        self.assertIsNone(billing._stripe_mode())
        self.settings.stripe_webhook_secret = "whsec_fixture"
        self.settings.stripe_publishable_key = "pk_test_fixture"
        self.assertIsNone(billing._stripe_mode())
        self.assertEqual(billing.stripe_readiness()["reason"], "stripe_credentials_missing_or_mixed")

    def test_test_card_is_never_a_live_saved_card(self):
        engine = create_engine("sqlite:///:memory:")
        self.addCleanup(engine.dispose)
        for model in (Tenant, TenantBillingProfile, TenantLiveBillingProfile):
            model.__table__.create(engine)
        with Session(engine) as db:
            db.add(Tenant(id="tenant", name="Client", slug="client"))
            db.add(TenantBillingProfile(tenant_id="tenant", stripe_customer_id="cus_test",
                default_payment_method_id="pm_test", setup_status="ready", card_last4="4242"))
            db.commit()
            self.assertEqual(billing._profile(db, "tenant").stripe_customer_id, "cus_test")
            self.settings.stripe_env = "live"
            self.settings.stripe_secret_key = "sk_live_fixture"
            self.settings.stripe_publishable_key = "pk_live_fixture"
            self.settings.live_charging_enabled = True
            self.assertIsNone(billing._profile(db, "tenant"))
            live = billing._get_or_create_profile(db, "tenant")
            self.assertIsInstance(live, TenantLiveBillingProfile)
            self.assertIsNone(live.stripe_customer_id)
            db.rollback()
            self.settings.stripe_env = "test"
            self.assertEqual(billing._profile(db, "tenant").stripe_customer_id, "cus_test")

    def test_wrong_mode_webhook_rejected_before_reconciliation(self):
        payload = json.dumps({"id":"evt_fixture", "object":"event", "livemode":True,
            "type":"setup_intent.succeeded", "data":{"object":{"id":"seti_fixture",
            "customer":"cus_other"}}}).encode()
        timestamp = str(int(time.time()))
        signature = hmac.new(b"whsec_fixture", timestamp.encode()+b"."+payload,
            hashlib.sha256).hexdigest()
        async def receive():
            return {"type":"http.request", "body":payload}
        request = Request({"type":"http", "headers":[(b"stripe-signature",
            f"t={timestamp},v1={signature}".encode())]}, receive)
        with self.assertRaises(HTTPException) as error:
            asyncio.run(billing.stripe_webhook(request, None))
        self.assertEqual(error.exception.status_code, 400)
        self.settings.stripe_env = "live"
        self.settings.stripe_secret_key = "sk_live_fixture"
        self.settings.stripe_publishable_key = "pk_live_fixture"
        self.settings.live_charging_enabled = True
        test_payload = payload.replace(b'"livemode": true', b'"livemode": false')
        test_signature = hmac.new(b"whsec_fixture", timestamp.encode()+b"."+test_payload,
            hashlib.sha256).hexdigest()
        async def test_receive():
            return {"type":"http.request", "body":test_payload}
        test_request = Request({"type":"http", "headers":[(b"stripe-signature",
            f"t={timestamp},v1={test_signature}".encode())]}, test_receive)
        with self.assertRaises(HTTPException) as error:
            asyncio.run(billing.stripe_webhook(test_request, None))
        self.assertEqual(error.exception.status_code, 400)

    def test_owner_readiness_contains_no_credentials(self):
        owner = NS(global_role="RMR_OWNER")
        report = billing.owner_stripe_readiness(owner)
        self.assertTrue(report["configuration_ready"])
        self.assertNotIn("sk_test_fixture", repr(report))
        self.assertNotIn("pk_test_fixture", repr(report))
        self.assertNotIn("whsec_fixture", repr(report))
        with self.assertRaises(HTTPException) as error:
            billing.owner_stripe_readiness(NS(global_role="CLIENT_ADMIN"))
        self.assertEqual(error.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
