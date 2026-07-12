from pydantic import BaseModel, Field
from typing import Any, Dict, Optional
from datetime import datetime
from bson import ObjectId

class RecordBase(BaseModel):
    form_id: str
    workspace_id: str
    data: Dict[str, Any] # Field ID -> Value mapping

class RecordCreate(RecordBase):
    pass

class RecordUpdate(BaseModel):
    data: Dict[str, Any]

class RecordInDB(RecordBase):
    id: Optional[str] = Field(default=None, alias="_id")
    created_by: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    status: str = "active"

class Record(RecordBase):
    id: Optional[str] = Field(default=None, alias="_id")
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    status: str
    attachments: Optional[Dict[str, Any]] = None

    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}

class PaginatedRecords(BaseModel):
    items: list[Record]
    total: int
    page: int
    limit: int
    pages: int

