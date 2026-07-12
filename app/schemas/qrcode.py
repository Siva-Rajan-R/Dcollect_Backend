from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime

class QRCodeBranding(BaseModel):
    dots_color: Optional[str] = "#2563eb"
    dots_type: Optional[str] = "rounded"
    corners_color: Optional[str] = "#1e40af"
    corners_type: Optional[str] = "extra-rounded"
    bg_color: Optional[str] = "#ffffff"

class QRCodeBase(BaseModel):
    name: str
    target_url: str
    branding: Optional[QRCodeBranding] = Field(default_factory=QRCodeBranding)

class QRCodeCreate(QRCodeBase):
    workspace_id: str

class QRCodeUpdate(BaseModel):
    name: Optional[str] = None
    target_url: Optional[str] = None
    branding: Optional[QRCodeBranding] = None

class QRCode(QRCodeBase):
    id: str = Field(alias="_id")
    workspace_id: str
    short_id: str
    creator_id: str
    created_at: datetime

    class Config:
        populate_by_name = True
