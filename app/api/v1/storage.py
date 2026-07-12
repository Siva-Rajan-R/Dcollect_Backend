import uuid
import io
import zipfile
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Header
from fastapi.responses import RedirectResponse, StreamingResponse
from app.api.deps import get_current_active_user
from app.schemas.attachment import Attachment, AttachmentInDB
from app.schemas.folder import Folder, FolderCreate, FolderUpdate
from app.schemas.user import UserInDB
from app.core.minio import get_minio_client
from app.core.config import settings
from app.db.mongodb import db
from bson import ObjectId
from jose import jwt
from app.schemas.token import TokenPayload
import datetime

router = APIRouter()

BUCKET_NAME = "dcollect-attachments"

# Helper function to manually verify JWT token from query string or headers
async def get_user_from_token_or_header(
    authorization: Optional[str] = Header(None),
    token: Optional[str] = None
) -> Optional[UserInDB]:
    raw_token = None
    if authorization and authorization.startswith("Bearer "):
        raw_token = authorization.split(" ")[1]
    elif token:
        raw_token = token
        
    if not raw_token:
        return None
        
    try:
        payload = jwt.decode(
            raw_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
        user_doc = await db.db.users.find_one({"_id": ObjectId(token_data.sub)})
        if user_doc:
            if "_id" in user_doc:
                user_doc["_id"] = str(user_doc["_id"])
            return UserInDB(**user_doc)
    except Exception:
        return None
    return None

# Helper to automatically resolve or create folders for forms, cards, documents, etc.
async def get_or_create_auto_folder(
    workspace_id: str,
    item_name: str,
    item_type: str,
    user_id: str
) -> Optional[str]:
    if not workspace_id or not item_name:
        return None
        
    folder_name = item_name.strip()
    # Auto-folders created here are always of type "assets"
    folder_type = "assets"
    
    # Check if folder exists at Root level with same type
    folder = await db.db.folders.find_one({
        "workspace_id": workspace_id,
        "parent_folder_id": None,
        "folder_type": folder_type,
        "name": folder_name
    })
    if folder:
        return str(folder["_id"])
        
    # Create new folder inheriting 'members' access level by default
    new_folder = {
        "workspace_id": workspace_id,
        "name": folder_name,
        "access_level": "members",
        "parent_folder_id": None,
        "folder_type": folder_type,
        "created_by": user_id,
        "created_at": datetime.datetime.utcnow()
    }
    res = await db.db.folders.insert_one(new_folder)
    return str(res.inserted_id)

# ==================== FOLDERS CRUD ====================

@router.post("/folders", response_model=Folder)
async def create_folder(
    folder_in: FolderCreate,
    current_user: UserInDB = Depends(get_current_active_user),
) -> Any:
    # Verify member status in workspace
    member = await db.db.members.find_one({
        "workspace_id": folder_in.workspace_id,
        "user_id": current_user.id
    })
    if not member:
        raise HTTPException(status_code=403, detail="Not a member of this workspace")

    # Enforce unique folder names constraint under same parent folder and same type
    p_id = folder_in.parent_folder_id if folder_in.parent_folder_id and folder_in.parent_folder_id != "null" else None
    existing = await db.db.folders.find_one({
        "workspace_id": folder_in.workspace_id,
        "parent_folder_id": p_id,
        "folder_type": folder_in.folder_type,
        "name": folder_in.name.strip()
    })
    if existing:
        raise HTTPException(status_code=400, detail="A folder with this name already exists in this folder level")

    new_folder = folder_in.dict()
    new_folder["name"] = folder_in.name.strip()
    new_folder["parent_folder_id"] = p_id
    new_folder["created_by"] = current_user.id
    new_folder["created_at"] = datetime.datetime.utcnow()

    res = await db.db.folders.insert_one(new_folder)
    created = await db.db.folders.find_one({"_id": res.inserted_id})
    if created:
        created["_id"] = str(created["_id"])
    return Folder(**created)

@router.get("/folders/workspace/{workspace_id}", response_model=List[Folder])
async def list_workspace_folders(
    workspace_id: str,
    folder_type: Optional[str] = None,
    current_user: UserInDB = Depends(get_current_active_user),
) -> Any:
    member = await db.db.members.find_one({
        "workspace_id": workspace_id,
        "user_id": current_user.id
    })
    if not member:
        raise HTTPException(status_code=403, detail="Not a member of this workspace")

    query: dict = {"workspace_id": workspace_id}
    if folder_type:
        query["folder_type"] = folder_type

    cursor = db.db.folders.find(query)
    items = await cursor.to_list(length=200)
    for it in items:
        if "_id" in it:
            it["_id"] = str(it["_id"])
    return [Folder(**it) for it in items]

@router.put("/folders/{id}", response_model=Folder)
async def update_folder(
    id: str,
    folder_in: FolderUpdate,
    current_user: UserInDB = Depends(get_current_active_user),
) -> Any:
    try:
        folder = await db.db.folders.find_one({"_id": ObjectId(id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Folder ID")

    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    member = await db.db.members.find_one({
        "workspace_id": folder["workspace_id"],
        "user_id": current_user.id
    })
    if not member:
        raise HTTPException(status_code=403, detail="Not authorized to edit this folder")

    update_data = folder_in.dict(exclude_unset=True)
    await db.db.folders.update_one({"_id": ObjectId(id)}, {"$set": update_data})
    
    # Cascade access levels to children files if folder access level changes
    if "access_level" in update_data:
        await db.db.attachments.update_many(
            {"folder_id": id},
            {"$set": {"access_level": update_data["access_level"]}}
        )

    updated = await db.db.folders.find_one({"_id": ObjectId(id)})
    if updated:
        updated["_id"] = str(updated["_id"])
    return Folder(**updated)

@router.delete("/folders/{id}")
async def delete_folder(
    id: str,
    current_user: UserInDB = Depends(get_current_active_user),
) -> Any:
    try:
        folder = await db.db.folders.find_one({"_id": ObjectId(id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Folder ID")

    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    member = await db.db.members.find_one({
        "workspace_id": folder["workspace_id"],
        "user_id": current_user.id
    })
    if not member:
        raise HTTPException(status_code=403, detail="Not authorized to delete this folder")

    parent_id = folder.get("parent_folder_id")
    await db.db.folders.delete_one({"_id": ObjectId(id)})
    # Delete all attachments (assets) belonging to this folder
    await db.db.attachments.delete_many({"folder_id": id})
    # Move child folders to deleted folder's parent
    await db.db.folders.update_many(
        {"parent_folder_id": id},
        {"$set": {"parent_folder_id": parent_id}}
    )
    # Move child documents to deleted folder's parent
    await db.db.documents.update_many(
        {"folder_id": id},
        {"$set": {"folder_id": parent_id}}
    )
    return {"status": "success", "message": "Folder deleted successfully"}

# ==================== UPLOADS & DOWNLOADS ====================

@router.post("/upload", response_model=Attachment)
async def upload_file(
    record_id: str = Form(...),
    field_id: str = Form(...),
    folder_id: Optional[str] = Form(None),
    access_level: Optional[str] = Form("members"),
    workspace_id: Optional[str] = Form(None),
    item_name: Optional[str] = Form(None),
    item_type: Optional[str] = Form(None),
    file: UploadFile = File(...),
    current_user: UserInDB = Depends(get_current_active_user),
) -> Any:
    minio_client = get_minio_client()
    
    # Ensure bucket exists
    found = minio_client.bucket_exists(BUCKET_NAME)
    if not found:
        minio_client.make_bucket(BUCKET_NAME)
        
    file_extension = file.filename.split(".")[-1] if "." in file.filename else ""
    object_name = f"{record_id}/{field_id}/{uuid.uuid4()}.{file_extension}"
    
    try:
        # Upload the file
        minio_client.put_object(
            bucket_name=BUCKET_NAME,
            object_name=object_name,
            data=file.file,
            length=-1, # Unknown length for streaming
            part_size=10*1024*1024, # 10MB parts
            content_type=file.content_type
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
    resolved_folder_id = folder_id if folder_id and folder_id != "null" else None
    
    # Auto-folder creation if item_name is specified
    if workspace_id and item_name:
        auto_id = await get_or_create_auto_folder(workspace_id, item_name, item_type or "uploads", current_user.id)
        if auto_id:
            resolved_folder_id = auto_id

    new_attachment = AttachmentInDB(
        record_id=record_id,
        field_id=field_id,
        file_name=file.filename,
        minio_path=object_name,
        size=0,
        mime_type=file.content_type,
        folder_id=resolved_folder_id,
        access_level=access_level,
        uploaded_by=current_user.id
    )
    
    result = await db.db.attachments.insert_one(new_attachment.dict(by_alias=True, exclude={"id"}))
    created_attachment = await db.db.attachments.find_one({"_id": result.inserted_id})
    if created_attachment and "_id" in created_attachment:
        created_attachment["id"] = str(created_attachment["_id"])
        created_attachment["_id"] = str(created_attachment["_id"])
    return Attachment(**created_attachment)

@router.post("/upload/public", response_model=Attachment)
async def upload_file_public(
    record_id: str = Form(...),
    field_id: str = Form(...),
    workspace_id: Optional[str] = Form(None),
    item_name: Optional[str] = Form(None),
    item_type: Optional[str] = Form(None),
    file: UploadFile = File(...),
) -> Any:
    """
    Upload a file to MinIO publicly (unauthenticated) and auto-group into folders.
    """
    minio_client = get_minio_client()
    
    # Ensure bucket exists
    found = minio_client.bucket_exists(BUCKET_NAME)
    if not found:
        minio_client.make_bucket(BUCKET_NAME)
        
    file_extension = file.filename.split(".")[-1] if "." in file.filename else ""
    object_name = f"{record_id}/{field_id}/{uuid.uuid4()}.{file_extension}"
    
    try:
        # Upload the file
        minio_client.put_object(
            bucket_name=BUCKET_NAME,
            object_name=object_name,
            data=file.file,
            length=-1, # Unknown length for streaming
            part_size=10*1024*1024, # 10MB parts
            content_type=file.content_type
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
    resolved_folder_id = None
    
    # Auto-folder creation if item_name is specified (uses "anonymous" creator ID for public uploads)
    if workspace_id and item_name:
        auto_id = await get_or_create_auto_folder(workspace_id, item_name, item_type or "uploads", "anonymous")
        if auto_id:
            resolved_folder_id = auto_id

    new_attachment = AttachmentInDB(
        record_id=record_id,
        field_id=field_id,
        file_name=file.filename,
        minio_path=object_name,
        size=0,
        mime_type=file.content_type,
        folder_id=resolved_folder_id,
        access_level="public",
        uploaded_by="anonymous"
    )
    
    result = await db.db.attachments.insert_one(new_attachment.dict(by_alias=True, exclude={"id"}))
    created_attachment = await db.db.attachments.find_one({"_id": result.inserted_id})
    if created_attachment and "_id" in created_attachment:
        created_attachment["id"] = str(created_attachment["_id"])
        created_attachment["_id"] = str(created_attachment["_id"])
    return Attachment(**created_attachment)

@router.put("/attachments/{id}", response_model=Attachment)
async def update_attachment_permissions(
    id: str,
    payload: dict,
    current_user: UserInDB = Depends(get_current_active_user),
) -> Any:
    try:
        att = await db.db.attachments.find_one({"_id": ObjectId(id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Attachment ID")
        
    if not att:
        raise HTTPException(status_code=404, detail="Attachment not found")

    update_fields = {}
    if "access_level" in payload:
        update_fields["access_level"] = payload["access_level"]
    if "folder_id" in payload:
        f_id = payload["folder_id"]
        update_fields["folder_id"] = f_id if f_id and f_id != "null" else None

    if update_fields:
        await db.db.attachments.update_one({"_id": ObjectId(id)}, {"$set": update_fields})
        
    updated = await db.db.attachments.find_one({"_id": ObjectId(id)})
    if updated:
        updated["_id"] = str(updated["_id"])
    return Attachment(**updated)

@router.delete("/attachments/{id}")
async def delete_attachment(
    id: str,
    current_user: UserInDB = Depends(get_current_active_user),
) -> Any:
    try:
        att = await db.db.attachments.find_one({"_id": ObjectId(id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Attachment ID")
        
    if not att:
        raise HTTPException(status_code=404, detail="Attachment not found")

    await db.db.attachments.delete_one({"_id": ObjectId(id)})
    return {"status": "success", "message": "File deleted successfully"}

@router.get("/download/{attachment_id}")
async def download_file(
    attachment_id: str,
    current_user: UserInDB = Depends(get_current_active_user),
) -> Any:
    from bson import ObjectId
    attachment_doc = await db.db.attachments.find_one({"_id": ObjectId(attachment_id)})
    if not attachment_doc:
        raise HTTPException(status_code=404, detail="Attachment not found")
        
    minio_client = get_minio_client()
    url = minio_client.presigned_get_object(
        bucket_name=BUCKET_NAME,
        object_name=attachment_doc["minio_path"]
    )
    if "minio:" in url:
        url = url.replace("minio:9000", "localhost:9000")
    elif "127.0.0.1:" in url:
        url = url.replace("127.0.0.1:9000", "localhost:9000")
    return {"url": url}

@router.get("/download/public/{attachment_id}")
async def download_file_public(
    attachment_id: str,
    token: Optional[str] = None,
    authorization: Optional[str] = Header(None)
) -> Any:
    from bson import ObjectId
    try:
        attachment_doc = await db.db.attachments.find_one({"_id": ObjectId(attachment_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Attachment ID")
        
    if not attachment_doc:
        raise HTTPException(status_code=404, detail="Attachment not found")
        
    access = attachment_doc.get("access_level", "public")
    
    # Enforce permissions
    if access in ["members", "owner"]:
        user = await get_user_from_token_or_header(authorization, token)
        if not user:
            raise HTTPException(status_code=401, detail="Authentication required for this secure asset")
        
        # If Owner: only the uploader can access
        if access == "owner" and attachment_doc.get("uploaded_by") != user.id:
            raise HTTPException(status_code=403, detail="Only the file owner has access to this asset")
            
    minio_client = get_minio_client()
    url = minio_client.presigned_get_object(
        bucket_name=BUCKET_NAME,
        object_name=attachment_doc["minio_path"]
    )
    if "minio:" in url:
        url = url.replace("minio:9000", "localhost:9000")
    elif "127.0.0.1:" in url:
        url = url.replace("127.0.0.1:9000", "localhost:9000")
        
    return RedirectResponse(url=url)

@router.get("/record/{record_id}", response_model=List[Attachment])
async def get_record_attachments(
    record_id: str,
    current_user: UserInDB = Depends(get_current_active_user),
) -> Any:
    cursor = db.db.attachments.find({"record_id": record_id})
    attachments = await cursor.to_list(length=100)
    for att in attachments:
        if "_id" in att:
            att["_id"] = str(att["_id"])
    return [Attachment(**att) for att in attachments]

@router.get("/workspace/{workspace_id}", response_model=List[Attachment])
async def get_workspace_attachments(
    workspace_id: str,
    current_user: UserInDB = Depends(get_current_active_user),
) -> Any:
    # Find all attachments belonging to this workspace (via matching member workspace validation)
    member = await db.db.members.find_one({
        "workspace_id": workspace_id,
        "user_id": current_user.id
    })
    if not member:
        raise HTTPException(status_code=403, detail="Not authorized to access this workspace")

    # In our uploads, we saved record_id="documents" or workspace_id/form_id/etc.
    # To associate files with a workspace, we fetch all files uploaded by members of this workspace, 
    # or files associated with records in this workspace, or simply look up files in the workspace.
    # Let's filter files that match the record_id="documents" (which are created in documents) 
    # or generic workspace assets.
    # Since documents have workspace_id, we can look up documents in the workspace:
    docs = await db.db.documents.find({"workspace_id": workspace_id}).to_list(length=500)
    doc_ids = [str(d["_id"]) for d in docs]
    
    # Query files where record_id is "documents" or folder matches folders in the workspace, 
    # or the upload record matches a document ID in the workspace
    folders = await db.db.folders.find({"workspace_id": workspace_id}).to_list(length=100)
    folder_ids = [str(f["_id"]) for f in folders]
    
    query = {
        "$or": [
            {"folder_id": {"$in": folder_ids}},
            {"field_id": {"$in": doc_ids}},
            {"record_id": workspace_id},
            {"record_id": "documents"} # Default document assets
        ]
    }
    
    cursor = db.db.attachments.find(query)
    attachments = await cursor.to_list(length=500)
    for att in attachments:
      if "_id" in att:
        att["_id"] = str(att["_id"])
    return [Attachment(**att) for att in attachments]

@router.get("/folders/{id}/zip")
async def download_folder_zip(
    id: str,
    current_user: UserInDB = Depends(get_current_active_user)
) -> Any:
    try:
        root_folder = await db.db.folders.find_one({"_id": ObjectId(id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Folder ID")
        
    if not root_folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    member = await db.db.members.find_one({
        "workspace_id": root_folder["workspace_id"],
        "user_id": current_user.id
    })
    if not member:
        raise HTTPException(status_code=403, detail="Not authorized to download this folder")

    # In-memory ZIP buffer
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        async def add_folder_to_zip(folder_id_str: str, current_path: str):
            # 1. Fetch and write all child folders recursively
            child_folders = await db.db.folders.find({"parent_folder_id": folder_id_str}).to_list(length=100)
            for folder in child_folders:
                folder_name = folder.get("name", "Unnamed_Folder").replace("/", "_")
                new_path = f"{current_path}{folder_name}/"
                await add_folder_to_zip(str(folder["_id"]), new_path)

            # 2. If it's a document/notes folder, write document notes
            docs = await db.db.documents.find({"folder_id": folder_id_str}).to_list(length=500)
            for doc in docs:
                title = doc.get("title", "Untitled").replace("/", "_").replace(" ", "_")
                content = doc.get("content", "")
                html_doc = f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{title}</title></head><body><h1>{title}</h1>{content}</body></html>"
                zip_file.writestr(f"{current_path}{title}.html", html_doc)

            # 3. If it's an assets folder or has attachments, fetch from MinIO
            attachments = await db.db.attachments.find({"folder_id": folder_id_str}).to_list(length=500)
            minio_client = get_minio_client()
            for att in attachments:
                file_name = att.get("file_name", "file").replace("/", "_")
                minio_path = att.get("minio_path")
                if minio_path:
                    try:
                        # Fetch file from MinIO bucket
                        minio_response = minio_client.get_object(BUCKET_NAME, minio_path)
                        file_data = minio_response.read()
                        zip_file.writestr(f"{current_path}{file_name}", file_data)
                    except Exception as err:
                        print(f"Failed to fetch {file_name} from MinIO: {err}")

        # Start zipping from root folder
        root_folder_name = root_folder.get("name", "Archive").replace("/", "_")
        await add_folder_to_zip(id, f"{root_folder_name}/")

    zip_buffer.seek(0)
    
    # Return streaming zip file
    safe_name = root_folder_name.replace(" ", "_")
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}.zip"'
        }
    )
