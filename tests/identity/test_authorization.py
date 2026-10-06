from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from sortax.identity.authorization import require_resource_owner
from sortax.identity.errors import ResourceNotFoundError
from sortax.identity.models import IdentityContext


def make_identity() -> IdentityContext:
    now = datetime.now(UTC)
    return IdentityContext(
        user_id=uuid4(),
        tenant_id=uuid4(),
        role="user",
        token_id=uuid4(),
        issued_at=now,
        expires_at=now + timedelta(hours=1),
    )


def test_owner_in_same_tenant_is_authorized() -> None:
    identity = make_identity()

    require_resource_owner(
        identity,
        resource_tenant_id=identity.tenant_id,
        resource_owner_user_id=identity.user_id,
    )


def test_other_user_in_same_tenant_is_hidden() -> None:
    identity = make_identity()

    with pytest.raises(ResourceNotFoundError):
        require_resource_owner(
            identity,
            resource_tenant_id=identity.tenant_id,
            resource_owner_user_id=uuid4(),
        )


def test_resource_in_other_tenant_is_hidden() -> None:
    identity = make_identity()

    with pytest.raises(ResourceNotFoundError):
        require_resource_owner(
            identity,
            resource_tenant_id=uuid4(),
            resource_owner_user_id=identity.user_id,
        )
