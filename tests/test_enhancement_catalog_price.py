"""Only reference pricing; no provider calls or runtime database changes."""
import unittest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from rmr_platform.models import Tenant, TenantService, ServiceCatalog, CostCategory
from rmr_platform.seed import seed_reference_data
from rmr_platform.billing_subscriptions import quote


class EnhancementCatalogPriceTests(unittest.TestCase):
    def test_default_usage_price_preserves_override_and_stays_out_of_monthly_quote(self):
        engine = create_engine('sqlite:///:memory:')
        self.addCleanup(engine.dispose)
        for model in (Tenant, ServiceCatalog, TenantService, CostCategory):
            model.__table__.create(engine)
        with Session(engine) as db:
            db.add(Tenant(id='test', name='Override fixture', slug='override-fixture'))
            db.add(ServiceCatalog(code='piq_enhancement', name='ProspectIQ Record Enhancement', standard_price_cents=400, cadence='usage', unit='record'))
            db.commit()
            assignment = TenantService(tenant_id='test', service_code='piq_enhancement',
                contract_price_cents=20, usage_price_cents=20, cadence='usage', status='active')
            db.add(assignment); db.commit()
            for _ in range(2):
                seed_reference_data(db); db.commit(); db.expire_all()
                catalog = db.scalar(select(ServiceCatalog).where(ServiceCatalog.code=='piq_enhancement'))
                self.assertEqual((catalog.standard_price_cents,catalog.cadence,catalog.unit),(50,'usage','record'))
                self.assertEqual((assignment.contract_price_cents,assignment.usage_price_cents,assignment.cadence),(20,20,'usage'))
                self.assertEqual(db.scalar(select(func.count()).select_from(ServiceCatalog).where(ServiceCatalog.code=='piq_enhancement')),1)
                self.assertEqual(quote(db,'test')['total_cents'],0)
                self.assertEqual(quote(db,'test')['services'],[])
