"""Auth API router."""
from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.dependencies import get_current_user
from app.auth.models import TokenResponse, UserCreate, UserLogin, UserResponse
from app.auth.security import create_access_token, hash_password, verify_password
from app.database_route import db_cursor

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/register", response_model=TokenResponse)
def register(payload: UserCreate):
    with db_cursor() as cursor:
        cursor.execute("SELECT id FROM users WHERE username = ?", (payload.username,))
        if cursor.fetchone():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已存在")
        hashed = hash_password(payload.password)
        cursor.execute(
            "INSERT INTO users (username, hashed_password, role) VALUES (?, ?, ?)",
            (payload.username, hashed, "admin"),
        )
        user_id = cursor.lastrowid
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        user = dict(cursor.fetchone())
    token = create_access_token({"sub": str(user["id"])})
    return TokenResponse(
        access_token=token,
        user=UserResponse(id=user["id"], username=user["username"], role=user["role"], is_active=bool(user["is_active"])),
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: UserLogin):
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM users WHERE username = ? AND is_active = 1", (payload.username,))
        user_row = cursor.fetchone()
    if user_row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    user = dict(user_row)
    if not verify_password(payload.password, user["hashed_password"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    token = create_access_token({"sub": str(user["id"])})
    return TokenResponse(
        access_token=token,
        user=UserResponse(id=user["id"], username=user["username"], role=user["role"], is_active=bool(user["is_active"])),
    )


@router.get("/me", response_model=UserResponse)
def read_current_user(current_user: dict = Depends(get_current_user)):
    return UserResponse(
        id=current_user["id"],
        username=current_user["username"],
        role=current_user["role"],
        is_active=bool(current_user["is_active"]),
    )
