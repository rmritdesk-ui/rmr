"""Offline, tenant-bound AR quote/payment regression; never calls Stripe."""
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from stripe import StripeError

from rmr_platform.billing_subscriptions import quote as monthly_quote
from rmr_platform import billing_policy
from rmr_platform.models import Tenant, ServiceCatalog, TenantService, TenantBillingProfile, BillingOperation
from rmr_platform.prospectiq_bridge import ar_billing


class ResearchPurchaseTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite:///:memory:')
        self.addCleanup(self.engine.dispose)
        for model in (Tenant,ServiceCatalog,TenantService,TenantBillingProfile,BillingOperation):
            model.__table__.create(self.engine)
        self.db=Session(self.engine)
        self.addCleanup(self.db.close)
        self.tenant=str(uuid4());self.other=str(uuid4())
        self.db.add_all([Tenant(id=self.tenant,name='One',slug='one'),
                         Tenant(id=self.other,name='Two',slug='two'),
                         ServiceCatalog(code='piq_enhancement',name='Enhancement',cadence='usage')])
        self.db.flush()
        for tenant,rate in ((self.tenant,20),(self.other,50)):
            self.db.add(TenantService(tenant_id=tenant,service_code='piq_enhancement',
                status='active',cadence='usage',usage_price_cents=rate,contract_price_cents=0))
            self.db.add(TenantBillingProfile(tenant_id=tenant,stripe_customer_id='cus_'+tenant[:8],
                default_payment_method_id='pm_'+tenant[:8],setup_status='ready'))
        self.db.commit()
        self.ids=[uuid4() for _ in range(3)]
        self.payload=ar_billing.ResearchPurchase(grant_id=uuid4(),mapping_id=uuid4(),mapping_version=1,
            rmr_tenant_id=self.tenant,rmr_user_id=uuid4(),piq_client_id=uuid4(),piq_user_id=uuid4(),
            target_profile_id=uuid4(),lead_ids=self.ids)
        self.stripe=Mock();self.stripe.v1.payment_intents.create.return_value=NS(id='pi_fixture',status='succeeded')
        self.real_context=ar_billing._context
        for name,value in (('_context',lambda *args:None),('_stripe_mode',lambda:'test'),
                           ('_stripe_client',lambda:self.stripe)):
            p=patch.object(ar_billing,name,value);p.start();self.addCleanup(p.stop)

    def approved(self, quote, payload=None):
        return (payload or self.payload).model_copy(update={
            'operation_id':quote['operation_id'],'approved':True,
            'approved_quote_hash':quote['quote_hash'],
        })

    def test_track_only_rejects_purchase_and_never_calls_stripe(self):
        with patch.object(ar_billing, 'settings', NS(ar_billing_mode='track_only')), patch.object(
                billing_policy, 'settings', NS(ar_billing_mode='track_only', monthly_billing_enabled=False)):
            for action in (ar_billing.quote, ar_billing.charge):
                with self.assertRaises(HTTPException) as error:
                    action(self.db, self.payload, NS())
                self.assertEqual(error.exception.status_code, 403)
        self.stripe.v1.payment_intents.create.assert_not_called()

    def test_frozen_tenant_rate_charge_retry_and_run_binding(self):
        self.assertEqual(monthly_quote(self.db,self.tenant)['total_cents'],0)
        q=ar_billing.quote(self.db,self.payload,NS())
        self.assertEqual((q['record_count'],q['unit_price_cents'],q['total_cents'],q['currency']),(3,20,60,'usd'))
        self.assertEqual(ar_billing.quote(self.db,self.payload,NS())['operation_id'],q['operation_id'])
        assignment=self.db.query(TenantService).filter_by(tenant_id=self.tenant).one()
        assignment.usage_price_cents=99;self.db.commit()
        charged=self.approved(q)
        self.assertEqual(ar_billing.charge(self.db,charged,NS())['status'],'succeeded')
        self.assertEqual(ar_billing.charge(self.db,charged,NS())['total_cents'],60)
        self.stripe.v1.payment_intents.create.assert_called_once()
        args,kwargs=self.stripe.v1.payment_intents.create.call_args
        self.assertEqual((args[0]['amount'],args[0]['currency'],args[0]['off_session'],args[0]['confirm']),(60,'usd',True,True))
        self.assertEqual(args[0]['customer'],'cus_'+self.tenant[:8])
        self.assertEqual(args[0]['payment_method'],'pm_'+self.tenant[:8])
        self.assertNotIn('payment_method_types',args[0])
        self.assertEqual(kwargs['options']['idempotency_key'],'rmr-piq-ar-'+q['operation_id'])
        run=uuid4();linked=charged.model_copy(update={'piq_run_id':run})
        self.assertEqual(ar_billing.link_run(self.db,linked,NS())['piq_run_id'],str(run))
        self.assertEqual(ar_billing.link_run(self.db,linked,NS())['piq_run_id'],str(run))
        next_cycle=self.payload.model_copy(update={'previous_operation_id':q['operation_id']})
        next_quote=ar_billing.quote(self.db,next_cycle,NS())
        self.assertNotEqual(next_quote['operation_id'],q['operation_id'])
        self.assertEqual(ar_billing.quote(self.db,next_cycle,NS())['operation_id'],next_quote['operation_id'])
        with self.assertRaises(HTTPException):
            ar_billing.link_run(self.db,charged.model_copy(update={'piq_run_id':uuid4()}),NS())

    def test_incomplete_payment_never_reports_success(self):
        self.stripe.v1.payment_intents.create.return_value=NS(id='pi_incomplete',status='requires_payment_method')
        q=ar_billing.quote(self.db,self.payload,NS())
        charged=self.approved(q)
        self.assertEqual(ar_billing.charge(self.db,charged,NS())['status'],'requires_payment_method')
        self.assertEqual(ar_billing.charge(self.db,charged,NS())['status'],'requires_payment_method')
        self.stripe.v1.payment_intents.create.assert_called_once()
        with self.assertRaises(HTTPException):
            ar_billing.link_run(self.db,charged.model_copy(update={'piq_run_id':uuid4()}),NS())

    def test_uncertain_stripe_response_keeps_same_frozen_operation(self):
        q=ar_billing.quote(self.db,self.payload,NS())
        charged=self.approved(q)
        self.stripe.v1.payment_intents.create.side_effect=StripeError('timeout')
        with self.assertRaises(HTTPException):ar_billing.charge(self.db,charged,NS())
        op=self.db.get(BillingOperation,q['operation_id'])
        self.assertEqual(op.result_data['status'],'payment_attempted')
        op.request_data={**op.request_data,'expires_at':(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()}
        self.db.commit()
        self.assertEqual(ar_billing.quote(self.db,self.payload,NS())['operation_id'],q['operation_id'])
        self.stripe.v1.payment_intents.create.side_effect=None
        self.assertEqual(ar_billing.charge(self.db,charged,NS())['status'],'succeeded')
        calls=self.stripe.v1.payment_intents.create.call_args_list
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[0].kwargs['options']['idempotency_key'],calls[1].kwargs['options']['idempotency_key'])

    def test_cross_tenant_or_changed_selection_cannot_replay(self):
        q=ar_billing.quote(self.db,self.payload,NS())
        for changed in (self.approved(q).model_copy(update={'rmr_tenant_id':self.other}),
                        self.approved(q).model_copy(update={'lead_ids':[uuid4()]})):
            with self.assertRaises(HTTPException):ar_billing.charge(self.db,changed,NS())
        self.stripe.v1.payment_intents.create.assert_not_called()

    def test_bridge_grant_must_match_mapping_tenant_actor_and_capabilities(self):
        grant=NS(id=str(self.payload.grant_id),status='consumed',mapping_id=str(self.payload.mapping_id),
            mapping_version=1,tenant_id=self.tenant,user_id=str(self.payload.rmr_user_id),
            piq_client_id=str(self.payload.piq_client_id),integration_instance_id='fixture',
            capabilities_json=['research.run','research.confirm_cost'])
        db=NS(get=lambda *_:grant)
        with patch.object(ar_billing.service,'check_grant'):
            self.assertIs(self.real_context(db,self.payload,NS(instance='fixture')),grant)
            with self.assertRaises(HTTPException):
                self.real_context(db,self.payload.model_copy(update={'rmr_tenant_id':self.other}),NS(instance='fixture'))
            grant.capabilities_json=['research.run']
            with self.assertRaises(HTTPException):self.real_context(db,self.payload,NS(instance='fixture'))

    def test_browser_price_and_duplicate_ids_rejected(self):
        with self.assertRaises(ValidationError):
            ar_billing.ResearchPurchase.model_validate({**self.payload.model_dump(mode='json'),'total_cents':1})
        self.assertEqual(len(set(self.payload.lead_ids)),3)
        q=ar_billing.quote(self.db,self.payload,NS())
        for value in (self.payload.model_copy(update={'operation_id':q['operation_id']}),
                      self.approved(q).model_copy(update={'approved_quote_hash':'0'*64})):
            with self.assertRaises(HTTPException):ar_billing.charge(self.db,value,NS())
        self.stripe.v1.payment_intents.create.assert_not_called()

    def test_below_stripe_minimum_is_quoted_but_never_charged(self):
        one=self.payload.model_copy(update={'lead_ids':[self.ids[0]]})
        q=ar_billing.quote(self.db,one,NS())
        self.assertEqual((q['total_cents'],q['payable']),(20,False))
        with self.assertRaises(HTTPException) as caught:
            ar_billing.charge(self.db,self.approved(q,one),NS())
        self.assertEqual(caught.exception.status_code,409)
        self.stripe.v1.payment_intents.create.assert_not_called()
