"""Next-cycle schedule regression: disposable DB, all Stripe calls mocked."""
import copy
import time
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace as NS

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from stripe import StripeObject, StripeError

import test_billing_subscriptions as base
from rmr_platform import billing_renewals as renewal, billing_subscriptions as monthly
from rmr_platform.models import BillingOperation, BillingServicePrice, TenantService, AuditEvent
from rmr_platform.routes import billing, services
from rmr_platform.schemas import TenantServiceCreate, TenantServiceUpdate


class RenewalTests(unittest.TestCase):
    activate = base.MonthlyTests.activate
    payload = base.MonthlyTests.payload
    webhook = base.MonthlyTests.webhook

    def setUp(self):
        base.MonthlyTests.setUp(self)
        self.prices = getattr(self, 'initial_prices', {'crm':4000, 'piq_access':1000, 'piq_enhancement':500})
        for row in self.db.scalars(select(TenantService).where(TenantService.tenant_id=='tenant')):
            row.contract_price_cents=self.prices[row.service_code]
        self.db.commit()
        self.client.v1.prices.create.side_effect=lambda p,**k:NS(id=f"price_{p['metadata']['rmr_service_code']}_{p['unit_amount']}")
        self.remote['latest_invoice']['amount_paid']=sum(self.prices.values())
        self.activate()
        self.before=copy.deepcopy(self.db.get(BillingOperation,self.op).request_data)
        self.start=int(time.time())-100
        self.end=self.start+2592000
        self.remote['items']={'data':[{'price':p.stripe_price_id,'quantity':1,
            'current_period_start':self.start,'current_period_end':self.end}
            for p in self.db.scalars(select(BillingServicePrice))], 'has_more':False}
        self.remote['schedule']=None
        self.schedule={'id':'sched_test','customer':'cus_saved','subscription':'sub_test','livemode':False,
            'metadata':{},'current_phase':{'start_date':self.start,'end_date':self.end}}
        def create(*args,**kwargs):
            self.remote['schedule']='sched_test'
            return StripeObject.construct_from(self.schedule,'fixture')
        def update(sid,params,**kwargs):
            self.schedule['metadata']=params['metadata'];self.schedule['phases']=copy.deepcopy(params['phases'])
            return StripeObject.construct_from(self.schedule,'fixture')
        self.client.v1.subscription_schedules.create.side_effect=create
        self.client.v1.subscription_schedules.retrieve.side_effect=lambda *a,**k:StripeObject.construct_from(self.schedule,'fixture')
        self.client.v1.subscription_schedules.update.side_effect=update
        self.webhook('invoice.paid')

    def edit(self,code,**fields):
        row=self.db.scalar(select(TenantService).where(TenantService.tenant_id=='tenant',TenantService.service_code==code))
        return services.update_tenant_service(row.id,TenantServiceUpdate(**fields),self.request,
            NS(id=None,global_role='RMR_OWNER'),self.db)

    def sync(self):
        renewal.reconcile(self.db,'tenant')

    def test_price_change_is_next_cycle_itemized_no_proration(self):
        self.edit('crm',contract_price_cents=5000)
        self.assertEqual(monthly.subscription(self.db,'tenant','test').monthly_amount_cents,5500)
        self.client.v1.subscription_schedules.update.assert_not_called()
        self.sync()
        params=self.client.v1.subscription_schedules.update.call_args.args[1]
        self.assertEqual(params['proration_behavior'],'none')
        self.assertEqual([p['proration_behavior'] for p in params['phases']],['none','none'])
        self.assertEqual(params['phases'][0]['end_date'],self.end)
        self.assertEqual(params['phases'][1]['start_date'],self.end)
        self.assertEqual(len(params['phases'][1]['items']),3)
        self.assertEqual(monthly.subscription(self.db,'tenant','test').monthly_amount_cents,5500)
        self.assertEqual(self.db.get(BillingOperation,self.op).request_data,self.before)
        summary=billing.billing_status('tenant',self.user,self.db)['monthly']
        self.assertEqual(summary['subscription']['monthly_amount_cents'],5500)
        self.assertEqual(summary['next_cycle']['total_cents'],6500)
        self.client.v1.subscriptions.update.assert_not_called()
        self.client.v1.payment_intents.create.assert_not_called()
        self.client.v1.refunds.create.assert_not_called()
        # New amount reuses the CRM Product, not a duplicate Product.
        self.assertEqual(self.client.v1.products.create.call_count,3)
        self.assertEqual(self.client.v1.prices.create.call_count,4)

    def test_successful_renewal_updates_items_period_and_access(self):
        self.edit('crm',contract_price_cents=5000);self.sync()
        future=self.schedule['phases'][1]['items']
        self.remote['items']['data']=[{**i,'current_period_start':self.end,'current_period_end':self.end+2592000} for i in future]
        self.remote['latest_invoice'].update(id='in_next',status='paid',amount_paid=6500)
        self.webhook('invoice.paid');self.sync()
        row=monthly.subscription(self.db,'tenant','test')
        self.assertEqual(row.monthly_amount_cents,6500)
        self.assertEqual(int(row.current_period_start.timestamp()),self.end)
        self.assertEqual(row.latest_invoice_id,'in_next')
        self.assertTrue(monthly.paid(row));self.assertIsNone(renewal.pending(self.db,'tenant'))
        self.assertEqual(self.db.get(BillingOperation,self.op).request_data,self.before)
        self.webhook('invoice.payment_failed') # Old event fetches current paid state.
        self.assertTrue(monthly.paid(row))
        self.remote['status']='past_due';self.remote['latest_invoice']['status']='open'
        self.webhook('invoice.payment_failed')
        self.assertTrue(monthly.onboarding_required(self.db,self.user))

    def test_addition_and_removal_change_only_future_phase(self):
        from rmr_platform.models import ServiceCatalog
        self.db.add(ServiceCatalog(code='extra',name='Extra',standard_price_cents=99999));self.db.commit()
        services.add_tenant_service('tenant',TenantServiceCreate(service_code='extra',contract_price_cents=2000,cadence='monthly'),
            self.request,NS(id=None,global_role='RMR_OWNER'),self.db)
        self.sync()
        self.assertEqual(len(self.schedule['phases'][0]['items']),3)
        self.assertEqual(len(self.schedule['phases'][1]['items']),4)
        self.edit('crm',status='suspended');self.sync()
        future=self.schedule['phases'][1]['items']
        self.assertEqual(len(future),3)
        self.assertFalse(any('crm' in i['price'] for i in future))
        self.assertEqual(monthly.subscription(self.db,'tenant','test').monthly_amount_cents,5500)
        self.client.v1.subscription_schedules.create.assert_called_once()

    def test_duplicate_and_concurrent_reconciliation(self):
        self.edit('crm',contract_price_cents=5000)
        def sync(_):
            with Session(self.engine) as db:renewal.reconcile(db,'tenant')
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(sync,range(2)))
        self.sync();self.sync()
        self.client.v1.subscription_schedules.create.assert_called_once()
        self.client.v1.subscription_schedules.update.assert_called_once()
        self.client.v1.subscriptions.create.assert_called_once()
        self.assertEqual(self.client.v1.prices.create.call_count,4)

    def test_timeout_retries_identical_frozen_schedule_request(self):
        self.edit('crm',contract_price_cents=5000)
        original=self.client.v1.subscription_schedules.update.side_effect
        self.client.v1.subscription_schedules.update.side_effect=StripeError('timeout')
        with self.assertRaises(StripeError):self.sync()
        first=self.client.v1.subscription_schedules.update.call_args
        self.db.rollback()
        self.client.v1.subscription_schedules.update.side_effect=original
        self.sync()
        self.assertEqual(self.client.v1.subscription_schedules.update.call_args,first)
        self.client.v1.subscription_schedules.create.assert_called_once()
        self.assertEqual(self.client.v1.prices.create.call_count,4)

    def test_wrong_schedule_customer_rejected(self):
        self.edit('crm',contract_price_cents=5000)
        self.schedule['customer']='cus_other'
        with self.assertRaises(HTTPException):self.sync()
        self.client.v1.subscription_schedules.update.assert_not_called()

    def test_live_configuration_blocks_schedule_calls(self):
        self.edit('crm',contract_price_cents=5000)
        self.settings.stripe_secret_key='sk_live_fixture';self.settings.stripe_publishable_key='pk_live_fixture'
        with self.assertRaises(HTTPException):self.sync()
        self.client.v1.subscription_schedules.create.assert_not_called()

    def test_all_services_removed_cancel_only_at_period_end(self):
        # Queue one coherent edit, as separate saves are allowed once prior update is scheduled.
        for code in self.prices:
            self.edit(code,contract_price_cents=0);self.sync()
        params=self.client.v1.subscription_schedules.update.call_args.args[1]
        self.assertEqual(params['end_behavior'],'cancel');self.assertEqual(len(params['phases']),1)
        self.assertEqual(params['phases'][0]['end_date'],self.end)
        self.assertEqual(monthly.subscription(self.db,'tenant','test').monthly_amount_cents,5500)

    def test_pending_is_tenant_scoped(self):
        self.edit('crm',contract_price_cents=5000)
        self.assertIsNone(renewal.pending(self.db,'other'))
        self.assertIsNone(billing.billing_status('other',NS(id=None,global_role=None,tenant_role='CLIENT_ADMIN',tenant_id='other'),self.db)['monthly']['next_cycle'])
        renewal.reconcile(self.db,'other')
        self.client.v1.subscription_schedules.create.assert_not_called()

    def test_zero_service_cancellation_does_not_leave_billing_gate_locked(self):
        for code in self.prices:
            self.edit(code,contract_price_cents=0);self.sync()
        self.remote['status']='canceled'
        with patch.object(renewal,'datetime') as clock:
            clock.now.return_value=datetime.fromtimestamp(self.end+1,timezone.utc)
            self.sync()
        self.webhook('customer.subscription.deleted')
        self.assertEqual(monthly.subscription(self.db,'tenant','test').monthly_amount_cents,0)
        self.assertFalse(monthly.onboarding_required(self.db,self.user))
        self.assertEqual(monthly.current_services(self.db,monthly.subscription(self.db,'tenant','test')),[])

    def test_wrong_tenant_price_mapping_rejected(self):
        self.remote['items']['data'][0]['price']='price_unmapped'
        with self.assertRaises(HTTPException):self.webhook('invoice.paid')

    def test_scheduled_card_replacement_updates_default_without_proration(self):
        self.edit('crm',contract_price_cents=5000);self.sync()
        self.client.v1.subscription_schedules.update.side_effect=None
        renewal.sync_schedule_payment_method(self.db,self.client,monthly.subscription(self.db,'tenant','test'),'pm_new','seti_new')
        params=self.client.v1.subscription_schedules.update.call_args.args[1]
        self.assertEqual(params,{'default_settings':{'default_payment_method':'pm_new'},'proration_behavior':'none'})

    def test_uncertain_operation_cannot_be_replayed_after_retention_window(self):
        from datetime import timedelta
        self.edit('crm',contract_price_cents=5000)
        op=renewal.pending(self.db,'tenant');op.created_at=datetime.now(timezone.utc)-timedelta(hours=24);self.db.commit()
        with self.assertRaises(HTTPException):self.sync()
        self.client.v1.subscription_schedules.create.assert_not_called()


class EightyToNinetyTests(unittest.TestCase):
    initial_prices = {'crm':3000, 'piq_access':4000, 'piq_enhancement':1000}
    setUp = RenewalTests.setUp
    activate = RenewalTests.activate
    payload = RenewalTests.payload
    webhook = RenewalTests.webhook
    edit = RenewalTests.edit
    sync = RenewalTests.sync

    def test_real_commercial_terms_save_queues_missing_renewal(self):
        from datetime import date
        from rmr_platform import cumulative_product_repair as commercial
        for model in (commercial.ClientServiceCommercialTerm, commercial.CommercialTermHistory):
            model.__table__.create(self.engine, checkfirst=True)
        row=self.db.scalar(select(TenantService).where(TenantService.tenant_id=='tenant',TenantService.service_code=='crm'))
        # Actual observed state: assignment was saved as $40 but no renewal exists.
        row.contract_price_cents=4000;self.db.commit()
        self.assertIsNone(renewal.pending(self.db,'tenant'))
        self.assertIsNone(billing.billing_status('tenant',self.user,self.db)['monthly']['next_cycle'])
        payload=commercial.CommercialTermUpdate(contract_price_cents=4000,effective_date=date.today(),rmr_share_pct=80,step2_share_pct=20)
        admin=NS(id=None,global_role='RMR_OWNER')
        commercial.update_commercial_term('tenant',row.id,payload,self.request,admin,self.db)
        operation_id=renewal.pending(self.db,'tenant').id
        commercial.update_commercial_term('tenant',row.id,payload,self.request,admin,self.db)
        self.assertEqual(renewal.pending(self.db,'tenant').id,operation_id)
        data=billing.billing_status('tenant',self.user,self.db)['monthly']
        self.assertEqual(data['subscription']['monthly_amount_cents'],8000)
        self.assertEqual(data['next_cycle']['total_cents'],9000)
        self.assertEqual(data['next_cycle']['effective_at'],self.end)
        self.client.v1.subscription_schedules.update.assert_not_called()
        self.sync()
        self.assertEqual(renewal.pending(self.db,'tenant').result_data['state'],'scheduled')
        self.assertIsNone(renewal.pending(self.db,'other'))
        self.client.v1.payment_intents.create.assert_not_called()
        self.client.v1.refunds.create.assert_not_called()

    def test_current_80_pending_90_date_and_idempotent_schedule(self):
        self.edit('crm',contract_price_cents=4000)
        op_id=renewal.pending(self.db,'tenant').id
        expected_date=datetime.fromtimestamp(self.end,timezone.utc).date().isoformat()
        for scheduled in (False,True):
            if scheduled:self.sync()
            data=billing.billing_status('tenant',self.user,self.db)['monthly']
            self.assertEqual(data['subscription']['monthly_amount_cents'],8000)
            self.assertEqual(data['next_cycle']['total_cents'],9000)
            self.assertEqual(data['next_cycle']['effective_at'],self.end)
            self.assertEqual(data['next_cycle']['effective_date'],expected_date)
        self.edit('crm',contract_price_cents=4000);self.sync()
        self.assertEqual(renewal.pending(self.db,'tenant').id,op_id)
        self.client.v1.subscription_schedules.update.assert_called_once()
        params=self.client.v1.subscription_schedules.update.call_args.args[1]
        self.assertEqual(params['proration_behavior'],'none')
        self.assertTrue(all(p['proration_behavior']=='none' for p in params['phases']))
        self.assertEqual(params['phases'][1]['start_date'],self.end)
        self.client.v1.payment_intents.create.assert_not_called()
        self.client.v1.refunds.create.assert_not_called()
        self.client.v1.subscriptions.update.assert_not_called()
        other=billing.billing_status('other',NS(id=None,tenant_id='other',tenant_role='CLIENT_ADMIN',global_role=None),self.db)
        self.assertIsNone(other['monthly']['next_cycle'])
        self.assertIsNone(other['monthly']['subscription'])
