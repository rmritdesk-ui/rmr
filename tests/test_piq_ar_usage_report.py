import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
from fastapi import HTTPException

from rmr_platform.prospectiq_bridge.ar_usage_report import owner_only, report, REPORT_PATH


TENANT = '11111111-1111-4111-8111-111111111111'
CLIENT = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'


class UsageReportTests(unittest.TestCase):
    def test_owner_only(self):
        owner_only(SimpleNamespace(global_role='RMR_OWNER'))
        for role in ('CLIENT_ADMIN', 'STEP2_ADMIN', None):
            with self.assertRaises(HTTPException) as error:
                owner_only(SimpleNamespace(global_role=role))
            self.assertEqual(error.exception.status_code, 403)

    def test_signed_read_through_preserves_piq_cost(self):
        mapping = SimpleNamespace(tenant_id=TENANT, piq_client_id=CLIENT)
        db = Mock()
        db.execute.return_value.all.return_value = [(mapping, 'Client A')]
        cfg = SimpleNamespace(instance='test', piq_origin='https://piq.example.test',
                              hmac_key_id='key', hmac_secret='secret' * 8)
        captured = []

        def handler(request):
            captured.append(request)
            return httpx.Response(200, json={
                'summary': {'actual_cost_usd': 0.12},
                'clients': [{'tenant_id': TENANT, 'actual_cost_usd': 0.12}],
            })

        result = report(db, cfg, tenant_id=TENANT, transport=httpx.MockTransport(handler))
        self.assertEqual(result['summary']['actual_cost_usd'], 0.12)
        self.assertEqual(result['clients'][0]['client_name'], 'Client A')
        self.assertEqual(captured[0].url.path, REPORT_PATH)
        self.assertEqual(json.loads(captured[0].content)['tenants'],
                         [{'tenant_id': TENANT, 'client_id': CLIENT}])
        self.assertTrue(captured[0].headers.get('X-Bridge-Signature'))

    def test_unmapped_client_blocks_before_piq(self):
        db = Mock()
        db.execute.return_value.all.return_value = []
        with self.assertRaises(HTTPException) as error:
            report(db, SimpleNamespace(instance='test'), tenant_id=TENANT)
        self.assertEqual(error.exception.status_code, 404)


if __name__ == '__main__':
    unittest.main()
