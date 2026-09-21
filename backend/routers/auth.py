import sys
import os
from fastapi import APIRouter, Depends
from pydantic import BaseModel

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from services.auth_service import (
    register_user, login_user, create_user, create_token, get_current_user
)

router = APIRouter(prefix="/api/auth", tags=["Auth"])


class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class GuestRequest(BaseModel):
    name: str = "Guest Traveler"


def _auth_payload(user: dict) -> dict:
    return {
        "token": create_token(user["id"]),
        "user": {"id": user["id"], "name": user["name"], "email": user.get("email"), "is_guest": bool(user.get("is_guest"))},
    }


@router.post("/register")
def register(req: RegisterRequest):
    user = register_user(req.name, req.email, req.password)
    return {"status": "SUCCESS", **_auth_payload(user)}


@router.post("/login")
def login(req: LoginRequest):
    user = login_user(req.email, req.password)
    return {"status": "SUCCESS", **_auth_payload(user)}


@router.post("/guest")
def guest(req: GuestRequest):
    user = create_user(name=req.name, email=None, password=None, is_guest=True)
    return {"status": "SUCCESS", **_auth_payload(user)}


@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    return {
        "id": user["id"],
        "name": user["name"],
        "email": user.get("email"),
        "is_guest": bool(user.get("is_guest")),
    }
