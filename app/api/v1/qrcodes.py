import math
import secrets
import logging
from datetime import datetime
from typing import Any, List, Optional
import httpx

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import RedirectResponse

from app.db.mongodb import db
from app.api.deps import get_current_active_user
from app.schemas.user import UserInDB
from app.schemas.qrcode import QRCode, QRCodeCreate, QRCodeUpdate

router = APIRouter()
logger = logging.getLogger(__name__)

async def get_ip_location(ip: str) -> dict:
    if ip in ("127.0.0.1", "localhost", "::1") or ip.startswith("192.168.") or ip.startswith("10.") or ip.startswith("172.16."):
        # Generate some mock location data for local testing so they get countries representation
        mock_countries = ["United States", "India", "Germany", "United Kingdom", "Canada"]
        mock_codes = ["US", "IN", "DE", "GB", "CA"]
        idx = hash(ip) % len(mock_countries)
        return {
            "country": mock_countries[idx],
            "countryCode": mock_codes[idx],
            "regionName": "Local Region",
            "city": "Local City"
        }
    
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(f"http://ip-api.com/json/{ip}", timeout=2.0)
            if res.status_code == 200:
                data = res.json()
                if data.get("status") == "success":
                    return {
                        "country": data.get("country", "Unknown"),
                        "countryCode": data.get("countryCode", "UN"),
                        "regionName": data.get("regionName", "Unknown"),
                        "city": data.get("city", "Unknown")
                    }
    except Exception as e:
        logger.error(f"Error fetching IP location: {e}")
        
    return {"country": "Unknown", "countryCode": "UN", "regionName": "Unknown", "city": "Unknown"}


@router.get("/r/{short_id}")
async def redirect_qr(short_id: str, request: Request):
    """
    Redirects short URL to target URL and logs scan telemetry.
    """
    qr_code = await db.db.qrcodes.find_one({"short_id": short_id})
    if not qr_code:
        raise HTTPException(status_code=404, detail="QR Code not found")
    
    # Resolve Scanner Client IP address
    client_ip = request.headers.get("x-forwarded-for")
    if client_ip:
        client_ip = client_ip.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else "127.0.0.1"
    
    # Resolve scanner details
    user_agent = request.headers.get("user-agent", "Unknown")
    loc_info = await get_ip_location(client_ip)
    
    # Log scan event
    scan_event = {
        "qr_code_id": str(qr_code["_id"]),
        "ip_address": client_ip,
        "country": loc_info["country"],
        "country_code": loc_info["countryCode"],
        "region": loc_info["regionName"],
        "city": loc_info["city"],
        "user_agent": user_agent,
        "created_at": datetime.utcnow()
    }
    await db.db.qr_scans.insert_one(scan_event)
    
    # Redirect to final destination
    return RedirectResponse(url=qr_code["target_url"])


@router.post("/", response_model=QRCode)
async def create_qrcode(
    qrcode_in: QRCodeCreate,
    current_user: UserInDB = Depends(get_current_active_user)
) -> Any:
    # Check permissions in workspace
    member = await db.db.members.find_one({
        "workspace_id": qrcode_in.workspace_id,
        "user_id": current_user.id
    })
    if not member:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    # Generate unique short ID
    attempts = 0
    short_id = ""
    while attempts < 10:
        candidate = secrets.token_urlsafe(5).replace("-", "").replace("_", "")[:6]
        exists = await db.db.qrcodes.find_one({"short_id": candidate})
        if not exists:
            short_id = candidate
            break
        attempts += 1
    
    if not short_id:
         raise HTTPException(status_code=500, detail="Failed to generate unique short link")
         
    qr_data = qrcode_in.model_dump()
    qr_data["short_id"] = short_id
    qr_data["creator_id"] = current_user.id
    qr_data["created_at"] = datetime.utcnow()
    
    result = await db.db.qrcodes.insert_one(qr_data)
    qr_data["_id"] = str(result.inserted_id)
    
    return QRCode(**qr_data)


@router.get("/workspace/{workspace_id}")
async def list_workspace_qrcodes(
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
        raise HTTPException(status_code=403, detail="Not enough permissions")
        
    total = await db.db.qrcodes.count_documents({"workspace_id": workspace_id})
    skip = (page - 1) * limit
    cursor = db.db.qrcodes.find({"workspace_id": workspace_id}).skip(skip).limit(limit)
    items_in_db = await cursor.to_list(length=limit)
    
    items = []
    for item in items_in_db:
        item["_id"] = str(item["_id"])
        items.append(QRCode(**item))
        
    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": math.ceil(total / limit) if total > 0 else 1
    }


@router.get("/{id}", response_model=QRCode)
async def get_qrcode(
    id: str,
    current_user: UserInDB = Depends(get_current_active_user)
) -> Any:
    qr_code = await db.db.qrcodes.find_one({"_id": id})
    if not qr_code:
        # Fallback if stored as ObjectId
        from bson import ObjectId
        try:
            qr_code = await db.db.qrcodes.find_one({"_id": ObjectId(id)})
        except:
            pass
            
    if not qr_code:
        raise HTTPException(status_code=404, detail="QR Code not found")
        
    # Check permissions
    member = await db.db.members.find_one({
        "workspace_id": qr_code["workspace_id"],
        "user_id": current_user.id
    })
    if not member:
        raise HTTPException(status_code=403, detail="Not enough permissions")
        
    qr_code["_id"] = str(qr_code["_id"])
    return QRCode(**qr_code)


@router.put("/{id}", response_model=QRCode)
async def update_qrcode(
    id: str,
    qrcode_in: QRCodeUpdate,
    current_user: UserInDB = Depends(get_current_active_user)
) -> Any:
    # Fetch QR
    from bson import ObjectId
    query = {"_id": id}
    qr_code = await db.db.qrcodes.find_one(query)
    if not qr_code:
        try:
            query = {"_id": ObjectId(id)}
            qr_code = await db.db.qrcodes.find_one(query)
        except:
            pass
            
    if not qr_code:
        raise HTTPException(status_code=404, detail="QR Code not found")
        
    # Check write access (Editor or Owner)
    member = await db.db.members.find_one({
        "workspace_id": qr_code["workspace_id"],
        "user_id": current_user.id
    })
    if not member or member.get("role") in ("Viewer", "Guest"):
        raise HTTPException(status_code=403, detail="Not enough write permissions")
        
    update_data = {k: v for k, v in qrcode_in.model_dump(exclude_unset=True).items() if v is not None}
    
    # Merge branding settings
    if "branding" in update_data:
        branding_data = qr_code.get("branding") or {}
        branding_data.update(update_data["branding"])
        update_data["branding"] = branding_data

    if update_data:
        await db.db.qrcodes.update_one(query, {"$set": update_data})
        
    updated = await db.db.qrcodes.find_one(query)
    updated["_id"] = str(updated["_id"])
    return QRCode(**updated)


@router.delete("/{id}")
async def delete_qrcode(
    id: str,
    current_user: UserInDB = Depends(get_current_active_user)
) -> Any:
    from bson import ObjectId
    query = {"_id": id}
    qr_code = await db.db.qrcodes.find_one(query)
    if not qr_code:
        try:
            query = {"_id": ObjectId(id)}
            qr_code = await db.db.qrcodes.find_one(query)
        except:
            pass
            
    if not qr_code:
        raise HTTPException(status_code=404, detail="QR Code not found")
        
    # Check permissions
    member = await db.db.members.find_one({
        "workspace_id": qr_code["workspace_id"],
        "user_id": current_user.id
    })
    if not member or member.get("role") in ("Viewer", "Guest"):
        raise HTTPException(status_code=403, detail="Not enough write permissions")
        
    # Delete scans
    await db.db.qr_scans.delete_many({"qr_code_id": str(qr_code["_id"])})
    # Delete QR code
    await db.db.qrcodes.delete_one(query)
    
    return {"status": "success"}


@router.get("/{id}/analytics")
async def get_qrcode_analytics(
    id: str,
    current_user: UserInDB = Depends(get_current_active_user)
) -> Any:
    # Fetch QR
    from bson import ObjectId
    qr_code = await db.db.qrcodes.find_one({"_id": id})
    if not qr_code:
        try:
            qr_code = await db.db.qrcodes.find_one({"_id": ObjectId(id)})
        except:
            pass
    if not qr_code:
        raise HTTPException(status_code=404, detail="QR Code not found")
        
    qr_id = str(qr_code["_id"])
    
    # Fetch scans
    scans_cursor = db.db.qr_scans.find({"qr_code_id": qr_id}).sort("created_at", -1)
    scans = await scans_cursor.to_list(length=1000)
    
    # Process scan statistics
    total_scans = len(scans)
    unique_ips = set()
    unique_scans = 0
    
    countries_map = {}
    scans_list = []
    
    for scan in scans:
        ip = scan["ip_address"]
        if ip not in unique_ips:
            unique_ips.add(ip)
            unique_scans += 1
            
        c_name = scan.get("country", "Unknown")
        countries_map[c_name] = countries_map.get(c_name, 0) + 1
        
        scans_list.append({
            "ip_address": ip,
            "country": c_name,
            "country_code": scan.get("country_code", "UN"),
            "region": scan.get("region", "Unknown"),
            "city": scan.get("city", "Unknown"),
            "user_agent": scan.get("user_agent", "Unknown"),
            "created_at": scan["created_at"].isoformat()
        })
        
    # Top countries list format
    top_countries = [{"country": k, "count": v} for k, v in countries_map.items()]
    top_countries.sort(key=lambda x: x["count"], reverse=True)
    
    return {
        "total_scans": total_scans,
        "unique_scans": unique_scans,
        "top_countries": top_countries,
        "scans": scans_list[:100]  # Return last 100 scans for UI logs
    }


@router.get("/workspace/{workspace_id}/stats")
async def get_workspace_qr_stats(
    workspace_id: str,
    current_user: UserInDB = Depends(get_current_active_user)
) -> Any:
    # Check permissions
    member = await db.db.members.find_one({
        "workspace_id": workspace_id,
        "user_id": current_user.id
    })
    if not member:
        raise HTTPException(status_code=403, detail="Not enough permissions")
        
    # Fetch all QR codes in workspace
    qr_cursor = db.db.qrcodes.find({"workspace_id": workspace_id})
    qrs = await qr_cursor.to_list(length=1000)
    
    total_qrs = len(qrs)
    qr_ids = [str(q["_id"]) for q in qrs]
    
    # Fetch all scans matching these QR codes
    scans_cursor = db.db.qr_scans.find({"qr_code_id": {"$in": qr_ids}})
    scans = await scans_cursor.to_list(length=10000)
    
    total_scans = len(scans)
    
    # Calculate unique scans (per QR Code per IP)
    qr_ip_pairs = set()
    unique_scans = 0
    countries_map = {}
    
    for s in scans:
        pair = (s["qr_code_id"], s["ip_address"])
        if pair not in qr_ip_pairs:
            qr_ip_pairs.add(pair)
            unique_scans += 1
        
        c = s.get("country", "Unknown")
        countries_map[c] = countries_map.get(c, 0) + 1
        
    top_countries = [{"country": k, "count": v} for k, v in countries_map.items()]
    top_countries.sort(key=lambda x: x["count"], reverse=True)
    
    # Scan counts per QR Code
    qr_stats = []
    for q in qrs:
        qid = str(q["_id"])
        q_scans = [s for s in scans if s["qr_code_id"] == qid]
        qr_stats.append({
            "id": qid,
            "name": q["name"],
            "target_url": q["target_url"],
            "short_id": q["short_id"],
            "scans_count": len(q_scans)
        })
    qr_stats.sort(key=lambda x: x["scans_count"], reverse=True)
    
    return {
        "total_qrcodes": total_qrs,
        "total_scans": total_scans,
        "unique_scans": unique_scans,
        "top_countries": top_countries[:5],
        "qrcodes": qr_stats
    }
