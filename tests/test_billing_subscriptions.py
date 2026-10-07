"""Isolated DB + mocked Stripe monthly onboarding and entitlement regression."""
import asyncio
import hashlib
import hmac
import json
import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from starlette.requests import Request
from stripe import StripeObject, StripeError

from rmr_platform import billing_subscriptions as monthly
from rmr_platform import billing_renewals
from rmr_platform.config import _enabled_unless_explicitly_disabled
from rmr_platform.models import (Tenant, User, TenantService, ServiceCatalog, TenantBillingProfile, TenantLiveBillingProfile,
    BillingOperation, BillingSubscription, BillingServicePrice, AuditEvent)
from rmr_platform.routes import billing


class MonthlyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{self.temp.name}/billing.db", connect_args={"check_same_thread": False, "timeout": 15})
        for model in (Tenant, User, ServiceCatalog, TenantService, TenantBillingProfile, BillingOperation, BillingSubscription, BillingServicePrice, AuditEvent):
            model.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.db.add_all([Tenant(id="tenant", name="Test", slug="test", status="live"), Tenant(id="other", name="Other", slug="other")])
        for code in ("piq_access", "piq_enhancement", "crm"):
            self.db.add(ServiceCatalog(code=code, name=code, standard_price_cents=999999))
        self.db.commit()
        for code in ("piq_access", "piq_enhancement", "crm"):
            self.db.add(TenantService(tenant_id="tenant", service_code=code, status="active", contract_price_cents=17500 if code == "piq_access" else 0))
        self.profile = TenantBillingProfile(tenant_id="tenant", stripe_customer_id="cus_saved", default_payment_method_id="pm_saved",
            setup_status="ready", card_brand="visa", card_last4="4242")
        self.db.add(self.profile)
        self.db.commit()
        self.user = NS(id="actor", tenant_id="tenant", tenant_role="CLIENT_ADMIN", global_role=None, active=True, must_change_password=False)
        self.settings = NS(payment_provider="stripe", stripe_env="test", live_charging_enabled=False,
            monthly_billing_enabled=True, ar_billing_mode="track_only",
            stripe_secret_key="sk_test_fixture", stripe_publishable_key="pk_test_fixture", stripe_webhook_secret="whsec_fixture")
        self.client = Mock()
        self.client.v1.products.create.return_value = NS(id="prod_test")
        self.client.v1.prices.create.return_value = NS(id="price_test")
        self.remote = {"id":"sub_test", "customer":"cus_saved", "livemode":False, "status":"active",
            "items":{"data":[{"current_period_start":int(time.time()),"current_period_end":int(time.time())+2592000}]},
            "latest_invoice":{"id":"in_test", "customer":"cus_saved", "status":"paid", "amount_paid":17500, "currency":"usd",
                "parent":{"subscription_details":{"subscription":"sub_test"}}, "confirmation_secret":None}}
        self.client.v1.subscriptions.create.side_effect = lambda *a, **k: StripeObject.construct_from(self.remote, "fixture")
        self.client.v1.subscriptions.retrieve.side_effect = lambda *a, **k: StripeObject.construct_from(self.remote, "fixture")
        async def inline(fn, *args): return fn(*args)
        for key, value in (("settings", self.settings), ("_stripe_client", lambda:self.client), ("run_in_threadpool", inline)):
            p = patch.object(billing,key,value); p.start(); self.addCleanup(p.stop)
        self.addCleanup(self.temp.cleanup); self.addCleanup(self.engine.dispose); self.addCleanup(self.db.close)
        self.request = Request({"type":"http", "method":"POST", "headers":[(b"x-rmr-request",b"1")]})
        self.op = billing.prepare_operation("subscription", "tenant", billing.PrepareOperation(), self.request, self.user, self.db)["operation_id"]

    def payload(self, db=None):
        return billing.ActivateSubscription(operation_id=self.op, confirmed=True, quote_hash=monthly.quote(db or self.db,"tenant")["quote_hash"])

    def activate(self, db=None):
        db = db or self.db
        return billing.activate_subscription("tenant",self.payload(db),self.request,self.user,db)

    def gate(self): monthly.require_paid_service(self.db,"tenant","piq_access",self.user)

    def webhook(self, kind, customer="cus_saved", sub="sub_test", valid=True):
        obj = {"object":"subscription", "id":sub, "customer":customer} if kind.startswith("customer.") else {
            "object":"invoice", "id":"old_invoice", "customer":customer, "parent":{"subscription_details":{"subscription":sub}}}
        body=json.dumps({"id":"evt_fixture", "object":"event", "livemode":False, "type":kind, "data":{"object":obj}}).encode()
        timestamp=str(int(time.time()))
        signature=hmac.new(b"whsec_fixture",timestamp.encode()+b"."+body,hashlib.sha256).hexdigest() if valid else "bad"
        async def receive(): return {"type":"http.request", "body":body}
        request=Request({"type":"http", "headers":[(b"stripe-signature",f"t={timestamp},v1={signature}".encode())]},receive)
        return asyncio.run(billing.stripe_webhook(request,self.db))

    def test_no_card_gate(self):
        self.profile.default_payment_method_id=None; self.profile.setup_status="not_configured";self.db.commit()
        self.assertEqual(billing.billing_status("tenant",self.user,self.db)["monthly"]["stage"],"payment_method_required")
        with self.assertRaises(HTTPException) as e:self.gate()
        self.assertEqual(e.exception.status_code,402)

    def test_monthly_disabled_allows_client_access_without_card_and_blocks_activation(self):
        self.profile.default_payment_method_id = None
        self.profile.setup_status = 'not_configured'
        self.db.commit()
        with patch.object(monthly, 'settings', NS(monthly_billing_enabled=False)):
            self.assertFalse(monthly.onboarding_required(self.db, self.user))
            monthly.require_paid_service(self.db, 'tenant', 'piq_access', self.user)
            path_request = Request({'type': 'http', 'method': 'GET',
                                    'path': '/api/tenants/tenant/crm', 'headers': []})
            monthly.require_onboarding_access(self.db, self.user, path_request)
            status = billing.billing_status('tenant', self.user, self.db)
            self.assertFalse(status['monthly']['billing_required'])
            self.assertFalse(status['subscription_activation_available'])
            with self.assertRaises(HTTPException) as error:
                billing.activate_subscription('tenant', self.payload(), self.request, self.user, self.db)
            self.assertEqual(error.exception.status_code, 403)
            self.client.v1.subscriptions.create.assert_not_called()
            with patch('rmr_platform.db.db_session') as open_session:
                billing_renewals.reconcile_pass()
                open_session.assert_not_called()

    def test_monthly_enabled_preserves_existing_gate(self):
        with patch.object(monthly, 'settings', NS(monthly_billing_enabled=True)):
            with self.assertRaises(HTTPException) as error:
                self.gate()
            self.assertEqual(error.exception.status_code, 402)
            self.assertTrue(billing.billing_status('tenant', self.user, self.db)['monthly']['billing_required'])

    def test_monthly_flag_only_explicit_false_disables_billing(self):
        for raw, expected in (('false', False), ('0', False), ('off', False),
                              ('true', True), ('invalid', True)):
            with patch.dict(os.environ, {'RMR_MONTHLY_BILLING_ENABLED': raw}):
                self.assertEqual(_enabled_unless_explicitly_disabled('RMR_MONTHLY_BILLING_ENABLED'), expected)

    def test_recovery_flag_only_for_actionable_invoice(self):
        self.activate()
        row=monthly.subscription(self.db,"tenant","test")
        for status,invoice,expected in [('active','paid',False),('incomplete','open',True),('past_due','open',True),('unpaid','open',False),('canceled','open',False),('incomplete_expired','open',False)]:
            row.status=status;row.last_payment_status=invoice;self.db.commit()
            self.assertEqual(monthly.summary(self.db,'tenant','test',self.profile)['subscription']['payment_action_required'],expected)

    def test_temporary_test_charge_removed(self):
        self.assertNotIn('/api/tenants/{tenant_id}/billing/test-charge',[r.path for r in billing.router.routes])
        with self.assertRaises(HTTPException) as error:
            billing.prepare_operation('test-charge','tenant',billing.PrepareOperation(),self.request,self.user,self.db)
        self.assertEqual(error.exception.status_code,403)

    def test_fresh_tenant_cannot_see_or_use_another_tenants_card(self):
        other=NS(id=None,tenant_id="other",tenant_role="CLIENT_ADMIN",global_role=None)
        result=billing.billing_status("other",other,self.db)
        self.assertIsNone(result["payment_method"]);self.assertEqual(result["setup_status"],"not_configured")
        with self.assertRaises(HTTPException):billing.billing_status("tenant",other,self.db)
        with self.assertRaises(HTTPException):
            billing.activate_subscription("other",self.payload(),self.request,other,self.db)
        self.client.v1.subscriptions.create.assert_not_called()
        self.client.v1.customers.create.return_value=NS(id="cus_other")
        self.client.v1.setup_intents.create.return_value=NS(id="seti_other",client_secret="fixture_secret")
        op=billing.prepare_operation("setup","other",billing.PrepareOperation(),self.request,other,self.db)["operation_id"]
        billing.create_setup_intent("other",billing.OperationRequest(operation_id=op),self.request,other,self.db)
        self.assertEqual(self.client.v1.setup_intents.create.call_args.args[0]["customer"],"cus_other")
        self.client.v1.setup_intents.retrieve.return_value=NS(id="seti_other",livemode=False,customer="cus_other",
            status="succeeded",payment_method="pm_other",created=int(time.time()))
        self.client.v1.payment_methods.retrieve.return_value=NS(customer="cus_saved",card=NS(brand="visa",last4="4242",exp_month=12,exp_year=2030))
        with self.assertRaises(HTTPException):
            billing.complete_payment_method("other",billing.SetupIntentComplete(setup_intent_id="seti_other"),self.request,other,self.db)
        self.client.v1.payment_methods.retrieve.return_value=NS(customer="cus_other",card=NS(brand="visa",last4="1234",exp_month=12,exp_year=2030))
        billing.complete_payment_method("other",billing.SetupIntentComplete(setup_intent_id="seti_other"),self.request,other,self.db)
        self.assertEqual(billing.billing_status("other",other,self.db)["payment_method"]["last4"],"1234")
        self.assertEqual(billing.billing_status("tenant",self.user,self.db)["payment_method"]["last4"],"4242")
        self.assertEqual(billing._profile(self.db,"tenant").stripe_customer_id,"cus_saved")
        self.client.v1.subscriptions.create.assert_not_called()
        self.db.add(TenantService(tenant_id="other",service_code="piq_access",status="active",contract_price_cents=10000))
        self.db.commit()
        self.remote["customer"]="cus_other";self.remote["latest_invoice"]["customer"]="cus_other"
        op=billing.prepare_operation("subscription","other",billing.PrepareOperation(),self.request,other,self.db)["operation_id"]
        billing.activate_subscription("other",billing.ActivateSubscription(operation_id=op,confirmed=True,
            quote_hash=monthly.quote(self.db,"other")["quote_hash"]),self.request,other,self.db)
        params=self.client.v1.subscriptions.create.call_args.args[0]
        self.assertEqual((params["customer"],params["default_payment_method"]),("cus_other","pm_other"))

    def test_onboarding_gate_stays_locked_until_paid(self):
        self.assertTrue(monthly.onboarding_required(self.db,self.user))
        self.remote["status"]="incomplete";self.remote["latest_invoice"]["status"]="open"
        self.activate();self.assertTrue(monthly.onboarding_required(self.db,self.user))
        self.remote["status"]="active";self.remote["latest_invoice"]["status"]="paid"
        self.webhook("invoice.paid");self.assertFalse(monthly.onboarding_required(self.db,self.user))
        self.remote["status"]="past_due";self.webhook("invoice.payment_failed")
        self.assertTrue(monthly.onboarding_required(self.db,self.user))

    def test_onboarding_no_billable_assignment_and_admin_exempt(self):
        self.user.global_role="RMR_OWNER"
        self.assertFalse(monthly.onboarding_required(self.db,self.user))
        self.user.global_role=None
        assignment=self.db.scalar(select(TenantService).where(TenantService.service_code=="piq_access"))
        assignment.status="inactive";self.db.commit()
        self.assertFalse(monthly.onboarding_required(self.db,self.user))

    def test_authenticated_api_boundary_blocks_modules_allows_billing_essentials(self):
        from fastapi import FastAPI, Depends
        from fastapi.testclient import TestClient
        from rmr_platform import security
        from rmr_platform.db import get_db
        self.db.add(User(id="actor",email="billing@example.test",full_name="Billing User",password_hash="unused",
                         tenant_id="tenant",tenant_role="CLIENT_ADMIN",active=True,must_change_password=False))
        self.db.commit()
        app=FastAPI();app.include_router(billing.router)
        paths=['/api/tenants/tenant/crm','/api/tenants/tenant/workspace','/api/solutions','/api/training',
               '/api/tenants/tenant/reports','/api/tenants/tenant/team','/api/tenants/tenant/email']
        def protected(user=Depends(security.current_user)):return {"ok":True}
        for path in paths+['/api/auth/me','/api/tenants','/api/tenants/tenant/modules','/api/tenants/tenant/theme']:
            app.add_api_route(path,protected,methods=['GET'])
        app.add_api_route('/api/auth/logout',protected,methods=['POST'])
        def db_session():
            with Session(self.engine) as db:yield db
        app.dependency_overrides[get_db]=db_session
        with patch.object(security,'decode_token',return_value={"sub":"actor"}), TestClient(app) as client:
            client.cookies.set('rmr_session','fixture')
            for path in paths:self.assertEqual(client.get(path).status_code,402,path)
            for path in ['/api/auth/me','/api/tenants','/api/tenants/tenant/modules','/api/tenants/tenant/theme','/api/tenants/tenant/billing']:
                self.assertEqual(client.get(path).status_code,200,path)
            self.assertEqual(client.post('/api/auth/logout').status_code,200)
            self.activate()
            for path in paths:self.assertEqual(client.get(path).status_code,200,path)

    def test_saved_card_review_not_unlock(self):
        result=billing.billing_status("tenant",self.user,self.db)
        self.assertEqual(result["monthly"]["stage"],"ready_to_activate")
        with self.assertRaises(HTTPException):self.gate()
        self.client.v1.subscriptions.create.assert_not_called()

    def test_server_price_and_unpriced(self):
        q=monthly.quote(self.db,"tenant")
        self.assertEqual(q["total_cents"],17500)
        self.assertEqual([s["service_code"] for s in q["services"]],["piq_access"])
        self.assertEqual(len(q["unpriced_services"]),2)
        with self.assertRaises(ValueError):billing.ActivateSubscription(**self.payload().model_dump(),amount=1)

    def fresh_three_service_client(self, enhancement_cents):
        from rmr_platform.routes import portfolio
        from rmr_platform.schemas import TenantCreate
        from rmr_platform.models import OnboardingProject, OnboardingStep, WebsiteSite, WebsitePage, WebsiteSection, Notification
        for model in (OnboardingProject, OnboardingStep, WebsiteSite, WebsitePage, WebsiteSection, Notification):
            model.__table__.create(self.engine, checkfirst=True)
        self.db.add(ServiceCatalog(code='platform_core', name='RMR Core', standard_price_cents=99999, cadence='monthly'))
        self.db.scalar(select(ServiceCatalog).where(ServiceCatalog.code=='piq_enhancement')).cadence='usage'
        self.db.commit()
        prices={'crm':4000,'platform_core':1000,'piq_enhancement':enhancement_cents}
        result=portfolio.create_tenant(TenantCreate(name='Fresh Client',slug='fresh-client',
            primary_contact_name='Test Admin',primary_contact_email='fresh@example.test',invite_primary_admin=False,
            services=[{'service_code':code,'contract_price_cents':price} for code,price in prices.items()]),
            self.request,NS(id=None,global_role='RMR_OWNER'),self.db)
        tid=result['tenant']['id'];self.db.expire_all()
        rows=list(self.db.scalars(select(TenantService).where(TenantService.tenant_id==tid)))
        self.assertEqual({r.service_code:r.contract_price_cents for r in rows},
                         {**prices,'piq_enhancement':0})
        self.assertEqual({r.service_code:r.usage_price_cents for r in rows}['piq_enhancement'],enhancement_cents)
        self.assertEqual({r.service_code:r.cadence for r in rows}['piq_enhancement'],'usage')
        return tid

    def test_fresh_usage_service_excluded_from_monthly_activation(self):
        tid=self.fresh_three_service_client(500)
        user=NS(id=None,tenant_id=tid,tenant_role='CLIENT_ADMIN',global_role=None)
        self.db.add(TenantBillingProfile(tenant_id=tid,stripe_customer_id='cus_fresh',
            default_payment_method_id='pm_fresh',setup_status='ready',card_brand='visa',card_last4='4242'))
        self.db.commit()
        review=billing.billing_status(tid,user,self.db)['monthly']
        expected={'crm':4000,'platform_core':1000}
        self.assertEqual({s['service_code']:s['amount_cents'] for s in review['services']},expected)
        self.assertEqual(review['total_cents'],5000)
        self.assertEqual([s['service_code'] for s in review['unpriced_services']],['piq_enhancement'])
        self.remote['customer']='cus_fresh';self.remote['latest_invoice']['customer']='cus_fresh'
        self.remote['latest_invoice']['amount_paid']=5000
        self.client.v1.prices.create.side_effect=lambda params,**kwargs:NS(id=f"price_{params['unit_amount']}")
        op=billing.prepare_operation('subscription',tid,billing.PrepareOperation(),self.request,user,self.db)['operation_id']
        billing.activate_subscription(tid,billing.ActivateSubscription(operation_id=op,confirmed=True,
            quote_hash=review['quote_hash']),self.request,user,self.db)
        accepted=self.db.get(BillingOperation,op).request_data['acceptance']
        self.assertEqual(accepted['total_cents'],5000)
        self.assertEqual({s['service_code']:s['amount_cents'] for s in accepted['services']},expected)
        self.assertEqual(sorted(c.args[0]['unit_amount'] for c in self.client.v1.prices.create.call_args_list),[1000,4000])
        self.assertEqual(len(self.client.v1.subscriptions.create.call_args.args[0]['items']),2)

    def test_fresh_zero_enhancement_stays_unpriced(self):
        tid=self.fresh_three_service_client(0)
        review=monthly.quote(self.db,tid)
        self.assertEqual(review['total_cents'],5000)
        self.assertEqual([s['service_code'] for s in review['unpriced_services']],['piq_enhancement'])

    def test_added_usage_service_keeps_usage_cadence_and_price(self):
        from rmr_platform.routes.services import add_tenant_service, update_tenant_service
        from rmr_platform.schemas import TenantServiceCreate, TenantServiceUpdate
        self.db.scalar(select(ServiceCatalog).where(ServiceCatalog.code=='piq_enhancement')).cadence='usage'
        self.db.commit()
        admin=NS(id=None,global_role='RMR_OWNER')
        result=add_tenant_service('other',TenantServiceCreate(service_code='piq_enhancement',
            contract_price_cents=20,cadence='monthly'),self.request,admin,self.db)
        row=self.db.get(TenantService,result['service']['id'])
        self.assertEqual((row.cadence,row.contract_price_cents,row.usage_price_cents),('usage',0,20))
        self.assertEqual(monthly.quote(self.db,'other')['total_cents'],0)
        with self.assertRaises(HTTPException):
            update_tenant_service(row.id,TenantServiceUpdate(cadence='monthly'),self.request,admin,self.db)

    def test_tenant_specific_prices_and_admin_assignment_edit(self):
        from rmr_platform.routes.services import add_tenant_service, update_tenant_service
        from rmr_platform.schemas import TenantServiceCreate, TenantServiceUpdate
        admin=NS(id=None,global_role="RMR_OWNER")
        result=add_tenant_service("other",TenantServiceCreate(service_code="piq_access",contract_price_cents=2000),self.request,admin,self.db)
        self.assertEqual(monthly.quote(self.db,"other")["total_cents"],2000)
        self.assertEqual(monthly.quote(self.db,"tenant")["total_cents"],17500)
        update_tenant_service(result["service"]["id"],TenantServiceUpdate(contract_price_cents=10000),self.request,admin,self.db)
        self.db.expire_all()
        self.assertEqual(monthly.quote(self.db,"other")["total_cents"],10000)
        with self.assertRaises(HTTPException):
            update_tenant_service(result["service"]["id"],TenantServiceUpdate(contract_price_cents=1),self.request,self.user,self.db)

    def test_quote_snapshot_and_stripe_use_assignment_prices(self):
        rows={s.service_code:s for s in self.db.scalars(select(TenantService).where(TenantService.tenant_id=="tenant"))}
        rows["piq_access"].contract_price_cents=10000;rows["crm"].contract_price_cents=5000
        rows["piq_enhancement"].contract_price_cents=9999;rows["piq_enhancement"].cadence="per_record"
        self.db.commit()
        self.assertEqual(billing.billing_status("tenant",self.user,self.db)["monthly"]["total_cents"],15000)
        self.client.v1.prices.create.side_effect=lambda params,**kwargs:NS(id=f"price_{params['unit_amount']}")
        self.activate()
        snapshot=self.db.get(BillingOperation,self.op).request_data["acceptance"]
        self.assertEqual(snapshot["total_cents"],15000)
        self.assertEqual({s["service_code"]:s["amount_cents"] for s in snapshot["services"]},{"crm":5000,"piq_access":10000})
        self.assertEqual(sorted(c.args[0]["unit_amount"] for c in self.client.v1.prices.create.call_args_list),[5000,10000])
        self.assertEqual(len(self.client.v1.subscriptions.create.call_args.args[0]["items"]),2)

    def test_active_agreement_not_repriced_by_assignment_edit(self):
        self.activate()
        assignment=self.db.scalar(select(TenantService).where(TenantService.service_code=="piq_access"))
        assignment.contract_price_cents=2000;self.db.commit()
        data=billing.billing_status("tenant",self.user,self.db)["monthly"]
        self.assertEqual(data["total_cents"],2000)
        self.assertEqual(data["subscription"]["monthly_amount_cents"],17500)
        self.assertEqual(data["subscription"]["services"][0]["amount_cents"],17500)
        self.activate();self.client.v1.subscriptions.create.assert_called_once()
        self.client.v1.subscriptions.update.assert_not_called()
        assignment.contract_price_cents=0;self.db.commit()
        self.remote["status"]="past_due";self.webhook("invoice.payment_failed")
        self.assertTrue(monthly.onboarding_required(self.db,self.user))
        with self.assertRaises(HTTPException):self.gate()

    def test_unpriced_monthly_service_not_in_stripe_items(self):
        self.activate()
        self.assertEqual(self.client.v1.prices.create.call_count,1)
        self.assertEqual(len(self.client.v1.subscriptions.create.call_args.args[0]["items"]),1)

    def test_explicit_confirmation_required(self):
        payload=self.payload();payload.confirmed=False
        with self.assertRaises(HTTPException):billing.activate_subscription("tenant",payload,self.request,self.user,self.db)
        self.client.v1.products.create.assert_not_called()

    def test_changed_review_rejected(self):
        payload=self.payload();payload.quote_hash="tampered"
        with self.assertRaises(HTTPException):billing.activate_subscription("tenant",payload,self.request,self.user,self.db)
        self.client.v1.subscriptions.create.assert_not_called()

    def test_acceptance_snapshot_and_exact_request(self):
        self.activate();op=self.db.get(BillingOperation,self.op)
        a=op.request_data["acceptance"]
        self.assertEqual((a["tenant_id"],a["user_id"],a["total_cents"],a["currency"],a["interval"]),("tenant","actor",17500,"usd","month"))
        self.assertTrue(a["accepted_at"]);self.assertEqual(a["operation_id"],self.op)
        params=self.client.v1.subscriptions.create.call_args.args[0]
        self.assertEqual(params["default_payment_method"],"pm_saved")
        self.assertEqual(params["collection_method"],"charge_automatically")
        self.assertNotIn("payment_method_types",params)
        self.assertEqual(self.client.v1.prices.create.call_args.args[0]["unit_amount"],17500)

    def test_paid_first_invoice_unlocks(self):
        self.assertEqual(self.activate()["monthly"]["stage"],"active");self.gate()

    def test_same_operation_retry_and_active_no_duplicate(self):
        self.activate();before=dict(self.db.get(BillingOperation,self.op).request_data)
        prepared=billing.prepare_operation("subscription","tenant",billing.PrepareOperation(previous_operation_id=self.op),self.request,self.user,self.db)
        self.assertEqual(prepared["operation_id"],self.op)
        self.activate();self.client.v1.subscriptions.create.assert_called_once()
        self.assertEqual(before,self.db.get(BillingOperation,self.op).request_data)

    def test_concurrent_activation(self):
        self.db.rollback();barrier=threading.Barrier(2)
        def run():
            with Session(self.engine) as db:
                payload=self.payload(db);db.rollback();barrier.wait()
                return billing.activate_subscription("tenant",payload,self.request,self.user,db)["monthly"]["stage"]
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:run(),range(2)))
        self.assertEqual(results,["active","active"])
        self.client.v1.subscriptions.create.assert_called_once()
        self.assertEqual(self.db.scalar(select(func.count(BillingSubscription.id))),1)

    def test_failed_first_payment_does_not_unlock(self):
        self.remote["status"]="incomplete";self.remote["latest_invoice"]["status"]="open"
        self.assertEqual(self.activate()["monthly"]["stage"],"payment_problem")
        with self.assertRaises(HTTPException):self.gate()

    def test_action_secret_not_persisted(self):
        self.remote["status"]="incomplete";self.remote["latest_invoice"]["status"]="open"
        self.remote["latest_invoice"]["confirmation_secret"]={"client_secret":"pi_action_secret_fixture"}
        self.assertEqual(self.activate()["client_secret"],"pi_action_secret_fixture")
        op=self.db.get(BillingOperation,self.op)
        self.assertNotIn("secret",json.dumps([op.request_data,op.result_data]))
        with self.assertRaises(HTTPException):self.gate()

    def test_invoice_paid_recovery(self):
        self.remote["status"]="incomplete";self.remote["latest_invoice"]["status"]="open";self.activate()
        self.remote["status"]="active";self.remote["latest_invoice"]["status"]="paid"
        self.webhook("invoice.paid");self.gate()

    def test_failed_renewal_blocks(self):
        self.activate();self.remote["status"]="past_due";self.remote["latest_invoice"]["status"]="open"
        self.webhook("invoice.payment_failed")
        with self.assertRaises(HTTPException):self.gate()

    def test_subscription_update_and_deletion(self):
        self.activate()
        for status,kind in [("unpaid","customer.subscription.updated"),("canceled","customer.subscription.deleted")]:
            self.remote["status"]=status;self.webhook(kind)
            with self.assertRaises(HTTPException):self.gate()
        self.assertIsNotNone(monthly.subscription(self.db,"tenant","test").cancelled_at)

    def test_duplicate_and_old_webhook_cannot_regress(self):
        self.activate();self.webhook("invoice.paid");self.webhook("invoice.paid")
        # Old failed event must retrieve the CURRENT paid invoice, not regress it.
        self.webhook("invoice.payment_failed");self.gate()
        self.client.v1.subscriptions.create.assert_called_once()

    def test_wrong_customer_and_subscription_ignored(self):
        self.activate();self.client.v1.subscriptions.retrieve.reset_mock()
        self.assertTrue(self.webhook("invoice.paid",customer="cus_other")["ignored"])
        self.assertTrue(self.webhook("invoice.paid",sub="sub_other")["ignored"])
        self.client.v1.subscriptions.retrieve.assert_not_called()

    def test_signature_rejected(self):
        with self.assertRaises(HTTPException) as e:self.webhook("invoice.paid",valid=False)
        self.assertEqual(e.exception.status_code,400)

    def test_direct_piq_and_bridge_entitlement(self):
        from rmr_platform.routes.piq import _require_piq_access
        from rmr_platform.routes.piq_workflow import access
        from rmr_platform.prospectiq_bridge.service import authorized_tenant
        for call in (lambda:_require_piq_access(self.db,"tenant",self.user),lambda:access(self.db,self.user,"tenant"),lambda:authorized_tenant(self.db,self.user,"tenant")):
            with self.assertRaises(HTTPException) as e:call()
            self.assertEqual(e.exception.status_code,402)
        self.activate();authorized_tenant(self.db,self.user,"tenant");access(self.db,self.user,"tenant")

    def test_global_admin_and_nonbillable_not_gated(self):
        admin=NS(global_role="RMR_OWNER")
        monthly.require_paid_service(self.db,"tenant","piq_access",admin)
        monthly.require_paid_service(self.db,"tenant","crm",self.user)

    def test_live_mode_rejected_before_any_provider_call(self):
        self.settings.stripe_secret_key="sk_live_fixture";self.settings.stripe_publishable_key="pk_live_fixture"
        with self.assertRaises(HTTPException) as e:self.activate()
        self.assertIn(e.exception.status_code,{403,409,503})
        self.client.v1.subscriptions.create.assert_not_called();self.client.v1.products.create.assert_not_called()

    def test_explicit_live_activation_uses_separate_card_and_price_mapping(self):
        TenantLiveBillingProfile.__table__.create(self.engine)
        self.db.add(TenantLiveBillingProfile(tenant_id="tenant", stripe_customer_id="cus_live",
            default_payment_method_id="pm_live", setup_status="ready", card_last4="1234"))
        self.db.commit()
        self.settings.stripe_env="live"
        self.settings.stripe_secret_key="sk_live_fixture"
        self.settings.stripe_publishable_key="pk_live_fixture"
        self.settings.live_charging_enabled=True
        self.remote.update(customer="cus_live",livemode=True)
        self.remote["latest_invoice"]["customer"]="cus_live"
        self.op=billing.prepare_operation("subscription","tenant",billing.PrepareOperation(),
            self.request,self.user,self.db)["operation_id"]
        result=self.activate()
        row=monthly.subscription(self.db,"tenant","live")
        self.assertEqual(row.stripe_customer_id,"cus_live")
        self.assertEqual(row.monthly_amount_cents,17500)
        self.assertEqual(result["monthly"]["subscription"]["monthly_amount_cents"],17500)
        self.assertEqual(billing._profile(self.db,"tenant").default_payment_method_id,"pm_live")
        self.assertEqual(self.profile.default_payment_method_id,"pm_saved")
        self.assertIsNotNone(self.db.get(BillingServicePrice,"tenant:live:piq_access:17500"))
        self.assertIsNone(monthly.subscription(self.db,"tenant","test"))

    def test_wrong_tenant_and_readonly_rejected(self):
        self.user.tenant_id="other"
        with self.assertRaises(HTTPException):self.activate()
        self.user.tenant_id="tenant";self.user.tenant_role="MARKETING_USER"
        with self.assertRaises(HTTPException):self.activate()
        self.client.v1.subscriptions.create.assert_not_called()

    def test_uncertain_create_reuses_key(self):
        self.client.v1.subscriptions.create.side_effect=StripeError("timeout")
        with self.assertRaises(HTTPException):self.activate()
        first=self.client.v1.subscriptions.create.call_args
        self.client.v1.subscriptions.create.side_effect=lambda *a,**k:StripeObject.construct_from(self.remote,"fixture")
        self.activate();self.assertEqual(first,self.client.v1.subscriptions.create.call_args)

    def test_refresh_has_no_creation(self):
        self.activate();self.client.v1.subscriptions.create.reset_mock()
        result=billing.refresh_subscription("tenant",self.request,self.user,self.db)
        self.assertEqual(result["monthly"]["stage"],"active");self.client.v1.subscriptions.create.assert_not_called()

    def test_repeat_additive_migration(self):
        from rmr_platform.migrations import apply_monthly_billing_schema
        apply_monthly_billing_schema(bind=self.engine);apply_monthly_billing_schema(bind=self.engine)
        self.assertEqual(self.db.scalar(select(func.count(Tenant.id))),2)

    def test_expired_paid_period_fails_closed(self):
        self.remote["items"]["data"][0]["current_period_end"]=int(time.time())-1
        self.activate()
        with self.assertRaises(HTTPException):self.gate()

    def test_wrong_retrieved_invoice_customer_rejected(self):
        self.remote["latest_invoice"]["customer"]="cus_other"
        with self.assertRaises(HTTPException):self.activate()
        self.db.rollback()
        with self.assertRaises(HTTPException):self.gate()

    def test_setup_replacement_updates_subscription_default_without_new_purchase(self):
        self.activate();self.client.v1.subscriptions.create.reset_mock()
        self.client.v1.setup_intents.retrieve.return_value=NS(id="seti_new",customer="cus_saved",livemode=False,
            status="succeeded",payment_method="pm_new",created=int(time.time())+20)
        self.client.v1.payment_methods.retrieve.return_value=NS(customer="cus_saved",
            card=NS(brand="visa",last4="1234",exp_month=12,exp_year=2030))
        billing._complete_setup_intent(self.db,self.profile,"seti_new")
        self.client.v1.subscriptions.update.assert_called_once()
        self.assertEqual(self.client.v1.subscriptions.update.call_args.args,("sub_test",{"default_payment_method":"pm_new"}))
        self.assertEqual(self.profile.card_last4,"1234")
        self.client.v1.subscriptions.create.assert_not_called()

    def test_origin_required(self):
        bad=Request({"type":"http","method":"POST","headers":[]})
        with self.assertRaises(HTTPException):billing.activate_subscription("tenant",self.payload(),bad,self.user,self.db)
        self.client.v1.subscriptions.create.assert_not_called()

    def test_products_prices_created_once_under_concurrent_retry(self):
        self.activate();self.activate()
        self.client.v1.products.create.assert_called_once();self.client.v1.prices.create.assert_called_once()
        self.assertEqual(self.db.scalar(select(func.count(BillingServicePrice.id))),1)

    def test_webhook_recovers_lost_subscription_creation_response(self):
        self.client.v1.subscriptions.create.side_effect=StripeError("timeout")
        with self.assertRaises(HTTPException):self.activate()
        self.remote["metadata"]={"rmr_tenant_id":"tenant","rmr_operation_id":self.op}
        self.webhook("invoice.paid");self.gate()
        self.activate()
        self.client.v1.subscriptions.create.assert_called_once()

    def test_webhook_does_not_adopt_unrelated_pending_subscription(self):
        self.client.v1.subscriptions.create.side_effect=StripeError("timeout")
        with self.assertRaises(HTTPException):self.activate()
        self.remote["metadata"]={"rmr_tenant_id":"tenant","rmr_operation_id":"wrong"}
        self.assertTrue(self.webhook("invoice.paid")["ignored"])
        with self.assertRaises(HTTPException):self.gate()
