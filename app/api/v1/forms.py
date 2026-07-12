from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from app.api.deps import get_current_active_user
from app.schemas.form import FormCreate, Form, FormInDB, FormDetails, FormUpdate, PaginatedForms
from app.schemas.field import FormFieldCreate, FormField, FormFieldInDB, FormFieldUpdate
from app.schemas.user import UserInDB
from app.db.mongodb import db
from bson import ObjectId
import math

router = APIRouter()

@router.post("/", response_model=Form)
async def create_form(
    *,
    form_in: FormCreate,
    current_user: UserInDB = Depends(get_current_active_user),
) -> Any:
    """
    Create a new form in a workspace.
    """
    member = await db.db.members.find_one({
        "workspace_id": form_in.workspace_id,
        "user_id": current_user.id
    })
    if not member or member.get("role") in ["Viewer", "Guest"]:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    new_form = FormInDB(
        **form_in.dict(),
        created_by=current_user.id
    )
    result = await db.db.forms.insert_one(new_form.dict(by_alias=True, exclude={"id"}))
    created_form = await db.db.forms.find_one({"_id": result.inserted_id})
    if created_form and "_id" in created_form:
        created_form["_id"] = str(created_form["_id"])
    return Form(**created_form)

@router.get("/workspace/{workspace_id}", response_model=PaginatedForms)
async def read_forms(
    workspace_id: str,
    page: int = 1,
    limit: int = 10,
    current_user: UserInDB = Depends(get_current_active_user),
) -> Any:
    """
    Retrieve forms for a given workspace with pagination.
    """
    member = await db.db.members.find_one({
        "workspace_id": workspace_id,
        "user_id": current_user.id
    })
    if not member:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    total = await db.db.forms.count_documents({"workspace_id": workspace_id})
    skip = (page - 1) * limit
    forms_cursor = db.db.forms.find({"workspace_id": workspace_id}).skip(skip).limit(limit)
    forms = await forms_cursor.to_list(length=limit)
    
    items = []
    for f in forms:
        if "_id" in f:
            f["_id"] = str(f["_id"])
        items.append(Form(**f))

    pages = math.ceil(total / limit) if total > 0 else 1
    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": pages
    }

@router.get("/public/{form_id}", response_model=FormDetails)
async def read_public_form(
    form_id: str,
) -> Any:
    """
    Retrieve form details publicly (unauthenticated) if it is public.
    """
    try:
        oid = ObjectId(form_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Form ID")

    form_doc = await db.db.forms.find_one({"_id": oid})
    if not form_doc:
        raise HTTPException(status_code=404, detail="Form not found")

    # If form is private, raise error (defaulting settings to public if not set)
    is_public = form_doc.get("settings", {}).get("is_public", True)
    if not is_public:
        raise HTTPException(status_code=403, detail="This form is private")

    fields_cursor = db.db.fields.find({"form_id": form_id}).sort("order", 1)
    fields = await fields_cursor.to_list(length=100)
    
    if "_id" in form_doc:
        form_doc["_id"] = str(form_doc["_id"])
        
    for field in fields:
        if "_id" in field:
            field["_id"] = str(field["_id"])

    return FormDetails(**form_doc, fields=[FormField(**f) for f in fields])

@router.get("/{form_id}", response_model=FormDetails)
async def read_form(
    form_id: str,
    current_user: UserInDB = Depends(get_current_active_user),
) -> Any:
    """
    Retrieve a form with its fields.
    """
    try:
        oid = ObjectId(form_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Form ID")

    form_doc = await db.db.forms.find_one({"_id": oid})
    if not form_doc:
        raise HTTPException(status_code=404, detail="Form not found")

    fields_cursor = db.db.fields.find({"form_id": form_id}).sort("order", 1)
    fields = await fields_cursor.to_list(length=100)
    
    if "_id" in form_doc:
        form_doc["_id"] = str(form_doc["_id"])
        
    for field in fields:
        if "_id" in field:
            field["_id"] = str(field["_id"])

    return FormDetails(**form_doc, fields=[FormField(**f) for f in fields])

@router.put("/{form_id}", response_model=FormDetails)
async def update_form(
    form_id: str,
    form_in: FormUpdate,
    current_user: UserInDB = Depends(get_current_active_user),
) -> Any:
    """
    Update form details and its fields in bulk.
    """
    try:
        oid = ObjectId(form_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Form ID")

    form_doc = await db.db.forms.find_one({"_id": oid})
    if not form_doc:
        raise HTTPException(status_code=404, detail="Form not found")

    member = await db.db.members.find_one({
        "workspace_id": form_doc["workspace_id"],
        "user_id": current_user.id
    })
    if not member or member.get("role") in ["Viewer", "Guest"]:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    # Update form metadata
    update_data = {}
    if form_in.name is not None:
        update_data["name"] = form_in.name
    if form_in.description is not None:
        update_data["description"] = form_in.description
    if form_in.settings is not None:
        update_data["settings"] = form_in.settings

    if update_data:
        await db.db.forms.update_one({"_id": oid}, {"$set": update_data})

    # Update fields in bulk if provided
    if form_in.fields is not None:
        incoming_field_ids = []
        for field in form_in.fields:
            if field.id:
                # Update existing field
                await db.db.fields.update_one(
                    {"_id": ObjectId(field.id)},
                    {"$set": {
                        "name": field.name,
                        "type": field.type,
                        "options": field.options.dict(),
                        "order": field.order
                    }}
                )
                incoming_field_ids.append(ObjectId(field.id))
            else:
                # Create new field
                new_field = FormFieldInDB(
                    name=field.name,
                    type=field.type,
                    options=field.options,
                    order=field.order,
                    form_id=form_id
                )
                result = await db.db.fields.insert_one(new_field.dict(by_alias=True, exclude={"id"}))
                incoming_field_ids.append(result.inserted_id)

        # Delete any fields that were NOT in the request
        await db.db.fields.delete_many({
            "form_id": form_id,
            "_id": {"$nin": incoming_field_ids}
        })

    return await read_form(form_id=form_id, current_user=current_user)

@router.post("/{form_id}/fields", response_model=FormField)
async def add_field(
    *,
    form_id: str,
    field_in: FormFieldCreate,
    current_user: UserInDB = Depends(get_current_active_user),
) -> Any:
    """
    Add a field to a form.
    """
    form_doc = await db.db.forms.find_one({"_id": ObjectId(form_id)})
    if not form_doc:
        raise HTTPException(status_code=404, detail="Form not found")

    new_field = FormFieldInDB(
        **field_in.dict()
    )
    result = await db.db.fields.insert_one(new_field.dict(by_alias=True, exclude={"id"}))
    created_field = await db.db.fields.find_one({"_id": result.inserted_id})
    return FormField(**created_field)

@router.get("/{form_id}/fields", response_model=List[FormField])
async def read_fields(
    form_id: str,
    current_user: UserInDB = Depends(get_current_active_user),
) -> Any:
    """
    Retrieve fields for a form.
    """
    fields_cursor = db.db.fields.find({"form_id": form_id}).sort("order", 1)
    fields = await fields_cursor.to_list(length=100)
    return [FormField(**field) for field in fields]

@router.delete("/{form_id}")
async def delete_form(
    form_id: str,
    delete_records: bool = True,
    current_user: UserInDB = Depends(get_current_active_user),
) -> Any:
    """
    Delete a form. Optionally delete its submitted records too.
    """
    try:
        oid = ObjectId(form_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Form ID")

    form_doc = await db.db.forms.find_one({"_id": oid})
    if not form_doc:
        raise HTTPException(status_code=404, detail="Form not found")

    # Check permissions
    member = await db.db.members.find_one({
        "workspace_id": form_doc["workspace_id"],
        "user_id": current_user.id
    })
    if not member or member.get("role") in ["Viewer", "Guest"]:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    # Delete form fields
    await db.db.fields.delete_many({"form_id": form_id})

    # Optionally delete records
    if delete_records:
        await db.db.records.delete_many({"form_id": form_id})

    # Delete the form itself
    await db.db.forms.delete_one({"_id": oid})

    return {"msg": "Form deleted successfully"}
