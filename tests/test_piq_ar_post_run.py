"""Offline post-run settlement tests; Stripe and providers are fully mocked."""
import unittest
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi import HTTPException
from stripe import StripeError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from rmr_platform.models import Tenant, ServiceCatalog, TenantService, TenantBillingProfile, TenantLiveBillingProfile, BillingOperation
from rmr_platform.prospectiq_bridge import ar_billing
from rmr_platform.routes import billing


class PostRunSettlementTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        self.addCleanup(engine.dispose)
        for model in (Tenant, ServiceCatalog, TenantService, TenantBillingProfile, BillingOperation):
            model.__table__.create(engine)
        self.db = Session(engine)
        self.addCleanup(self.db.close)
        self.tenant, self.other = str(uuid4()), str(uuid4())
        self.client, self.run = uuid4(), uuid4()
        self.db.add_all([Tenant(id=self.tenant, name="One", slug="one"),
                         Tenant(id=self.other, name="Two", slug="two"),
                         ServiceCatalog(code="piq_enhancement", name="Enhancement", cadence="usage")])
        self.db.flush()
        self.db.add(TenantService(tenant_id=self.tenant, service_code="piq_enhancement",
                                  status="active", cadence="usage", usage_price_cents=20,
                                  contract_price_cents=0))
        self.db.add(TenantBillingProfile(tenant_id=self.tenant, stripe_customer_id="cus_test",
                                          default_payment_method_id="pm_test", setup_status="ready"))
        self.db.commit()
        self.stripe = Mock()
        def create(params, options):
            intent = NS(id="pi_test", status="succeeded", amount=params["amount"],
                        currency=params["currency"], customer=params["customer"],
                        livemode=False, metadata=params["metadata"])
            self.stripe.v1.payment_intents.retrieve.return_value = intent
            return intent
        self.stripe.v1.payment_intents.create.side_effect = create
        for name, value in (("_context", lambda *args: None), ("_stripe_mode", lambda: "test"),
                            ("_stripe_client", lambda: self.stripe),
                            ("settings", NS(ar_billing_mode="post_run"))):
            p = patch.object(ar_billing, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.freeze_payload = ar_billing.PostRunFreeze(
            grant_id=uuid4(), mapping_id=uuid4(), mapping_version=1,
            rmr_tenant_id=self.tenant, rmr_user_id=uuid4(), piq_client_id=self.client,
            piq_user_id=uuid4(), lead_ids=[uuid4() for _ in range(3)],
            confirmation_hash="a" * 64, estimate_min_cents_per_record=40,
            estimate_max_cents_per_record=100)

    def frozen(self):
        return ar_billing.freeze_post_run(self.db, self.freeze_payload, NS())

    def settlement(self, op, cost="1.55", status="completed", **overrides):
        return ar_billing.PostRunSettlement(operation_id=op["operation_id"],
            piq_run_id=self.run, rmr_tenant_id=self.tenant, piq_client_id=self.client,
            run_status=status, actual_provider_cost_usd=cost, **overrides)

    def test_freeze_then_research_then_one_combined_charge(self):
        frozen = self.frozen()
        self.assertEqual((frozen["unit_price_cents"], frozen["enhancement_fee_cents"]), (20, 60))
        self.stripe.v1.payment_intents.create.assert_not_called()
        self.assertEqual(self.frozen()["operation_id"], frozen["operation_id"])
        link = ar_billing.PostRunLink(operation_id=frozen["operation_id"],
            piq_run_id=self.run, rmr_tenant_id=self.tenant, piq_client_id=self.client)
        self.assertEqual(ar_billing.link_post_run(self.db, link)["piq_run_id"], str(self.run))
        assignment = self.db.query(TenantService).one()
        assignment.usage_price_cents = 99
        self.db.commit()
        paid = ar_billing.settle_post_run(self.db, self.settlement(frozen))
        self.assertEqual((paid["status"], paid["actual_provider_cost_usd"],
                          paid["final_amount_cents"]), ("paid", "1.55", 215))
        self.assertEqual(self.stripe.v1.payment_intents.create.call_args.args[0]["amount"], 215)
        self.assertEqual(self.stripe.v1.payment_intents.create.call_count, 1)
        self.assertEqual(ar_billing.settle_post_run(self.db, self.settlement(frozen))["status"], "paid")
        self.assertEqual(self.stripe.v1.payment_intents.create.call_count, 1)

    def test_pending_cost_failed_run_and_below_minimum_do_not_charge(self):
        frozen = self.frozen()
        self.assertEqual(ar_billing.settle_post_run(self.db,
            self.settlement(frozen, cost=None))["status"], "pending_cost")
        self.stripe.v1.payment_intents.create.assert_not_called()
        self.assertEqual(ar_billing.settle_post_run(self.db,
            self.settlement(frozen))["status"], "paid")
        self.stripe.v1.payment_intents.create.reset_mock()
        later = self.freeze_payload.model_copy(update={"confirmation_hash": "b" * 64})
        other = ar_billing.freeze_post_run(self.db, later, NS())
        self.assertEqual(ar_billing.settle_post_run(self.db,
            self.settlement(other, status="partial"))["status"], "no_auto_charge")
        self.stripe.v1.payment_intents.create.assert_not_called()
        final = ar_billing.freeze_post_run(self.db,
            self.freeze_payload.model_copy(update={"confirmation_hash": "c" * 64,
                "lead_ids": [self.freeze_payload.lead_ids[0]]}), NS())
        self.run = uuid4()
        self.assertEqual(ar_billing.settle_post_run(self.db,
            self.settlement(final, cost="0.01"))["status"], "below_minimum")
        self.stripe.v1.payment_intents.create.assert_not_called()

    def test_known_payment_failure_keeps_amount_and_explicit_retry_uses_same_operation(self):
        frozen = self.frozen()
        original = self.stripe.v1.payment_intents.create.side_effect
        def failed(params, options):
            intent = original(params, options)
            intent.status = "requires_payment_method"
            return intent
        self.stripe.v1.payment_intents.create.side_effect = failed
        due = ar_billing.settle_post_run(self.db, self.settlement(frozen))
        self.assertEqual((due["status"], due["final_amount_cents"]), ("payment_failed", 215))
        self.assertEqual(ar_billing.settle_post_run(self.db, self.settlement(frozen))["status"], "payment_failed")
        self.assertEqual(self.stripe.v1.payment_intents.create.call_count, 1)
        self.stripe.v1.payment_intents.create.side_effect = lambda params, options: NS(
            id="pi_retry", status="succeeded", amount=params["amount"],
            currency="usd", customer=params["customer"], livemode=False, metadata=params["metadata"])
        self.assertEqual(ar_billing.retry_post_run(self.db, self.settlement(frozen))["status"], "paid")
        self.assertEqual(self.stripe.v1.payment_intents.create.call_count, 2)
        self.assertEqual(self.stripe.v1.payment_intents.create.call_args.args[0]["amount"], 215)

    def test_cross_tenant_and_track_only_never_charge(self):
        frozen = self.frozen()
        changed = self.settlement(frozen).model_copy(update={"rmr_tenant_id": self.other})
        with self.assertRaises(HTTPException):
            ar_billing.settle_post_run(self.db, changed)
        with patch.object(ar_billing, "settings", NS(ar_billing_mode="track_only")):
            with self.assertRaises(HTTPException):
                ar_billing.settle_post_run(self.db, self.settlement(frozen))
        self.stripe.v1.payment_intents.create.assert_not_called()

    def test_duplicate_webhook_reconciles_same_intent_without_new_charge(self):
        frozen = self.frozen()
        ar_billing.settle_post_run(self.db, self.settlement(frozen))
        remote = self.stripe.v1.payment_intents.retrieve.return_value
        first = ar_billing.reconcile_post_run_webhook(self.db, remote)
        second = ar_billing.reconcile_post_run_webhook(self.db, remote)
        self.assertEqual(first, {"ok": True})
        self.assertEqual(second, {"ok": True})
        self.assertEqual(self.stripe.v1.payment_intents.create.call_count, 1)
        self.assertEqual(self.db.get(BillingOperation, frozen["operation_id"]).result_data["status"], "paid")

    def test_decline_exception_with_intent_is_recorded_without_rerunning_research(self):
        frozen = self.frozen()
        decline = StripeError("declined")
        decline.error = NS(payment_intent=NS(id="pi_decline"))
        self.stripe.v1.payment_intents.create.side_effect = decline
        self.stripe.v1.payment_intents.retrieve.return_value = NS(
            id="pi_decline", status="requires_payment_method", amount=215,
            currency="usd", customer="cus_test", livemode=False,
            metadata={"purpose":"rmr_piq_adaptive_research_post_run",
                      "tenant_id":self.tenant,"billing_operation_id":frozen["operation_id"],
                      "piq_run_id":str(self.run)})
        result = ar_billing.settle_post_run(self.db, self.settlement(frozen))
        self.assertEqual((result["status"], result["final_amount_cents"]), ("payment_failed", 215))
        self.assertEqual(self.stripe.v1.payment_intents.create.call_count, 1)

    def test_live_settlement_requires_separate_live_saved_card(self):
        TenantLiveBillingProfile.__table__.create(self.db.bind)
        with patch.object(ar_billing, "_stripe_mode", lambda: "live"), patch.object(
            billing, "settings", NS(stripe_env="live")):
            frozen = self.frozen()
            self.assertEqual(ar_billing.settle_post_run(self.db,
                self.settlement(frozen))["status"], "amount_due")
            self.stripe.v1.payment_intents.create.assert_not_called()
            self.db.add(TenantLiveBillingProfile(tenant_id=self.tenant,
                stripe_customer_id="cus_live", default_payment_method_id="pm_live",
                setup_status="ready"))
            self.db.commit()
            self.stripe.v1.payment_intents.create.side_effect = lambda params, options: NS(
                id="pi_live", status="succeeded", amount=params["amount"],
                currency="usd", customer=params["customer"], livemode=True,
                metadata=params["metadata"])
            self.assertEqual(ar_billing.settle_post_run(self.db,
                self.settlement(frozen))["status"], "paid")
            params = self.stripe.v1.payment_intents.create.call_args.args[0]
            self.assertEqual((params["customer"], params["payment_method"]),
                ("cus_live", "pm_live"))

    def test_legacy_prepayment_cannot_charge_with_live_keys(self):
        with patch.object(ar_billing, "_stripe_mode", lambda: "live"), patch.object(
            ar_billing, "settings", NS(ar_billing_mode="payment_required")):
            with self.assertRaises(HTTPException) as error:
                ar_billing.quote(self.db, self.freeze_payload, NS())
            self.assertEqual(error.exception.status_code, 403)
            self.stripe.v1.payment_intents.create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
