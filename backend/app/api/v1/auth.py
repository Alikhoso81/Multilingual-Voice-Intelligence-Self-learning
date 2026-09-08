import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_db, get_optional_user
from app.core.security import create_token, decode_token, hash_password, verify_password
from app.models.organization import Organization
from app.models.user import User, UserRole
from app.schemas.auth import Token, UserCreate, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(
    payload: UserCreate,
    db: Session = Depends(get_db),
    caller: User | None = Depends(get_optional_user),
) -> User:
    if not settings.ALLOW_OPEN_REGISTRATION:
        if caller is None or caller.role != UserRole.admin or caller.organization_id != payload.organization_id:
            raise HTTPException(
                status_code=403,
                detail="Open registration is disabled — an org admin must create this user",
            )

    org = db.query(Organization).filter(Organization.id == payload.organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        organization_id=payload.organization_id,
        full_name=payload.full_name,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> Token:
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User is inactive")
    return _tokens_for(user)


@router.post("/refresh", response_model=Token)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> Token:
    claims = decode_token(payload.refresh_token)
    if claims is None or claims.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    try:
        user_id = uuid.UUID(claims.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    return _tokens_for(user)


def _tokens_for(user: User) -> Token:
    return Token(
        access_token=create_token(str(user.id), user.role.value, str(user.organization_id), "access"),
        refresh_token=create_token(str(user.id), user.role.value, str(user.organization_id), "refresh"),
    )
