"""Sandbox-only payment tests: all Stripe and database operations are mocked."""
import unittest
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from fastapi import HTTPException
from starlette.requests import Request
from stripe import StripeError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from rmr_platform.models import AuditEvent, BillingOperation, BillingSubscription, ServiceCatalog, TenantService, Tenant, TenantBillingProfile, User

from rmr_platform.routes import billing


class BillingSetupTests(unittest.TestCase):
    def setUp(self):
        self.settings = NS(payment_provider="stripe", stripe_env="test", live_charging_enabled=False,
            monthly_billing_enabled=True, ar_billing_mode="track_only",
            stripe_secret_key="sk_test_fixture", stripe_publishable_key="pk_test_fixture", stripe_webhook_secret="whsec_fixture")
        self.user = NS(id=None, tenant_id="tenant", tenant_role="CLIENT_ADMIN", global_role=None)
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{self.temp.name}/billing.db", connect_args={"check_same_thread": False, "timeout": 10})
        for model in (Tenant, User, TenantBillingProfile, AuditEvent, BillingOperation, BillingSubscription, ServiceCatalog, TenantService):
            model.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.tenant = Tenant(id="tenant",slug="test-tenant",name="Test tenant")
        self.db.add(self.tenant)
        self.db.commit()
        self.profile = TenantBillingProfile(id="profile",tenant_id="tenant",setup_status="ready",stripe_customer_id="cus_saved",default_payment_method_id="pm_saved",card_brand="visa",card_last4="4242",card_exp_month=12,card_exp_year=2030)
        self.db.add(self.profile)
        self.db.commit()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.client = Mock()
        self.client.v1.payment_intents.create.return_value = NS(id="pi_test", status="succeeded", amount=100, currency="usd", client_secret="MUST_NOT_RETURN")
        for name, value in [("settings", self.settings), ("StripeClient", Mock(return_value=self.client))]:
            p = patch.object(billing, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.request = Request({"type":"http", "method":"POST", "headers":[(b"x-rmr-request",b"1")]})
        self.op = billing.prepare_operation("setup","tenant",billing.PrepareOperation(),self.request,self.user,self.db)["operation_id"]
        billing.StripeClient.reset_mock()

    def test_save_and_replacement_preserved(self):
        op = billing.prepare_operation("setup","tenant",billing.PrepareOperation(),self.request,self.user,self.db)["operation_id"]
        self.client.v1.setup_intents.create.return_value = NS(id="seti_saved",client_secret="fixture")
        billing.create_setup_intent("tenant", billing.OperationRequest(operation_id=op), self.request, self.user, self.db)
        self.assertEqual(self.profile.setup_status,"ready")
        self.assertEqual(self.profile.default_payment_method_id,"pm_saved")
        self.profile.default_payment_method_id = None
        self.profile.card_last4 = ""
        self.db.commit()
        op = billing.prepare_operation("setup","tenant",billing.PrepareOperation(previous_operation_id=op),self.request,self.user,self.db)["operation_id"]
        billing.create_setup_intent("tenant", billing.OperationRequest(operation_id=op), self.request, self.user, self.db)
        self.assertEqual(self.profile.setup_status,"setup_pending")
        self.client.v1.setup_intents.retrieve.return_value = NS(id="seti_saved",customer="cus_saved",status="succeeded",payment_method="pm_new",livemode=False,created=2000000000)
        self.client.v1.payment_methods.retrieve.return_value = NS(customer="cus_saved",card=NS(brand="visa",last4="1111",exp_month=12,exp_year=2031))
        billing.complete_payment_method("tenant", NS(setup_intent_id="seti_saved"), self.request, self.user, self.db)
        self.assertEqual(self.profile.default_payment_method_id,"pm_new")
        self.assertEqual(self.profile.setup_status,"ready")
        self.client.v1.payment_intents.create.assert_not_called()


    def test_concurrent_setup_same_operation(self):
        op=billing.prepare_operation("setup","tenant",billing.PrepareOperation(),self.request,self.user,self.db)["operation_id"]
        result=NS(id="seti_concurrent",client_secret="fixture")
        self.client.v1.setup_intents.create.return_value=result
        self.client.v1.setup_intents.retrieve.return_value=result
        self.db.rollback()
        barrier=threading.Barrier(2)
        def run():
            with Session(self.engine) as db:
                barrier.wait()
                return billing.create_setup_intent("tenant",billing.OperationRequest(operation_id=op),self.request,self.user,db)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:run(),range(2)))
        self.assertEqual(results[0],results[1])
        self.assertEqual(self.client.v1.setup_intents.create.call_count,1)

    def test_mixed_modes_fail_safely(self):
        for sk,pk in [("sk_test_fixture","pk_live_fixture"),("sk_live_fixture","pk_test_fixture")]:
            self.settings.stripe_secret_key=sk;self.settings.stripe_publishable_key=pk
            with self.assertRaises(HTTPException):billing.create_setup_intent("tenant", billing.OperationRequest(operation_id=self.op), self.request, self.user, self.db)
            self.assertFalse(billing.billing_status("tenant",self.user,self.db)["stripe_configured"])
        self.client.v1.payment_intents.create.assert_not_called()

    def test_uncertain_operation_expired(self):
        self.db.get(BillingOperation,self.op).created_at=datetime.now(timezone.utc)-timedelta(hours=24)
        self.db.commit()
        with self.assertRaises(HTTPException):billing.create_setup_intent("tenant", billing.OperationRequest(operation_id=self.op), self.request, self.user, self.db)
        self.client.v1.payment_intents.create.assert_not_called()

    def test_setup_retry_and_cancel_preserve_card(self):
        op=billing.prepare_operation("setup","tenant",billing.PrepareOperation(),self.request,self.user,self.db)["operation_id"]
        result=NS(id="seti_retry",client_secret="NEVER_STORE")
        self.client.v1.setup_intents.create.side_effect=[StripeError("timeout"),result]
        self.client.v1.setup_intents.retrieve.return_value=result
        def run():return billing.create_setup_intent("tenant",billing.OperationRequest(operation_id=op),self.request,self.user,self.db)
        with self.assertRaises(HTTPException):run()
        self.assertEqual(self.profile.default_payment_method_id,"pm_saved")
        run();run()
        self.assertEqual(self.profile.setup_status,"ready")
        self.assertEqual(self.profile.default_payment_method_id,"pm_saved")
        calls=self.client.v1.setup_intents.create.call_args_list
        self.assertEqual(calls[0],calls[1])
        self.assertEqual(len(calls),2)
        self.assertNotIn("NEVER_STORE",str(self.db.get(BillingOperation,op).result_data))


if __name__ == "__main__":
    unittest.main()
