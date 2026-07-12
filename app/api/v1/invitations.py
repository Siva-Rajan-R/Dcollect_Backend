"""
Invitations API
--------------
Handles secure email-based workspace invitations with per-service permissions.
Token lifetime: 3 days. Statuses: pending / accepted / expired.
"""
import secrets
import datetime
from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse

from app.api.deps import get_current_active_user
from app.schemas.user import UserInDB
from app.schemas.invitation import InvitationCreate, InvitationInDB, InvitationStatus, ServicePermissions
from app.schemas.member import MemberInDB, Role
from app.db.mongodb import db
from app.core.config import settings
from app.core.email import send_invitation_email
from bson import ObjectId

router = APIRouter()

INVITATION_EXPIRY_DAYS = 3


def _now() -> datetime.datetime:
    return datetime.datetime.utcnow()


def _default_permissions_for_role(role: str) -> dict:
    """Return a sensible default service permissions dict for a given role."""
    if role in ("Owner", "Admin", "Editor"):
        return {k: "write" for k in ["forms", "qrcodes", "cards", "tasks", "documents", "assets"]}
    if role == "Contributor":
        return {k: "write" for k in ["forms", "qrcodes", "cards", "tasks", "documents", "assets"]}
    # Viewer / Guest → read only
    return {k: "read" for k in ["forms", "qrcodes", "cards", "tasks", "documents", "assets"]}


async def _mark_expired_invitations(workspace_id: str):
    """Mark past-expiry invitations as expired in DB."""
    await db.db.invitations.update_many(
        {
            "workspace_id": workspace_id,
            "status": InvitationStatus.PENDING,
            "expires_at": {"$lt": _now()},
        },
        {"$set": {"status": InvitationStatus.EXPIRED}},
    )


# ---------------------------------------------------------------------------
# POST /invitations/workspace/{workspace_id}
# ---------------------------------------------------------------------------
@router.post("/workspace/{workspace_id}")
async def create_invitation(
    workspace_id: str,
    payload: InvitationCreate,
    current_user: UserInDB = Depends(get_current_active_user),
) -> Any:
    """
    Invite a collaborator by email with per-service permissions.
    Always creates an invitation link regardless of whether the email is registered.
    The user must click the accept link — only then are they added to the workspace.
    """
    # Only owners may invite
    member_check = await db.db.members.find_one({"workspace_id": workspace_id, "user_id": current_user.id})
    if not member_check or member_check["role"] != "Owner":
        raise HTTPException(status_code=403, detail="Only Owners can invite members")

    workspace = await db.db.workspaces.find_one({"_id": ObjectId(workspace_id)})
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    email = payload.email.lower().strip()
    service_perms = payload.service_permissions.to_dict()

    # Check if user is already an active member
    existing_user = await db.db.users.find_one({"email": email})
    if existing_user:
        existing_user_id = str(existing_user["_id"])
        already_member = await db.db.members.find_one({"workspace_id": workspace_id, "user_id": existing_user_id})
        if already_member:
            raise HTTPException(status_code=400, detail="This user is already a member of this workspace.")

    # Check for an existing pending invitation for this email in this workspace
    existing_inv = await db.db.invitations.find_one({
        "workspace_id": workspace_id,
        "email": email,
        "status": InvitationStatus.PENDING,
    })
    if existing_inv:
        raise HTTPException(
            status_code=400,
            detail="A pending invitation already exists for this email. Resend or cancel it first."
        )

    token = secrets.token_urlsafe(32)
    expires_at = _now() + datetime.timedelta(days=INVITATION_EXPIRY_DAYS)

    inv_doc = {
        "workspace_id": workspace_id,
        "email": email,
        "invited_by": current_user.id,
        "token": token,
        "service_permissions": service_perms,
        "status": InvitationStatus.PENDING,
        "expires_at": expires_at,
        "created_at": _now(),
        "accepted_at": None,
        "email_sent": False,
    }
    result = await db.db.invitations.insert_one(inv_doc)

    accept_url = f"{settings.FRONTEND_URL}/invite/accept/{token}"

    # Resolve inviter name
    inviter_name = (
        current_user.full_name
        or current_user.email.split("@")[0]
        if hasattr(current_user, "full_name") and current_user.full_name
        else current_user.email.split("@")[0]
    )
    workspace_name = workspace.get("name", "DCollect Workspace")

    email_sent = await send_invitation_email(
        to_email=email,
        inviter_name=inviter_name,
        workspace_name=workspace_name,
        accept_url=accept_url,
        service_permissions=service_perms,
    )

    # Update email_sent flag
    await db.db.invitations.update_one(
        {"_id": result.inserted_id},
        {"$set": {"email_sent": email_sent}}
    )

    return {
        "status": "invited",
        "message": "Invitation created. Email sent." if email_sent else "Invitation created. Email not sent (SMTP not configured) — use the accept_url below.",
        "type": "invitation",
        "accept_url": accept_url,  # useful for testing when SMTP is off
        "invitation_id": str(result.inserted_id),
    }


# ---------------------------------------------------------------------------
# GET /invitations/workspace/{workspace_id}
# ---------------------------------------------------------------------------
@router.get("/workspace/{workspace_id}")
async def list_invitations(
    workspace_id: str,
    current_user: UserInDB = Depends(get_current_active_user),
) -> Any:
    """List all invitations for a workspace (auto-expire stale ones)."""
    member_check = await db.db.members.find_one({"workspace_id": workspace_id, "user_id": current_user.id})
    if not member_check:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    await _mark_expired_invitations(workspace_id)

    cursor = db.db.invitations.find({"workspace_id": workspace_id}).sort("created_at", -1)
    invitations = await cursor.to_list(length=200)

    result = []
    for inv in invitations:
        inviter_name = "Unknown"
        try:
            inviter_doc = await db.db.users.find_one({"_id": ObjectId(inv["invited_by"])})
            if inviter_doc:
                inviter_name = inviter_doc.get("full_name") or inviter_doc.get("email", "").split("@")[0]
        except Exception:
            pass

        # Check if the invitee already has an account
        invitee_registered = bool(await db.db.users.find_one({"email": inv["email"]}))

        result.append({
            "id": str(inv["_id"]),
            "email": inv["email"],
            "status": inv["status"],
            "service_permissions": inv.get("service_permissions", {}),
            "invited_by_name": inviter_name,
            "created_at": inv["created_at"].isoformat(),
            "expires_at": inv["expires_at"].isoformat(),
            "accepted_at": inv["accepted_at"].isoformat() if inv.get("accepted_at") else None,
            "email_sent": inv.get("email_sent", False),
            "is_registered": invitee_registered,
        })

    return result


# ---------------------------------------------------------------------------
# GET /invitations/accept/{token}  (public — no auth required)
# ---------------------------------------------------------------------------
@router.get("/accept/{token}")
async def accept_invitation(token: str) -> Any:
    """
    Accept a workspace invitation via token.
    Called when the invited user clicks the link in their email.
    Returns redirect to frontend login with a context param, or JSON for API clients.
    """
    inv = await db.db.invitations.find_one({"token": token})
    if not inv:
        raise HTTPException(status_code=404, detail="Invalid or already-used invitation link.")

    if inv["status"] == InvitationStatus.ACCEPTED:
        # Already accepted — redirect to login
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/login?invite=already_accepted")

    if inv["status"] == InvitationStatus.EXPIRED or inv["expires_at"] < _now():
        await db.db.invitations.update_one({"_id": inv["_id"]}, {"$set": {"status": InvitationStatus.EXPIRED}})
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/login?invite=expired&email={inv['email']}")

    # Check if user already has an account with this email
    user_doc = await db.db.users.find_one({"email": inv["email"]})

    if user_doc:
        # User exists → add as member immediately
        user_id = str(user_doc["_id"])
        already_member = await db.db.members.find_one({"workspace_id": inv["workspace_id"], "user_id": user_id})
        if not already_member:
            await db.db.members.insert_one({
                "user_id": user_id,
                "workspace_id": inv["workspace_id"],
                "role": Role.VIEWER,
                "service_permissions": inv.get("service_permissions", {}),
                "joined_at": _now(),
            })

        # Mark invitation accepted
        await db.db.invitations.update_one(
            {"_id": inv["_id"]},
            {"$set": {"status": InvitationStatus.ACCEPTED, "accepted_at": _now(), "token": ""}},
        )
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/login?invite=accepted&workspace={inv['workspace_id']}")

    # User does not exist → redirect to register page with prefilled email
    # Invalidate token after click so they must register first, then owner re-invites
    # OR: store a "pre-accept" marker and let them register → we auto-accept on registration
    # Simple approach: redirect to register with context, mark invitation as "click_pending"
    return RedirectResponse(
        url=f"{settings.FRONTEND_URL}/login?invite=register&email={inv['email']}&token={token}"
    )


# ---------------------------------------------------------------------------
# POST /invitations/{invitation_id}/resend
# ---------------------------------------------------------------------------
@router.post("/{invitation_id}/resend")
async def resend_invitation(
    invitation_id: str,
    current_user: UserInDB = Depends(get_current_active_user),
) -> Any:
    """Resend an invitation: generates a new token and resets the 3-day expiry."""
    inv = await db.db.invitations.find_one({"_id": ObjectId(invitation_id)})
    if not inv:
        raise HTTPException(status_code=404, detail="Invitation not found")

    member_check = await db.db.members.find_one({"workspace_id": inv["workspace_id"], "user_id": current_user.id})
    if not member_check or member_check["role"] != "Owner":
        raise HTTPException(status_code=403, detail="Only Owners can resend invitations")

    if inv["status"] == InvitationStatus.ACCEPTED:
        raise HTTPException(status_code=400, detail="Invitation already accepted")

    new_token = secrets.token_urlsafe(32)
    new_expiry = _now() + datetime.timedelta(days=INVITATION_EXPIRY_DAYS)

    await db.db.invitations.update_one(
        {"_id": inv["_id"]},
        {"$set": {
            "token": new_token,
            "expires_at": new_expiry,
            "status": InvitationStatus.PENDING,
            "email_sent": False,
        }},
    )

    accept_url = f"{settings.FRONTEND_URL}/invite/accept/{new_token}"

    workspace = await db.db.workspaces.find_one({"_id": ObjectId(inv["workspace_id"])})
    workspace_name = workspace.get("name", "DCollect Workspace") if workspace else "DCollect Workspace"
    inviter_name = (
        current_user.full_name
        if hasattr(current_user, "full_name") and current_user.full_name
        else current_user.email.split("@")[0]
    )

    email_sent = await send_invitation_email(
        to_email=inv["email"],
        inviter_name=inviter_name,
        workspace_name=workspace_name,
        accept_url=accept_url,
        service_permissions=inv.get("service_permissions", {}),
    )

    await db.db.invitations.update_one(
        {"_id": inv["_id"]},
        {"$set": {"email_sent": email_sent}}
    )

    return {
        "status": "resent",
        "message": "Invitation resent." if email_sent else "Invitation updated. SMTP not configured — use accept_url below.",
        "accept_url": accept_url,
    }


# ---------------------------------------------------------------------------
# DELETE /invitations/{invitation_id}
# ---------------------------------------------------------------------------
@router.delete("/{invitation_id}")
async def cancel_invitation(
    invitation_id: str,
    current_user: UserInDB = Depends(get_current_active_user),
) -> Any:
    """Cancel and delete an invitation."""
    inv = await db.db.invitations.find_one({"_id": ObjectId(invitation_id)})
    if not inv:
        raise HTTPException(status_code=404, detail="Invitation not found")

    member_check = await db.db.members.find_one({"workspace_id": inv["workspace_id"], "user_id": current_user.id})
    if not member_check or member_check["role"] != "Owner":
        raise HTTPException(status_code=403, detail="Only Owners can cancel invitations")

    await db.db.invitations.delete_one({"_id": inv["_id"]})
    return {"status": "cancelled", "message": "Invitation cancelled and deleted."}
