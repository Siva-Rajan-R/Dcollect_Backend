from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, status
from app.api.deps import get_current_active_user
from app.schemas.workspace import WorkspaceCreate, Workspace, WorkspaceInDB
from app.schemas.member import MemberInDB, Role
from app.schemas.user import UserInDB
from app.db.mongodb import db
from bson import ObjectId
import datetime

router = APIRouter()

@router.post("/", response_model=Workspace)
async def create_workspace(
    *,
    workspace_in: WorkspaceCreate,
    current_user: UserInDB = Depends(get_current_active_user),
) -> Any:
    """
    Create new workspace.
    """
    new_workspace = WorkspaceInDB(
        name=workspace_in.name,
        logo_url=workspace_in.logo_url,
        settings=workspace_in.settings,
        owner_id=current_user.id
    )
    result = await db.db.workspaces.insert_one(new_workspace.dict(by_alias=True, exclude={"id"}))
    created_workspace = await db.db.workspaces.find_one({"_id": result.inserted_id})
    
    # Add owner as a member
    new_member = MemberInDB(
        user_id=current_user.id,
        workspace_id=str(result.inserted_id),
        role=Role.OWNER
    )
    await db.db.members.insert_one(new_member.dict(by_alias=True, exclude={"id"}))
    
    if "_id" in created_workspace:
        created_workspace["_id"] = str(created_workspace["_id"])
        
    return Workspace(**created_workspace)

@router.get("/", response_model=List[Workspace])
async def read_workspaces(
    current_user: UserInDB = Depends(get_current_active_user),
) -> Any:
    """
    Retrieve workspaces where the current user is a member.
    """
    # Find all memberships for this user
    memberships_cursor = db.db.members.find({"user_id": current_user.id})
    memberships = await memberships_cursor.to_list(length=100)
    
    if not memberships:
        from app.schemas.member import Role
        # Create default workspace automatically
        ws_insert = await db.db.workspaces.insert_one({
            "name": "My Workspace",
            "logo_url": None,
            "settings": {},
            "owner_id": current_user.id,
            "created_at": datetime.datetime.utcnow(),
            "updated_at": datetime.datetime.utcnow()
        })
        # Add owner as a member
        await db.db.members.insert_one({
            "user_id": current_user.id,
            "workspace_id": str(ws_insert.inserted_id),
            "role": Role.OWNER
        })
        # Reload memberships
        memberships_cursor = db.db.members.find({"user_id": current_user.id})
        memberships = await memberships_cursor.to_list(length=100)
    
    workspace_ids = [ObjectId(m["workspace_id"]) for m in memberships]
    
    # Get those workspaces
    workspaces_cursor = db.db.workspaces.find({"_id": {"$in": workspace_ids}})
    workspaces = await workspaces_cursor.to_list(length=100)
    
    for ws in workspaces:
        if "_id" in ws:
            ws["_id"] = str(ws["_id"])
            
    return [Workspace(**ws) for ws in workspaces]

@router.get("/{id}", response_model=Workspace)
async def read_workspace(
    *,
    id: str,
    current_user: UserInDB = Depends(get_current_active_user),
) -> Any:
    """
    Get workspace by ID.
    """
    workspace_doc = await db.db.workspaces.find_one({"_id": ObjectId(id)})
    if not workspace_doc:
        raise HTTPException(status_code=404, detail="Workspace not found")
        
    # Check membership
    member_doc = await db.db.members.find_one({"workspace_id": id, "user_id": current_user.id})
    if not member_doc:
        raise HTTPException(status_code=403, detail="Not enough permissions")
        
    if "_id" in workspace_doc:
        workspace_doc["_id"] = str(workspace_doc["_id"])
        
    return Workspace(**workspace_doc)

@router.get("/{id}/stats")
async def read_workspace_stats(
    id: str,
    current_user: UserInDB = Depends(get_current_active_user),
) -> Any:
    """
    Get aggregated dashboard stats for a workspace.
    """
    # Check membership
    member_doc = await db.db.members.find_one({"workspace_id": id, "user_id": current_user.id})
    if not member_doc:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    # Get forms
    forms_cursor = db.db.forms.find({"workspace_id": id})
    forms = await forms_cursor.to_list(length=100)
    total_forms = len(forms)

    # Get members count
    total_members = await db.db.members.count_documents({"workspace_id": id})

    # Get records counts
    form_ids = [str(f["_id"]) for f in forms]
    total_records = 0
    active_forms = []
    
    for form in forms:
        form_id_str = str(form["_id"])
        count = await db.db.records.count_documents({"form_id": form_id_str})
        total_records += count
        active_forms.append({
            "id": form_id_str,
            "name": form["name"],
            "submissions_count": count
        })

    # Get 5 recent submissions
    recent_submissions = []
    if form_ids:
        recent_cursor = db.db.records.find({"form_id": {"$in": form_ids}}).sort("created_at", -1).limit(5)
        recent_docs = await recent_cursor.to_list(length=5)
        for r in recent_docs:
            f_name = "Unknown Form"
            for form in forms:
                if str(form["_id"]) == r["form_id"]:
                    f_name = form["name"]
                    break
            recent_submissions.append({
                "id": str(r["_id"]),
                "form_name": f_name,
                "created_at": r["created_at"],
                "data": r["data"]
            })

    # Sort active forms by submissions count
    active_forms.sort(key=lambda x: x["submissions_count"], reverse=True)

    return {
        "total_forms": total_forms,
        "total_records": total_records,
        "total_members": total_members,
        "active_forms": active_forms[:5],
        "recent_submissions": recent_submissions
    }

@router.put("/{id}", response_model=Workspace)
async def update_workspace(
    *,
    id: str,
    workspace_in: WorkspaceCreate,
    current_user: UserInDB = Depends(get_current_active_user),
) -> Any:
    """
    Update workspace name/details.
    """
    workspace_doc = await db.db.workspaces.find_one({"_id": ObjectId(id)})
    if not workspace_doc:
        raise HTTPException(status_code=404, detail="Workspace not found")
        
    # Check ownership
    if workspace_doc["owner_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Only owners can edit workspace settings")
        
    update_data = {}
    if workspace_in.name is not None:
        update_data["name"] = workspace_in.name
    if workspace_in.logo_url is not None:
        update_data["logo_url"] = workspace_in.logo_url
    if workspace_in.settings is not None:
        update_data["settings"] = workspace_in.settings
        
    await db.db.workspaces.update_one({"_id": ObjectId(id)}, {"$set": update_data})
    
    updated_ws = await db.db.workspaces.find_one({"_id": ObjectId(id)})
    if "_id" in updated_ws:
        updated_ws["_id"] = str(updated_ws["_id"])
    return Workspace(**updated_ws)

@router.get("/{id}/members")
async def get_workspace_members(
    id: str,
    current_user: UserInDB = Depends(get_current_active_user),
) -> Any:
    """
    List all members in a workspace, including user details.
    """
    member_check = await db.db.members.find_one({"workspace_id": id, "user_id": current_user.id})
    if not member_check:
        raise HTTPException(status_code=403, detail="Not enough permissions")
        
    members_cursor = db.db.members.find({"workspace_id": id})
    members_list = await members_cursor.to_list(length=100)
    
    result = []
    for m in members_list:
        u_id = m["user_id"]
        user_doc = None
        if isinstance(u_id, ObjectId):
            user_doc = await db.db.users.find_one({"_id": u_id})
            if not user_doc:
                user_doc = await db.db.users.find_one({"_id": str(u_id)})
        else:
            try:
                user_doc = await db.db.users.find_one({"_id": ObjectId(u_id)})
            except Exception:
                pass
            if not user_doc:
                user_doc = await db.db.users.find_one({"_id": str(u_id)})
                
        if user_doc:
            result.append({
                "user_id": str(u_id),
                "name": user_doc.get("full_name") or user_doc.get("email").split("@")[0],
                "email": user_doc["email"],
                "role": m["role"],
                "joined_at": m["joined_at"],
                "service_permissions": m.get("service_permissions") or {},
            })
    return result

@router.post("/{id}/members")
async def add_workspace_member(
    id: str,
    payload: dict,
    current_user: UserInDB = Depends(get_current_active_user),
) -> Any:
    """
    Invite/add a new member by email.
    """
    member_check = await db.db.members.find_one({"workspace_id": id, "user_id": current_user.id})
    if not member_check or member_check["role"] != "Owner":
        raise HTTPException(status_code=403, detail="Only Owners can manage workspace members")
        
    email = payload.get("email")
    role = payload.get("role", "Viewer")
    service_permissions = payload.get("service_permissions", {})
    
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")
        
    invited_user = await db.db.users.find_one({"email": email})
    if not invited_user:
        raise HTTPException(status_code=404, detail="User with this email is not registered")
        
    invited_user_id = str(invited_user["_id"])
    
    existing_member = await db.db.members.find_one({"workspace_id": id, "user_id": invited_user_id})
    if existing_member:
        raise HTTPException(status_code=400, detail="User is already a member of this workspace")
        
    from app.schemas.member import MemberInDB, Role as MemberRole
    import datetime
    new_mem_doc = {
        "user_id": invited_user_id,
        "workspace_id": id,
        "role": MemberRole(role),
        "service_permissions": service_permissions,
        "joined_at": datetime.datetime.utcnow(),
    }
    await db.db.members.insert_one(new_mem_doc)
    return {"status": "success", "message": "Member added successfully"}

@router.delete("/{id}/members/{user_id}")
async def remove_workspace_member(
    id: str,
    user_id: str,
    current_user: UserInDB = Depends(get_current_active_user),
) -> Any:
    """
    Remove a member from the workspace.
    """
    member_check = await db.db.members.find_one({"workspace_id": id, "user_id": current_user.id})
    if not member_check or member_check["role"] != "Owner":
        raise HTTPException(status_code=403, detail="Only Owners can manage workspace members")
        
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot remove yourself from the workspace")
        
    await db.db.members.delete_one({"workspace_id": id, "user_id": user_id})
    return {"status": "success", "message": "Member removed successfully"}

@router.patch("/{id}/members/{user_id}/permissions")
async def update_member_permissions(
    id: str,
    user_id: str,
    payload: dict,
    current_user: UserInDB = Depends(get_current_active_user),
) -> Any:
    """
    Update the service_permissions of an existing workspace member.
    Only Owners can do this.
    """
    member_check = await db.db.members.find_one({"workspace_id": id, "user_id": current_user.id})
    if not member_check or member_check["role"] != "Owner":
        raise HTTPException(status_code=403, detail="Only Owners can manage member permissions")

    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot edit your own permissions")

    target_member = await db.db.members.find_one({"workspace_id": id, "user_id": user_id})
    if not target_member:
        raise HTTPException(status_code=404, detail="Member not found in this workspace")

    service_permissions = payload.get("service_permissions", {})
    valid_services = {"forms", "qrcodes", "cards", "tasks", "documents", "assets"}
    valid_access = {"none", "read", "write"}

    # Validate and sanitise
    cleaned = {}
    for svc, acc in service_permissions.items():
        if svc in valid_services and acc in valid_access:
            cleaned[svc] = acc

    await db.db.members.update_one(
        {"workspace_id": id, "user_id": user_id},
        {"$set": {"service_permissions": cleaned}}
    )
    return {"status": "success", "message": "Permissions updated", "service_permissions": cleaned}


@router.delete("/{id}")
async def delete_workspace(
    id: str,
    current_user: UserInDB = Depends(get_current_active_user),
) -> Any:
    """
    Delete a workspace. Only owners can delete it.
    """
    workspace_doc = await db.db.workspaces.find_one({"_id": ObjectId(id)})
    if not workspace_doc:
        raise HTTPException(status_code=404, detail="Workspace not found")
        
    # Check ownership
    if workspace_doc["owner_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Only owners can delete the workspace")
        
    # Delete workspace document
    await db.db.workspaces.delete_one({"_id": ObjectId(id)})
    
    # Delete all members associated
    await db.db.members.delete_many({"workspace_id": id})
    
    # Delete other workspace-specific resources
    await db.db.forms.delete_many({"workspace_id": id})
    await db.db.qrcodes.delete_many({"workspace_id": id})
    await db.db.cards.delete_many({"workspace_id": id})
    await db.db.tasks.delete_many({"workspace_id": id})
    await db.db.documents.delete_many({"workspace_id": id})
    await db.db.assets.delete_many({"workspace_id": id})
    
    return {"status": "success", "message": "Workspace deleted successfully"}



