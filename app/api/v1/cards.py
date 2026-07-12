import string
import random
import logging
from datetime import datetime
from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from app.db.mongodb import db
from app.api.deps import get_current_active_user
from app.schemas.user import UserInDB
from app.schemas.card import BusinessCard, BusinessCardCreate, BusinessCardUpdate
from app.api.v1.qrcodes import get_ip_location

logger = logging.getLogger(__name__)
router = APIRouter()

def generate_short_id(length: int = 6) -> str:
    chars = string.ascii_letters + string.digits
    return "".join(random.choice(chars) for _ in range(length))

@router.post("/", response_model=BusinessCard)
async def create_business_card(
    card_in: BusinessCardCreate,
    current_user: UserInDB = Depends(get_current_active_user)
) -> Any:
    # Verify member status in workspace
    member = await db.db.members.find_one({
        "workspace_id": card_in.workspace_id,
        "user_id": current_user.id
    })
    if not member:
        raise HTTPException(status_code=403, detail="Not a member of this workspace")

    # Generate unique short id
    short_id = generate_short_id()
    while await db.db.business_cards.find_one({"short_id": short_id}):
        short_id = generate_short_id()

    new_card = card_in.dict()
    new_card["short_id"] = short_id
    new_card["created_at"] = datetime.utcnow()

    res = await db.db.business_cards.insert_one(new_card)
    created = await db.db.business_cards.find_one({"_id": res.inserted_id})
    if created:
        created["_id"] = str(created["_id"])
    return BusinessCard(**created)

@router.get("/workspace/{workspace_id}/stats")
async def get_workspace_card_stats(
    workspace_id: str,
    current_user: UserInDB = Depends(get_current_active_user)
) -> Any:
    member = await db.db.members.find_one({
        "workspace_id": workspace_id,
        "user_id": current_user.id
    })
    if not member:
        raise HTTPException(status_code=403, detail="Not a member of this workspace")

    cards = await db.db.business_cards.find({"workspace_id": workspace_id}).to_list(length=100)
    card_ids = [str(c["_id"]) for c in cards]

    total_scans = 0
    unique_ips = set()
    top_countries_map = {}

    if card_ids:
        scans_cursor = db.db.card_scans.find({"card_id": {"$in": card_ids}})
        scans = await scans_cursor.to_list(length=5000)
        total_scans = len(scans)
        for s in scans:
            unique_ips.add(f"{s.get('card_id')}-{s.get('ip_address')}")
            country = s.get("country", "Unknown")
            top_countries_map[country] = top_countries_map.get(country, 0) + 1

    top_countries = [{"country": k, "count": v} for k, v in top_countries_map.items()]
    top_countries = sorted(top_countries, key=lambda x: x["count"], reverse=True)[:5]

    for c in cards:
        c["id"] = str(c["_id"])
        c["target_url"] = f"/public/card/{c['id']}"
        scans_count = await db.db.card_scans.count_documents({"card_id": c["id"]})
        c["scans_count"] = scans_count

    return {
        "total_cards": len(cards),
        "total_scans": total_scans,
        "unique_scans": len(unique_ips),
        "top_countries": top_countries,
        "cards": cards
    }

@router.get("/workspace/{workspace_id}", response_model=dict)
async def list_workspace_cards(
    workspace_id: str,
    page: int = 1,
    limit: int = 100,
    current_user: UserInDB = Depends(get_current_active_user)
) -> Any:
    member = await db.db.members.find_one({
        "workspace_id": workspace_id,
        "user_id": current_user.id
    })
    if not member:
        raise HTTPException(status_code=403, detail="Not a member of this workspace")

    cursor = db.db.business_cards.find({"workspace_id": workspace_id})
    total = await db.db.business_cards.count_documents({"workspace_id": workspace_id})
    
    items = await cursor.skip((page - 1) * limit).limit(limit).to_list(length=limit)
    for it in items:
        if "_id" in it:
            it["_id"] = str(it["_id"])

    return {
        "items": [BusinessCard(**it) for it in items],
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit
    }

@router.get("/{id}", response_model=BusinessCard)
async def get_card_details(
    id: str,
    current_user: UserInDB = Depends(get_current_active_user)
) -> Any:
    from bson import ObjectId
    card = await db.db.business_cards.find_one({"_id": ObjectId(id)})
    if not card:
        raise HTTPException(status_code=404, detail="Business card not found")
        
    card["_id"] = str(card["_id"])
    return BusinessCard(**card)

@router.get("/public/{id}")
async def get_public_card(id: str) -> Any:
    # Public route to fetch card details without authentication
    from bson import ObjectId
    try:
        card = await db.db.business_cards.find_one({"_id": ObjectId(id)})
    except Exception:
        raise HTTPException(status_code=404, detail="Invalid card ID format")
    if not card:
        raise HTTPException(status_code=404, detail="Business card not found")
    card["_id"] = str(card["_id"])
    
    # Exclude tracking name for public view if needed, or keep it
    return {
        "id": card["_id"],
        "first_name": card.get("first_name"),
        "last_name": card.get("last_name"),
        "title": card.get("title"),
        "company": card.get("company"),
        "email": card.get("email"),
        "phone": card.get("phone"),
        "website": card.get("website"),
        "address": card.get("address"),
        "avatar_url": card.get("avatar_url"),
        "logo_url": card.get("logo_url"),
        "front_image_url": card.get("front_image_url"),
        "back_image_url": card.get("back_image_url"),
        "social_links": card.get("social_links"),
        "custom_fields": card.get("custom_fields")
    }

@router.put("/{id}", response_model=BusinessCard)
async def update_business_card(
    id: str,
    card_in: BusinessCardUpdate,
    current_user: UserInDB = Depends(get_current_active_user)
) -> Any:
    from bson import ObjectId
    card = await db.db.business_cards.find_one({"_id": ObjectId(id)})
    if not card:
        raise HTTPException(status_code=404, detail="Business card not found")

    # Verify workspace membership
    member = await db.db.members.find_one({
        "workspace_id": card["workspace_id"],
        "user_id": current_user.id
    })
    if not member:
        raise HTTPException(status_code=403, detail="Not authorized to edit cards in this workspace")

    update_data = {k: v for k, v in card_in.dict(exclude_unset=True).items()}
    if "social_links" in update_data and update_data["social_links"]:
        update_data["social_links"] = card_in.social_links.dict()
    if "custom_fields" in update_data and update_data["custom_fields"] is not None:
        update_data["custom_fields"] = [f.dict() for f in card_in.custom_fields]

    await db.db.business_cards.update_one({"_id": ObjectId(id)}, {"$set": update_data})
    
    updated = await db.db.business_cards.find_one({"_id": ObjectId(id)})
    updated["_id"] = str(updated["_id"])
    return BusinessCard(**updated)

@router.delete("/{id}")
async def delete_business_card(
    id: str,
    current_user: UserInDB = Depends(get_current_active_user)
) -> Any:
    from bson import ObjectId
    card = await db.db.business_cards.find_one({"_id": ObjectId(id)})
    if not card:
        raise HTTPException(status_code=404, detail="Business card not found")

    member = await db.db.members.find_one({
        "workspace_id": card["workspace_id"],
        "user_id": current_user.id
    })
    if not member:
        raise HTTPException(status_code=403, detail="Not authorized to delete cards in this workspace")

    await db.db.business_cards.delete_one({"_id": ObjectId(id)})
    await db.db.card_scans.delete_many({"card_id": id})
    return {"status": "ok"}

@router.get("/{id}/analytics")
async def get_card_analytics(
    id: str,
    current_user: UserInDB = Depends(get_current_active_user)
) -> Any:
    from bson import ObjectId
    card = await db.db.business_cards.find_one({"_id": ObjectId(id)})
    if not card:
        raise HTTPException(status_code=404, detail="Business card not found")

    member = await db.db.members.find_one({
        "workspace_id": card["workspace_id"],
        "user_id": current_user.id
    })
    if not member:
        raise HTTPException(status_code=403, detail="Not authorized to view analytics")

    cursor = db.db.card_scans.find({"card_id": id}).sort("created_at", -1)
    scans = await cursor.to_list(length=100)

    total_scans = len(scans)
    unique_ips = set()
    top_countries_map = {}

    for s in scans:
        s["_id"] = str(s["_id"])
        unique_ips.add(s.get("ip_address"))
        country = s.get("country", "Unknown")
        top_countries_map[country] = top_countries_map.get(country, 0) + 1

    top_countries = [{"country": k, "count": v} for k, v in top_countries_map.items()]
    top_countries = sorted(top_countries, key=lambda x: x["count"], reverse=True)[:5]

    return {
        "total_scans": total_scans,
        "unique_scans": len(unique_ips),
        "top_countries": top_countries,
        "scans": scans
    }

@router.get("/vcard/{id}")
async def get_vcard_file(id: str) -> Any:
    from bson import ObjectId
    try:
        card = await db.db.business_cards.find_one({"_id": ObjectId(id)})
    except Exception:
        raise HTTPException(status_code=404, detail="Invalid card ID format")
    if not card:
        raise HTTPException(status_code=404, detail="Business card not found")

    first = card.get("first_name", "")
    last = card.get("last_name", "")
    company = card.get("company", "")
    title = card.get("title", "")
    email = card.get("email", "")
    phone = card.get("phone", "")
    website = card.get("website", "")
    address = card.get("address", "")

    # Construct VCard standard string
    vcard = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"FN:{first} {last}",
        f"N:{last};{first};;;",
        f"ORG:{company}",
        f"TITLE:{title}",
        f"EMAIL;TYPE=PREF,INTERNET:{email}",
        f"TEL;TYPE=CELL,voice:{phone}",
        f"URL:{website}",
        f"ADR;TYPE=WORK:;;{address};;;;",
        "END:VCARD"
    ]
    vcard_str = "\n".join(vcard)

    return Response(
        content=vcard_str,
        media_type="text/vcard",
        headers={
            "Content-Disposition": f"attachment; filename={first}_{last}.vcf"
        }
    )

@router.get("/r/{short_id}")
async def redirect_card(short_id: str, request: Request):
    """
    Redirects scanner to the public digital business card page and logs scan telemetry.
    """
    card = await db.db.business_cards.find_one({"short_id": short_id})
    if not card:
        raise HTTPException(status_code=404, detail="Digital business card not found")

    client_ip = request.headers.get("x-forwarded-for")
    if client_ip:
        client_ip = client_ip.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else "127.0.0.1"

    user_agent = request.headers.get("user-agent", "Unknown")
    loc_info = await get_ip_location(client_ip)

    scan_event = {
        "card_id": str(card["_id"]),
        "ip_address": client_ip,
        "country": loc_info["country"],
        "country_code": loc_info["countryCode"],
        "region": loc_info["regionName"],
        "city": loc_info["city"],
        "user_agent": user_agent,
        "created_at": datetime.utcnow()
    }
    await db.db.card_scans.insert_one(scan_event)

    # Redirect to public frontend card page
    public_url = f"{settings.API_V1_STR.replace('/api/v1', '')}/public/card/{str(card['_id'])}"
    # Wait, we need to redirect to the frontend URL! 
    # Usually frontend runs on localhost:5173 or same host. Let's find origin of request or default to setting
    # We can redirect to relative path if backend/frontend are served on same domain, 
    # or redirect based on the referer/origin headers or default to localhost:5173 for local dev!
    host = request.headers.get("host", "localhost:5173")
    if "8000" in host:
        # Request is going to backend, redirect to frontend port 5173!
        redirect_target = f"http://{host.replace('8000', '5173')}/public/card/{str(card['_id'])}"
    else:
        redirect_target = f"/public/card/{str(card['_id'])}"

    return RedirectResponse(url=redirect_target)
