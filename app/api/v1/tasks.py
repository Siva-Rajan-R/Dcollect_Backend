from fastapi import APIRouter, Depends, HTTPException, status
from typing import Any, List
from app.api.deps import get_current_active_user
from app.schemas.user import UserInDB
from app.schemas.task import TaskCreate, TaskUpdate, Task
from app.db.mongodb import db
from bson import ObjectId
import datetime

router = APIRouter()

@router.post("/", response_model=Task)
async def create_task(
    *,
    task_in: TaskCreate,
    current_user: UserInDB = Depends(get_current_active_user)
) -> Any:
    member = await db.db.members.find_one({
        "workspace_id": task_in.workspace_id,
        "user_id": current_user.id
    })
    if not member:
        raise HTTPException(status_code=403, detail="Not a member of this workspace")

    new_task = task_in.dict()
    new_task["created_by"] = current_user.id
    new_task["created_at"] = datetime.datetime.utcnow()
    new_task["updated_at"] = datetime.datetime.utcnow()

    res = await db.db.tasks.insert_one(new_task)
    created = await db.db.tasks.find_one({"_id": res.inserted_id})
    if created:
        created["_id"] = str(created["_id"])
    return Task(**created)

@router.get("/workspace/{workspace_id}", response_model=List[Task])
async def list_workspace_tasks(
    workspace_id: str,
    current_user: UserInDB = Depends(get_current_active_user)
) -> Any:
    member = await db.db.members.find_one({
        "workspace_id": workspace_id,
        "user_id": current_user.id
    })
    if not member:
        raise HTTPException(status_code=403, detail="Not a member of this workspace")

    cursor = db.db.tasks.find({"workspace_id": workspace_id})
    items = await cursor.to_list(length=200)
    for it in items:
        if "_id" in it:
            it["_id"] = str(it["_id"])
    return [Task(**it) for it in items]

@router.put("/{id}", response_model=Task)
async def update_task(
    id: str,
    task_in: TaskUpdate,
    current_user: UserInDB = Depends(get_current_active_user)
) -> Any:
    try:
        task = await db.db.tasks.find_one({"_id": ObjectId(id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Task ID")

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    member = await db.db.members.find_one({
        "workspace_id": task["workspace_id"],
        "user_id": current_user.id
    })
    if not member:
        raise HTTPException(status_code=403, detail="Not authorized to edit this task")

    update_data = task_in.dict(exclude_unset=True)
    update_data["updated_at"] = datetime.datetime.utcnow()

    await db.db.tasks.update_one({"_id": ObjectId(id)}, {"$set": update_data})
    updated = await db.db.tasks.find_one({"_id": ObjectId(id)})
    if updated:
        updated["_id"] = str(updated["_id"])
    return Task(**updated)

@router.delete("/{id}")
async def delete_task(
    id: str,
    current_user: UserInDB = Depends(get_current_active_user)
) -> Any:
    try:
        task = await db.db.tasks.find_one({"_id": ObjectId(id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Task ID")

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    member = await db.db.members.find_one({
        "workspace_id": task["workspace_id"],
        "user_id": current_user.id
    })
    if not member:
        raise HTTPException(status_code=403, detail="Not authorized to delete this task")

    await db.db.tasks.delete_one({"_id": ObjectId(id)})
    return {"status": "success", "message": "Task deleted successfully"}
