import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.models.organization import Organization

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
def create_organization(payload: OrganizationCreate, db: Session = Depends(get_db)) -> Organization:
    org = Organization(name=payload.name, industry=payload.industry)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org
