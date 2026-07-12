from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime

class CommentEntry(BaseModel):
    id: Optional[str] = None
    user_id: str
    user_name: str
    user_avatar: Optional[str] = None
    text: str
    created_at: Optional[str] = None

class DocumentBase(BaseModel):
    title: str
    content: str
    assets: Optional[List[str]] = []
    folder_id: Optional[str] = None
    comments: Optional[List[Any]] = []

class DocumentCreate(DocumentBase):
    workspace_id: str

class DocumentUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    assets: Optional[List[str]] = None
    folder_id: Optional[str] = None
    comments: Optional[List[Any]] = None

class Document(DocumentBase):
    id: str = Field(alias="_id")
    workspace_id: str
    created_by: str
    created_at: datetime
    updated_at: datetime

    class Config:
        allow_population_by_field_name = True
