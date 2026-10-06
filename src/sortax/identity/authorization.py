from typing import Protocol
from uuid import UUID

from sortax.identity.errors import ResourceNotFoundError
from sortax.identity.models import IdentityContext


class OwnedTenantResource(Protocol):
    tenant_id: UUID
    owner_user_id: UUID


def require_resource_owner(
    identity: IdentityContext,
    *,
    resource_tenant_id: UUID,
    resource_owner_user_id: UUID,
) -> None:
    """Authorize an owned resource without revealing why access was denied."""

    if resource_tenant_id != identity.tenant_id or resource_owner_user_id != identity.user_id:
        raise ResourceNotFoundError


def require_owned_resource(identity: IdentityContext, resource: OwnedTenantResource) -> None:
    require_resource_owner(
        identity,
        resource_tenant_id=resource.tenant_id,
        resource_owner_user_id=resource.owner_user_id,
    )
