import os
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile

from src.auth.constants import (
    ALLOWED_MIME_TYPES,
    MAX_FILE_SIZE_BYTES,
    REFRESH_COOKIE_MAX_AGE,
    REFRESH_COOKIE_NAME,
    REFRESH_COOKIE_PATH,
)
from src.auth.jwt_utils import create_access_token, create_refresh_token, hash_token
from src.auth.passwords import verify_password
from src.auth.refresh_token_store import (
    get_refresh_token,
    is_token_valid,
    revoke_all_user_tokens,
    revoke_refresh_token,
    save_refresh_token,
)
from src.auth.schemas import LoginRequest, ProfileUpdateRequest, RegisterRequest
from src.config import settings
from src.dependencies import get_current_user, get_current_user_id
from src.store import (
    create_user,
    delete_user_data,
    get_password_hash,
    get_user_by_email,
    get_user_by_id,
    update_password_hash,
    update_user_profile,
)


router = APIRouter(prefix="/api/auth", tags=["Auth"])
AVATAR_DIR = Path(settings.sqlite_path).parent / "avatars"


def _set_refresh_cookie(response: Response, raw_token: str) -> None:
    is_prod = settings.environment == "production"
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=raw_token,
        httponly=True,
        secure=is_prod,
        samesite="none" if is_prod else "lax",
        max_age=REFRESH_COOKIE_MAX_AGE,
        path=REFRESH_COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    is_prod = settings.environment == "production"
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        secure=is_prod,
        samesite="none" if is_prod else "lax",
    )


def _issue_session(response: Response, user: dict) -> dict:
    access_token = create_access_token(user["id"], user["email"])
    raw_refresh = create_refresh_token()
    save_refresh_token(user["id"], hash_token(raw_refresh), email=user["email"])
    _set_refresh_cookie(response, raw_refresh)
    return {"access_token": access_token, "token_type": "bearer", "user": user}


@router.post("/register")
async def register(body: RegisterRequest, response: Response):
    email = body.email.strip().lower()
    if "@" not in email:
        raise HTTPException(400, "Enter a valid email address")
    if get_user_by_email(email):
        raise HTTPException(409, "An account with this email already exists")
    user = create_user(body.name.strip(), email, body.password)
    return _issue_session(response, user)


@router.post("/login")
async def login(body: LoginRequest, response: Response):
    user = get_user_by_email(body.email.strip().lower())
    if not user or not verify_password(body.password, get_password_hash(user["id"])):
        raise HTTPException(401, "Invalid email or password")
    return _issue_session(response, user)


@router.post("/refresh")
async def refresh_session(request: Request, response: Response):
    raw = request.cookies.get(REFRESH_COOKIE_NAME)
    if not raw:
        raise HTTPException(401, "No refresh token cookie found")
    old_hash = hash_token(raw)
    row = get_refresh_token(old_hash)
    if not row or not is_token_valid(row):
        _clear_refresh_cookie(response)
        raise HTTPException(401, "Refresh token is invalid, expired, or revoked")

    user = get_user_by_id(str(row["user_id"]))
    if not user:
        _clear_refresh_cookie(response)
        raise HTTPException(401, "Account no longer exists")

    revoke_refresh_token(old_hash)
    new_raw = create_refresh_token()
    save_refresh_token(user["id"], hash_token(new_raw), email=user["email"])
    _set_refresh_cookie(response, new_raw)
    return {"access_token": create_access_token(user["id"], user["email"]), "token_type": "bearer"}


@router.post("/logout")
async def logout(request: Request, response: Response):
    raw = request.cookies.get(REFRESH_COOKIE_NAME)
    if raw:
        revoke_refresh_token(hash_token(raw))
    _clear_refresh_cookie(response)
    return {"status": "ok", "message": "Logged out successfully"}


@router.get("/me")
@router.get("/profile")
async def get_profile(user_id: str = Depends(get_current_user_id)):
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(404, "Profile not found")
    return {"status": "success", "user": user}


@router.patch("/profile")
async def update_profile(body: ProfileUpdateRequest, user_id: str = Depends(get_current_user_id)):
    if body.password is not None:
        if not body.current_password:
            raise HTTPException(400, "Current password is required")
        if not verify_password(body.current_password, get_password_hash(user_id)):
            raise HTTPException(400, "Current password is incorrect")
        update_password_hash(user_id, body.password)
    try:
        user = update_user_profile(user_id, name=body.name, avatar_url=body.avatar_url, theme=body.theme)
        return {"status": "success", "user": user}
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@router.post("/upload-avatar")
async def upload_avatar(request: Request, file: UploadFile = File(...), user_id: str = Depends(get_current_user_id)):
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(400, "Only JPEG, PNG, WebP, or GIF images are allowed")
    content = await file.read()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(400, "Avatar file is too large")

    extension = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }.get(file.content_type, ".img")
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    for existing in AVATAR_DIR.glob(f"avatar_{user_id}.*"):
        existing.unlink(missing_ok=True)
    target = AVATAR_DIR / f"avatar_{user_id}{extension}"
    target.write_bytes(content)
    avatar_url = f"{str(request.base_url).rstrip('/')}/avatars/{target.name}"
    update_user_profile(user_id, avatar_url=avatar_url)
    return {"status": "success", "avatar_url": avatar_url}


@router.delete("/me")
async def delete_account(user_id: str = Depends(get_current_user_id)):
    revoke_all_user_tokens(user_id)
    delete_user_data(user_id)
    for avatar in AVATAR_DIR.glob(f"avatar_{user_id}.*") if AVATAR_DIR.exists() else []:
        avatar.unlink(missing_ok=True)
    return {"status": "success", "message": "Account deleted successfully"}
