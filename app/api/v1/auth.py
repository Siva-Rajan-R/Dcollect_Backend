from datetime import timedelta
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from app.core.config import settings
from app.core.security import create_access_token, get_password_hash, verify_password
from app.schemas.token import Token
from app.schemas.user import UserCreate, User, UserInDB
from app.db.mongodb import db
from app.api.deps import get_current_active_user

router = APIRouter()

from app.core.redis import redis_client
from app.utils.email import send_otp_email
from app.schemas.user import OTPRequest, OTPVerify
import random

@router.post("/request-otp")
async def request_otp(otp_in: OTPRequest) -> Any:
    """
    Request a 6-digit OTP for passwordless login.
    """
    # For development/testing, we use a fixed OTP if the email contains "test"
    # Otherwise, generate a random one.
    if "test" in otp_in.email.lower() or otp_in.email == "siva967763@gmail.com":
        otp_code = "123456"
    else:
        otp_code = f"{random.randint(100000, 999999)}"
    
    # Store in Redis with 5 min expiration
    await redis_client.redis.setex(f"otp:{otp_in.email}", 300, otp_code)
    
    print(f"\n{'='*40}")
    print(f"DEVELOPMENT OTP FOR {otp_in.email}: {otp_code}")
    print(f"{'='*40}\n")
    
    # Mock send email
    send_otp_email(otp_in.email, otp_code)
    
    return {"msg": "OTP sent to your email (check backend terminal)"}

@router.post("/verify-otp", response_model=Token)
async def verify_otp(otp_in: OTPVerify) -> Any:
    """
    Verify OTP and return access token. If user doesn't exist, create one.
    """
    stored_otp = await redis_client.redis.get(f"otp:{otp_in.email}")
    if not stored_otp or stored_otp != otp_in.otp:
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")
    
    # Delete OTP after successful use
    await redis_client.redis.delete(f"otp:{otp_in.email}")

    user_doc = await db.db.users.find_one({"email": otp_in.email})
    if not user_doc:
        # Create new user on the fly
        new_user = UserInDB(email=otp_in.email)
        result = await db.db.users.insert_one(new_user.dict(by_alias=True, exclude={"id"}))
        user_doc = await db.db.users.find_one({"_id": result.inserted_id})
    
    # Ensure user has at least one workspace
    user_id_str = str(user_doc["_id"])
    member_ws = await db.db.members.find_one({"user_id": user_id_str})
    if not member_ws:
        from datetime import datetime
        from app.schemas.member import Role
        # Create default workspace
        ws_insert = await db.db.workspaces.insert_one({
            "name": "My Workspace",
            "logo_url": None,
            "settings": {},
            "owner_id": user_id_str,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        })
        # Add owner as a member
        await db.db.members.insert_one({
            "user_id": user_id_str,
            "workspace_id": str(ws_insert.inserted_id),
            "role": Role.OWNER
        })
    
    if "_id" in user_doc:
        user_doc["_id"] = str(user_doc["_id"])
    user = UserInDB(**user_doc)
    
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return {
        "access_token": create_access_token(
            user.id, expires_delta=access_token_expires
        ),
        "token_type": "bearer",
    }

@router.post("/me", response_model=User)
async def read_current_user(
    current_user: UserInDB = Depends(get_current_active_user),
) -> Any:
    """
    Get current user.
    """
    return User(**current_user.dict(by_alias=True))
