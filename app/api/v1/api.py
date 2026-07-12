from fastapi import APIRouter
from app.api.v1 import auth, workspaces, forms, records, storage, qrcodes, cards, documents, tasks, invitations

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(workspaces.router, prefix="/workspaces", tags=["workspaces"])
api_router.include_router(forms.router, prefix="/forms", tags=["forms"])
api_router.include_router(records.router, prefix="/records", tags=["records"])
api_router.include_router(storage.router, prefix="/storage", tags=["storage"])
api_router.include_router(qrcodes.router, prefix="/qrcodes", tags=["qrcodes"])
api_router.include_router(cards.router, prefix="/cards", tags=["cards"])
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(invitations.router, prefix="/invitations", tags=["invitations"])
