from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime

class SocialLinks(BaseModel):
    linkedin: Optional[str] = None
    twitter: Optional[str] = None
    github: Optional[str] = None
    instagram: Optional[str] = None

class CustomField(BaseModel):
    label: str
    value: str

class BusinessCardBase(BaseModel):
    name: str = Field(..., description="Card internal tracking name")
    first_name: str
    last_name: str
    title: Optional[str] = None
    company: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    address: Optional[str] = None
    avatar_url: Optional[str] = None
    logo_url: Optional[str] = None
    front_image_url: Optional[str] = None
    back_image_url: Optional[str] = None
    social_links: Optional[SocialLinks] = None
    custom_fields: Optional[List[CustomField]] = None

class BusinessCardCreate(BusinessCardBase):
    workspace_id: str

class BusinessCardUpdate(BaseModel):
    name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    title: Optional[str] = None
    company: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    address: Optional[str] = None
    avatar_url: Optional[str] = None
    logo_url: Optional[str] = None
    front_image_url: Optional[str] = None
    back_image_url: Optional[str] = None
    social_links: Optional[SocialLinks] = None
    custom_fields: Optional[List[CustomField]] = None

class BusinessCard(BusinessCardBase):
    id: str = Field(..., alias="_id")
    workspace_id: str
    short_id: str
    created_at: datetime

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
