from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

class TaskBase(BaseModel):
    title: str
    description: Optional[str] = ""
    status: Optional[str] = "todo" # todo, in_progress, done
    priority: Optional[str] = "medium" # low, medium, high
    task_type: Optional[str] = "task" # standard, bug, feature, improvement, documentation, design, milestone, personal
    assigned_to_user_id: Optional[str] = None # Legacy support
    assigned_to_user_ids: Optional[List[str]] = [] # Multi-assignee support
    due_date: Optional[str] = None
    due_time: Optional[str] = None
    start_date: Optional[str] = None
    estimated_hours: Optional[float] = 0.0
    actual_hours: Optional[float] = 0.0
    time_spent: Optional[float] = 0.0
    parent_task_id: Optional[str] = None
    checklists: Optional[List[Dict[str, Any]]] = [] # List of checklist items
    connected_document_ids: Optional[List[str]] = []
    connected_folder_ids: Optional[List[str]] = []
    connected_asset_ids: Optional[List[str]] = []
    connected_qr_ids: Optional[List[str]] = []
    connected_card_ids: Optional[List[str]] = []
    connected_form_ids: Optional[List[str]] = []
    custom_fields: Optional[List[Dict[str, Any]]] = []
    activity_log: Optional[List[Dict[str, Any]]] = []

class TaskCreate(TaskBase):
    workspace_id: str

class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    task_type: Optional[str] = None
    assigned_to_user_id: Optional[str] = None
    assigned_to_user_ids: Optional[List[str]] = None
    due_date: Optional[str] = None
    due_time: Optional[str] = None
    start_date: Optional[str] = None
    estimated_hours: Optional[float] = None
    actual_hours: Optional[float] = None
    time_spent: Optional[float] = None
    parent_task_id: Optional[str] = None
    checklists: Optional[List[Dict[str, Any]]] = None
    connected_document_ids: Optional[List[str]] = None
    connected_folder_ids: Optional[List[str]] = []
    connected_asset_ids: Optional[List[str]] = []
    connected_qr_ids: Optional[List[str]] = []
    connected_card_ids: Optional[List[str]] = []
    connected_form_ids: Optional[List[str]] = []
    custom_fields: Optional[List[Dict[str, Any]]] = None
    activity_log: Optional[List[Dict[str, Any]]] = None

class Task(TaskBase):
    id: str = Field(alias="_id")
    workspace_id: str
    created_by: str
    created_at: datetime
    updated_at: datetime

    class Config:
        allow_population_by_field_name = True
