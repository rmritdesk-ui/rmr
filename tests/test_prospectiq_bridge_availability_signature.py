"""Regression: bridge availability passes the actor to the PIQ entitlement helper."""

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from uuid import uuid4

from rmr_platform.prospectiq_bridge import routes, service


class BridgeAvailabilitySignatureTest(TestCase):
    def test_unprovisioned_availability_accepts_bridge_actor(self):
        tenant_id = uuid4()
        user = SimpleNamespace(active=True, must_change_password=False,
                               tenant_role="CLIENT_ADMIN")
        db = Mock()
        db.scalar.side_effect = [None, object(), object()]
        with (patch.object(routes, "settings", SimpleNamespace(prospectiq_bridge_enabled=True)),
              patch.object(routes, "bridge_config", return_value=SimpleNamespace(instance="test")),
              patch.object(service, "require_operational_tenant"),
              patch.object(service, "require_tenant_access"),
              patch.object(service, "is_global_admin", return_value=False),
              patch.object(service, "capabilities_for", return_value={"profiles.create"}),
              patch("rmr_platform.billing_subscriptions.require_paid_service")):
            result = routes.availability(tenant_id, user=user, db=db)

        self.assertEqual(result, {"enabled": True, "status": "unprovisioned",
                                  "can_provision": True})
