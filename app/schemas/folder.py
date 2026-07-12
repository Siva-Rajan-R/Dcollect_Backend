from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class FolderBase(BaseModel):
    name: str
    access_level: Optional[str] = "members" # public, members, owner
    parent_folder_id: Optional[str] = None
    folder_type: Optional[str] = "assets"  # assets | documents

class FolderCreate(FolderBase):
    workspace_id: str

class FolderUpdate(BaseModel):
    name: Optional[str] = None
    access_level: Optional[str] = None
    parent_folder_id: Optional[str] = None
    folder_type: Optional[str] = None

class Folder(FolderBase):
    id: str = Field(alias="_id")
    workspace_id: str
    created_by: str
    created_at: datetime

    class Config:
        allow_population_by_field_name = True
