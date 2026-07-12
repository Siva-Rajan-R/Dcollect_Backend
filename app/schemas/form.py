from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime
from bson import ObjectId

class FormBase(BaseModel):
    name: str
    description: Optional[str] = None
    workspace_id: str
    settings: dict[str, Any] = {}

class FormCreate(FormBase):
    pass

class FormInDB(FormBase):
    id: Optional[str] = Field(default=None, alias="_id")
    created_by: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class Form(FormBase):
    id: str = Field(alias="_id")
    created_by: str
    created_at: datetime
    updated_at: datetime

    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}

from app.schemas.field import FormField, FormFieldUpdate

class FormUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    settings: Optional[dict[str, Any]] = None
    fields: Optional[list[FormFieldUpdate]] = None


class FormDetails(Form):
    fields: list[FormField] = []

class PaginatedForms(BaseModel):
    items: list[Form]
    total: int
    page: int
    limit: int
    pages: int


