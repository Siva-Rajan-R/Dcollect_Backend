from typing import Optional
from pydantic import BaseModel, Field
from datetime import datetime
from bson import ObjectId

class AttachmentBase(BaseModel):
    record_id: str
    field_id: str
    file_name: str
    minio_path: str
    size: int
    mime_type: str
    folder_id: Optional[str] = None
    access_level: Optional[str] = "members"

class AttachmentCreate(AttachmentBase):
    pass

class AttachmentInDB(AttachmentBase):
    id: Optional[str] = Field(default=None, alias="_id")
    uploaded_by: str
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)

class Attachment(AttachmentBase):
    id: Optional[str] = Field(default=None, alias="_id")
    uploaded_by: str
    uploaded_at: datetime

    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}
