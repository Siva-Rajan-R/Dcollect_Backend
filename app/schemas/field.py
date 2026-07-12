from pydantic import BaseModel, Field
from typing import Optional, Any, List
from enum import Enum
from bson import ObjectId

class FieldType(str, Enum):
    SINGLE_LINE = "single_line"
    PARAGRAPH = "paragraph"
    NUMBER = "number"
    EMAIL = "email"
    DATE = "date"
    DROPDOWN = "dropdown"
    CHECKBOX = "checkbox"
    FILE = "file"
    IMAGE = "image"
    RELATIONSHIP = "relationship"

class FieldOptions(BaseModel):
    required: bool = False
    unique: bool = False
    placeholder: Optional[str] = None
    help_text: Optional[str] = None
    choices: Optional[List[str]] = None # For dropdown/radio
    min: Optional[float] = None
    max: Optional[float] = None
    max_size: Optional[int] = 5
    max_files: Optional[int] = 1

class FormFieldBase(BaseModel):
    name: str
    type: FieldType
    options: FieldOptions = Field(default_factory=FieldOptions)
    order: int = 0
    form_id: str

class FormFieldCreate(FormFieldBase):
    pass

class FormFieldInDB(FormFieldBase):
    id: Optional[str] = Field(default=None, alias="_id")

class FormField(FormFieldBase):
    id: str = Field(alias="_id")

    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}

class FormFieldUpdate(BaseModel):
    id: Optional[str] = Field(default=None, alias="id")
    name: str
    type: FieldType
    options: FieldOptions = Field(default_factory=FieldOptions)
    order: int = 0

