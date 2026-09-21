import sys
import os
import traceback
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional, List

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from services.agent import run_agent_chat
from services.auth_service import get_current_user, assert_trip_ownership
from database.db import get_connection

router = APIRouter(prefix="/api/chat", tags=["Agent Chat"])


class ChatMessage(BaseModel):
    role: str   # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    user_message: str
    trip_id: Optional[str] = None
    destination: Optional[str] = None
    history: Optional[List[ChatMessage]] = []


def _resolve_active_trip(user_id: str, requested: Optional[str]) -> Optional[str]:
    if requested:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM trips WHERE id = ?", (requested,))
        row = cur.fetchone()
        conn.close()
        if row and row["user_id"] == user_id:
            return requested
        return None
    # fall back to the user's most recent active trip
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM trips WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    )
    row = cur.fetchone()
    conn.close()
    return row["id"] if row else None


@router.post("")
def chat_with_agent(req: ChatRequest, user: dict = Depends(get_current_user)):
    try:
        trip_id = _resolve_active_trip(user["id"], req.trip_id)
        if not trip_id:
            return {
                "reply": "You don't have a trip yet — generate one first and I can manage it for you! 🧳",
                "tool_executed": None, "tool_args": {}, "tool_result": None, "rag_context": [],
            }
        history = [{"role": m.role, "content": m.content} for m in (req.history or [])]
        res = run_agent_chat(
            req.user_message,
            trip_id=trip_id,
            destination=req.destination,
            history=history,
            user=user,
        )
        res["trip_id"] = trip_id
        return res
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[CHAT ERROR] {e}\n{tb}")
        return {
            "reply": "TripOS Agent encountered an error. Please try again.",
            "tool_executed": None, "tool_args": {}, "tool_result": None, "rag_context": [],
        }
