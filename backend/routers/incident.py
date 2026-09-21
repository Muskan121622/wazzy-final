import sys
import os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from services.auth_service import get_current_user, assert_trip_ownership
from services.monitor import (
    create_recovery_proposal,
    approve_recovery_proposal,
    reject_recovery_proposal,
    evaluate_schedule_delay,
    check_closed_places,
    get_pending_proposals,
)
from services.optimizer import get_right_now_recommendation
from services.host_service import get_host_recommendations

router = APIRouter(prefix="/api/incident", tags=["Incident & Recovery"])


class IncidentTriggerRequest(BaseModel):
    trip_id: str
    day_number: int = 1


class ClosedPlacesRequest(BaseModel):
    trip_id: str
    day_number: int = 1


class ProposalDecisionRequest(BaseModel):
    proposal_id: str


class DelayEvaluationRequest(BaseModel):
    trip_id: str
    day_number: int = 1
    delay_minutes: int = 45
    delayed_item_id: str | None = None
    user_lat: float | None = None
    user_lon: float | None = None
    speed_kmh: float = 25.0
    current_time: str | None = None  # traveller's local "now" (HH:MM or 'hh:mm AM') for live GPS mode


@router.post("/trigger")
def trigger_incident(req: IncidentTriggerRequest, user: dict = Depends(get_current_user)):
    assert_trip_ownership(req.trip_id, user["id"])
    return create_recovery_proposal(trip_id=req.trip_id, day_number=req.day_number)


@router.post("/check-closed")
def check_closed(req: ClosedPlacesRequest, user: dict = Depends(get_current_user)):
    assert_trip_ownership(req.trip_id, user["id"])
    return check_closed_places(trip_id=req.trip_id, day_number=req.day_number)


@router.post("/evaluate-delay")
def evaluate_delay(req: DelayEvaluationRequest, user: dict = Depends(get_current_user)):
    assert_trip_ownership(req.trip_id, user["id"])
    return evaluate_schedule_delay(
        trip_id=req.trip_id,
        day_number=req.day_number,
        delayed_item_id=req.delayed_item_id,
        delay_minutes=req.delay_minutes,
        user_lat=req.user_lat,
        user_lon=req.user_lon,
        speed_kmh=req.speed_kmh,
        current_time=req.current_time,
    )


@router.get("/proposals")
def list_pending_proposals(trip_id: str, user: dict = Depends(get_current_user)):
    assert_trip_ownership(trip_id, user["id"])
    return get_pending_proposals(trip_id=trip_id, user_id=user["id"])


@router.post("/approve")
def approve_proposal(req: ProposalDecisionRequest, user: dict = Depends(get_current_user)):
    res = approve_recovery_proposal(proposal_id=req.proposal_id, user_id=user["id"])
    if res.get("status") == "FORBIDDEN":
        raise HTTPException(status_code=403, detail=res["message"])
    return res


@router.post("/reject")
def reject_proposal(req: ProposalDecisionRequest, user: dict = Depends(get_current_user)):
    res = reject_recovery_proposal(proposal_id=req.proposal_id, user_id=user["id"])
    if res.get("status") == "FORBIDDEN":
        raise HTTPException(status_code=403, detail=res["message"])
    return res


@router.get("/right-now")
def get_right_now(trip_id: str, is_rainy: bool = False, user: dict = Depends(get_current_user)):
    assert_trip_ownership(trip_id, user["id"])
    res = get_right_now_recommendation(trip_id=trip_id, is_rainy=is_rainy)
    return {"candidates": res}


@router.get("/host-tips")
def get_host_tips(trip_id: str, user: dict = Depends(get_current_user)):
    assert_trip_ownership(trip_id, user["id"])
    res = get_host_recommendations(trip_id=trip_id)
    return {"host_tips": res}
