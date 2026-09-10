"""Maximum bridge grants. PIQ still enforces client/resource ownership."""
from ..permissions import CLIENT_OPERATION_WRITERS, is_global_admin, require_client_operational_write

READ = ["prospects.read"]
OPERATE = ["profiles.create", "profiles.update_own", "discovery.run", "prospects.export"]
ADMIN = ["profiles.manage_workspace", "research.run", "research.confirm_cost"]


def capabilities_for(user, tenant_id, managed=None):
    capabilities = list(READ)
    operational = bool(managed) if is_global_admin(user) else user.tenant_role in CLIENT_OPERATION_WRITERS
    if operational:
        require_client_operational_write(user, tenant_id)
        capabilities += OPERATE
        if is_global_admin(user) or user.tenant_role == "CLIENT_ADMIN":
            capabilities += ADMIN
    return capabilities
