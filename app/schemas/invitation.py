from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict
from bson import ObjectId


class InvitationStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    EXPIRED = "expired"


class ServiceAccess(str, Enum):
    NONE = "none"
    READ = "read"
    WRITE = "write"


class ServicePermissions(BaseModel):
    forms: ServiceAccess = ServiceAccess.NONE
    qrcodes: ServiceAccess = ServiceAccess.NONE
    cards: ServiceAccess = ServiceAccess.NONE
    tasks: ServiceAccess = ServiceAccess.NONE
    documents: ServiceAccess = ServiceAccess.NONE
    assets: ServiceAccess = ServiceAccess.NONE

    def to_dict(self) -> Dict[str, str]:
        return {
            "forms": self.forms.value,
            "qrcodes": self.qrcodes.value,
            "cards": self.cards.value,
            "tasks": self.tasks.value,
            "documents": self.documents.value,
            "assets": self.assets.value,
        }


class InvitationCreate(BaseModel):
    email: str
    service_permissions: ServicePermissions = Field(default_factory=ServicePermissions)


class InvitationInDB(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    workspace_id: str
    email: str
    invited_by: str           # user_id of the inviter
    token: str                # secure random hex token
    service_permissions: Dict[str, str] = Field(default_factory=dict)
    status: InvitationStatus = InvitationStatus.PENDING
    expires_at: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)
    accepted_at: Optional[datetime] = None
    email_sent: bool = False

    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}
