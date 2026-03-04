from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from datetime import date
from typing import Optional
import os
from . import logic
from .database import setup_database_and_tables

app = FastAPI()

static_files_path = os.path.join(os.path.dirname(__file__), '..', 'frontend')
app.mount("/static", StaticFiles(directory=static_files_path), name="static")


class AttendancePayload(BaseModel):
    present_ids: list[int]


class LateArrivalPayload(BaseModel):
    member_id: int
    action: str
    swap_assignment_id: Optional[int] = None


class SwapAssignmentPayload(BaseModel):
    assignment_id: int
    new_member_id: int


# --- HTML Page Routes ---
@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(static_files_path, 'index.html'))

@app.get("/people")
async def serve_people_page():
    return FileResponse(os.path.join(static_files_path, 'people.html'))

@app.get("/history")
async def serve_history_page():
    return FileResponse(os.path.join(static_files_path, 'history.html'))

@app.get("/schedule")
async def serve_schedule_page():
    return FileResponse(os.path.join(static_files_path, 'schedule.html'))


# --- API Endpoints ---
@app.get("/setup")
async def setup_db_endpoint():
    try:
        setup_database_and_tables()
        return JSONResponse(content={"message": "Database and tables initialized successfully."})
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.get("/api/members")
async def get_members_api():
    return JSONResponse(content=logic.get_active_members())

@app.post("/api/members/add")
async def add_member_api(name: str = Form(...)):
    result = logic.add_member(name)
    if "error" in result:
        return JSONResponse(content=result, status_code=400)
    return JSONResponse(content=result)

@app.post("/api/members/remove")
async def remove_member_api(member_id: int = Form(...)):
    result = logic.remove_member(member_id)
    if "error" in result:
        return JSONResponse(content=result, status_code=400)
    return JSONResponse(content=result)

@app.post("/api/attendance")
async def mark_attendance_api(payload: AttendancePayload):
    result = logic.mark_attendance(payload.present_ids, date.today().isoformat())
    if "error" in result:
        return JSONResponse(content=result, status_code=400)
    return JSONResponse(content=result)

@app.post("/api/chores/assign")
async def assign_chores_api():
    assignments, message = logic.assign_chores_for_today()
    if not assignments:
        return JSONResponse(content={"message": message}, status_code=400)
    return JSONResponse(content={"assignments": assignments, "message": message})

@app.get("/api/chores/today")
async def get_todays_chores_api():
    return JSONResponse(content=logic.get_daily_assignments(date.today()))

@app.get("/api/chores/status")
async def get_chore_status_api():
    status = logic.get_todays_chore_status()
    if not status:
        return JSONResponse(content={"error": "Could not fetch chore status."}, status_code=500)
    return JSONResponse(content=status)

@app.post("/api/chores/swap")
async def swap_assignment_api(payload: SwapAssignmentPayload):
    """Swap an assigned person with someone else."""
    result = logic.swap_assignment(payload.assignment_id, payload.new_member_id)
    if "error" in result:
        return JSONResponse(content=result, status_code=400)
    return JSONResponse(content=result)

@app.get("/api/attendance/absent-today")
async def get_absent_today_api():
    return JSONResponse(content=logic.get_absent_members_today())

@app.post("/api/attendance/late-arrival")
async def mark_late_arrival_api(payload: LateArrivalPayload):
    result = logic.mark_late_arrival(
        member_id=payload.member_id,
        action=payload.action,
        swap_assignment_id=payload.swap_assignment_id
    )
    if "error" in result:
        return JSONResponse(content=result, status_code=400)
    return JSONResponse(content=result)

@app.get("/api/history/summary")
async def get_history_summary_api():
    return JSONResponse(content=logic.get_history_summary())

@app.get("/api/schedule")
async def get_schedule_api(days: int = 30):
    return JSONResponse(content=logic.get_schedule(days))