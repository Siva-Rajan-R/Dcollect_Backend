from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum
from bson import ObjectId
from typing import Optional, Dict

class Role(str, Enum):
    OWNER = "Owner"
    ADMIN = "Admin"
    MANAGER = "Manager"
    EDITOR = "Editor"
    CONTRIBUTOR = "Contributor"
    VIEWER = "Viewer"
    GUEST = "Guest"

class MemberBase(BaseModel):
    role: Role = Role.VIEWER

class MemberCreate(MemberBase):
    user_id: str
    workspace_id: str

class MemberInDB(MemberBase):
    id: Optional[str] = Field(default=None, alias="_id")
    user_id: str
    workspace_id: str
    joined_at: datetime = Field(default_factory=datetime.utcnow)
    service_permissions: Optional[Dict[str, str]] = None  # per-service access map

class Member(MemberBase):
    id: str = Field(alias="_id")
    user_id: str
    workspace_id: str
    joined_at: datetime
    service_permissions: Optional[Dict[str, str]] = None

    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}

