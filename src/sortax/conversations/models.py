from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

ConversationStatus = Literal["active", "archived"]


@dataclass(frozen=True, slots=True)
class Conversation:
    id: UUID
    tenant_id: UUID
    owner_user_id: UUID
    title: str
    status: ConversationStatus
    last_message_at: datetime | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    version: int
