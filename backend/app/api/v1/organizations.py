import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_db, get_optional_user
from app.models.organization import Organization
from app.models.user import User, UserRole

router = APIRouter(prefix="/organizations", tags=["organizations"])


class OrganizationCreate(BaseModel):
    name: str
    industry: str | None = None


class OrganizationOut(BaseModel):
    id: uuid.UUID
    name: str
    industry: str | None

    class Config:
        from_attributes = True


@router.post("", response_model=OrganizationOut, status_code=201)
def create_organization(
    payload: OrganizationCreate,
    db: Session = Depends(get_db),
    caller: User | None = Depends(get_optional_user),
) -> Organization:
    if not settings.ALLOW_OPEN_REGISTRATION and (caller is None or caller.role != UserRole.admin):
        raise HTTPException(
            status_code=403,
            detail="Open registration is disabled — organizations are provisioned out of band",
        )
    org = Organization(name=payload.name, industry=payload.industry)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org
