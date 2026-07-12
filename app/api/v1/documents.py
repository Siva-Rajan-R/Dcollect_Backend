from fastapi import APIRouter, Depends, HTTPException, status, Response, Header
from typing import Any, List,Optional
from app.api.deps import get_current_active_user
from app.schemas.user import UserInDB
from app.schemas.document import DocumentCreate, DocumentUpdate, Document
from app.db.mongodb import db
from bson import ObjectId
import datetime

router = APIRouter()

@router.post("/", response_model=Document)
async def create_document(
    *,
    doc_in: DocumentCreate,
    current_user: UserInDB = Depends(get_current_active_user)
) -> Any:
    # Verify member status in workspace
    member = await db.db.members.find_one({
        "workspace_id": doc_in.workspace_id,
        "user_id": current_user.id
    })
    if not member:
        raise HTTPException(status_code=403, detail="Not a member of this workspace")

    new_doc = doc_in.dict()
    new_doc["created_by"] = current_user.id
    new_doc["created_at"] = datetime.datetime.utcnow()
    new_doc["updated_at"] = datetime.datetime.utcnow()

    res = await db.db.documents.insert_one(new_doc)
    created = await db.db.documents.find_one({"_id": res.inserted_id})
    if created:
        created["_id"] = str(created["_id"])
    return Document(**created)

@router.get("/workspace/{workspace_id}", response_model=List[Document])
async def list_workspace_documents(
    workspace_id: str,
    current_user: UserInDB = Depends(get_current_active_user)
) -> Any:
    member = await db.db.members.find_one({
        "workspace_id": workspace_id,
        "user_id": current_user.id
    })
    if not member:
        raise HTTPException(status_code=403, detail="Not a member of this workspace")

    cursor = db.db.documents.find({"workspace_id": workspace_id}).sort("updated_at", -1)
    items = await cursor.to_list(length=100)
    for it in items:
        if "_id" in it:
            it["_id"] = str(it["_id"])
    return [Document(**it) for it in items]

@router.get("/{id}", response_model=Document)
async def get_document_details(
    id: str,
    current_user: UserInDB = Depends(get_current_active_user)
) -> Any:
    try:
        doc = await db.db.documents.find_one({"_id": ObjectId(id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Document ID")
        
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Verify membership
    member = await db.db.members.find_one({
        "workspace_id": doc["workspace_id"],
        "user_id": current_user.id
    })
    if not member:
        raise HTTPException(status_code=403, detail="Not authorized to view this document")

    if "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return Document(**doc)

@router.put("/{id}", response_model=Document)
async def update_document(
    id: str,
    doc_in: DocumentUpdate,
    current_user: UserInDB = Depends(get_current_active_user)
) -> Any:
    try:
        doc = await db.db.documents.find_one({"_id": ObjectId(id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Document ID")

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    member = await db.db.members.find_one({
        "workspace_id": doc["workspace_id"],
        "user_id": current_user.id
    })
    if not member:
        raise HTTPException(status_code=403, detail="Not authorized to edit this document")

    update_data = doc_in.dict(exclude_unset=True)
    update_data["updated_at"] = datetime.datetime.utcnow()

    await db.db.documents.update_one({"_id": ObjectId(id)}, {"$set": update_data})
    updated = await db.db.documents.find_one({"_id": ObjectId(id)})
    if updated:
        updated["_id"] = str(updated["_id"])
    return Document(**updated)

@router.delete("/{id}")
async def delete_document(
    id: str,
    current_user: UserInDB = Depends(get_current_active_user)
) -> Any:
    try:
        doc = await db.db.documents.find_one({"_id": ObjectId(id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Document ID")

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    member = await db.db.members.find_one({
        "workspace_id": doc["workspace_id"],
        "user_id": current_user.id
    })
    if not member:
        raise HTTPException(status_code=403, detail="Not authorized to delete this document")

    await db.db.documents.delete_one({"_id": ObjectId(id)})
    # Delete all attachments (assets) uploaded for this document
    await db.db.attachments.delete_many({"field_id": id})
    return {"status": "success", "message": "Document deleted successfully"}

@router.get("/{id}/download")
async def download_document(
    id: str,
    token: Optional[str] = None,
    authorization: Optional[str] = Header(None)
) -> Any:
    # Resolve user
    user = None
    if authorization and authorization.startswith("Bearer "):
        raw_token = authorization.split(" ")[1]
    else:
        raw_token = token

    if not raw_token:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        from jose import jwt
        from app.core.config import settings
        from app.schemas.token import TokenPayload
        payload = jwt.decode(raw_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        token_data = TokenPayload(**payload)
        user_doc = await db.db.users.find_one({"_id": ObjectId(token_data.sub)})
        if user_doc:
            if "_id" in user_doc:
                user_doc["_id"] = str(user_doc["_id"])
            user = UserInDB(**user_doc)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    if not user:
        raise HTTPException(status_code=401, detail="Invalid user")

    try:
        doc = await db.db.documents.find_one({"_id": ObjectId(id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Document ID")
        
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    member = await db.db.members.find_one({
        "workspace_id": doc["workspace_id"],
        "user_id": user.id
    })
    if not member:
        raise HTTPException(status_code=403, detail="Not authorized to download this document")

    # Clean HTML tags to text/markdown format or return as-is. We can return HTML as a .html file, or convert/return.
    # HTML is most complete because ProseMirror editor saves HTML content. Let's return as a clean HTML doc, or Markdown text.
    # Let's provide a markdown-like formatting by keeping HTML format which can be rendered directly by any browser!
    title_safe = doc.get("title", "Untitled").replace(" ", "_")
    content = doc.get("content", "")
    
    # Wrap in simple HTML page for full compatibility
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{doc.get("title", "Untitled")}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; max-width: 800px; margin: 40px auto; padding: 0 20px; color: #333; }}
        h1 {{ border-bottom: 1px solid #eee; padding-bottom: 10px; }}
        img {{ max-width: 100%; height: auto; }}
    </style>
</head>
<body>
    <h1>{doc.get("title", "Untitled")}</h1>
    {content}
</body>
</html>"""

    return Response(
        content=html_content,
        media_type="text/html",
        headers={
            "Content-Disposition": f'attachment; filename="{title_safe}.html"'
        }
    )
