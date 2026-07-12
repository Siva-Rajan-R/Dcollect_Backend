from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from app.api.deps import get_current_active_user
from app.schemas.record import RecordCreate, Record, RecordInDB, RecordUpdate, PaginatedRecords
from app.schemas.user import UserInDB
from app.db.mongodb import db
from bson import ObjectId
import math

router = APIRouter()

@router.post("/", response_model=Record)
async def create_record(
    *,
    record_in: RecordCreate,
    current_user: UserInDB = Depends(get_current_active_user),
) -> Any:
    """
    Submit a new record for a form.
    """
    form_doc = await db.db.forms.find_one({"_id": ObjectId(record_in.form_id)})
    if not form_doc:
        raise HTTPException(status_code=404, detail="Form not found")

    new_record = RecordInDB(
        **record_in.dict(),
        created_by=current_user.id
    )
    result = await db.db.records.insert_one(new_record.dict(by_alias=True, exclude={"id"}))
    created_record = await db.db.records.find_one({"_id": result.inserted_id})
    if created_record and "_id" in created_record:
        created_record["_id"] = str(created_record["_id"])
    return Record(**created_record)

@router.post("/public", response_model=Record)
async def create_public_record(
    *,
    record_in: RecordCreate,
) -> Any:
    """
    Submit a new record for a form publicly (unauthenticated).
    """
    form_doc = await db.db.forms.find_one({"_id": ObjectId(record_in.form_id)})
    if not form_doc:
        raise HTTPException(status_code=404, detail="Form not found")

    # If form is private, block submission
    is_public = form_doc.get("settings", {}).get("is_public", True)
    if not is_public:
        raise HTTPException(status_code=403, detail="This form is private and does not accept public responses")

    # Override workspace_id from form_doc just to be safe
    record_data = record_in.dict()
    record_data["workspace_id"] = form_doc["workspace_id"]

    new_record = RecordInDB(
        **record_data,
        created_by=None
    )
    result = await db.db.records.insert_one(new_record.dict(by_alias=True, exclude={"id"}))
    created_record = await db.db.records.find_one({"_id": result.inserted_id})
    if created_record and "_id" in created_record:
        created_record["_id"] = str(created_record["_id"])
    return Record(**created_record)

@router.get("/form/{form_id}", response_model=PaginatedRecords)
async def read_records(
    form_id: str,
    page: int = 1,
    limit: int = 10,
    current_user: UserInDB = Depends(get_current_active_user),
) -> Any:
    """
    Retrieve records for a given form with pagination.
    """
    from app.core.minio import get_minio_client
    total = await db.db.records.count_documents({"form_id": form_id})
    skip = (page - 1) * limit
    records_cursor = db.db.records.find({"form_id": form_id}).sort("created_at", -1).skip(skip).limit(limit)
    records = await records_cursor.to_list(length=limit)
    
    items = []
    minio_client = get_minio_client()
    for r in records:
        if "_id" in r:
            r["_id"] = str(r["_id"])
        
        # Query attachments for this record and generate presigned URLs
        r_attachments = {}
        att_cursor = db.db.attachments.find({"record_id": r["_id"]})
        atts = await att_cursor.to_list(length=100)
        for att in atts:
            try:
                url = minio_client.presigned_get_object(
                    bucket_name="dcollect-attachments",
                    object_name=att["minio_path"]
                )
                field_id = att["field_id"]
                if field_id not in r_attachments:
                    r_attachments[field_id] = []
                
                r_attachments[field_id].append({
                    "url": url,
                    "file_name": att["file_name"],
                    "mime_type": att.get("mime_type", "")
                })
            except Exception as e:
                print(f"Error presigning attachment URL: {e}")
        
        r["attachments"] = r_attachments
        items.append(Record(**r))

    pages = math.ceil(total / limit) if total > 0 else 1
    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": pages
    }
