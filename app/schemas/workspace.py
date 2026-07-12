from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime
from bson import ObjectId
from app.schemas.user import PyObjectId

class WorkspaceBase(BaseModel):
    name: str
    logo_url: Optional[str] = None
    settings: dict[str, Any] = {}

class WorkspaceCreate(WorkspaceBase):
    pass

class WorkspaceInDB(WorkspaceBase):
    id: Optional[str] = Field(default=None, alias="_id")
    owner_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

class Workspace(WorkspaceBase):
    id: str = Field(alias="_id")
    owner_id: str
    created_at: datetime

    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}
