import uuid
from typing import Generator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decode_token
from app.db.session import SessionLocal
from app.models.user import User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decode_token(token)
    if payload is None or payload.get("type") != "access":
        raise credentials_exception

    try:
        user_id = uuid.UUID(payload.get("sub"))
    except (TypeError, ValueError):
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        raise credentials_exception
    return user


def get_optional_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User | None:
    """Current user if a valid access token is present, else None. Used by
    endpoints that are open in dev but gated in production."""
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    payload = decode_token(header[7:])
    if payload is None or payload.get("type") != "access":
        return None
    try:
        user_id = uuid.UUID(payload.get("sub"))
    except (TypeError, ValueError):
        return None
    user = db.query(User).filter(User.id == user_id).first()
    return user if user and user.is_active else None


def enforce_upload_limit(request: Request) -> None:
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit():
        if int(content_length) > settings.MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Upload exceeds the {settings.MAX_UPLOAD_MB} MB limit",
            )


def require_roles(*allowed_roles: UserRole):
    """
    Usage: Depends(require_roles(UserRole.admin))
    Enforces RBAC at the API-dependency level, not just in the UI.
    """

    def checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return current_user

    return checker
