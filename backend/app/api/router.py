"""Assembles the API."""

from fastapi import APIRouter, Depends

from app.api.deps import require_admin
from app.api.errors import error_responses
from app.api.routes import admin_documents, admin_inquiries, conversations, health, inquiries

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(conversations.router)
api_router.include_router(inquiries.router)

admin_router = APIRouter(
    prefix="/admin",
    dependencies=[Depends(require_admin)],
    responses=error_responses(401, 403),
)
admin_router.include_router(admin_documents.router)
admin_router.include_router(admin_inquiries.router)
api_router.include_router(admin_router)
