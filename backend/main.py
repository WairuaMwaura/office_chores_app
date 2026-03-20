from fastapi import FastAPI, Form
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


class AttendanceForDatePayload(BaseModel):
    date: str
    present_ids: list[int]


class LateArrivalPayload(BaseModel):
    member_id: int
    action: str
    swap_assignment_id: Optional[int] = None


class SwapAssignmentPayload(BaseModel):
    assignment_id: int
    new_member_id: int


class AssignForDatePayload(BaseModel):
    date: str


# --- HTML Routes ---
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


# --- Setup ---
@app.get("/setup")
async def setup_db_endpoint():
    try:
        setup_database_and_tables()
        return JSONResponse(content={"message": "Database and tables initialized successfully."})
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


# --- Members ---
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


# --- Attendance (today) ---
@app.post("/api/attendance")
async def mark_attendance_api(payload: AttendancePayload):
    result = logic.mark_attendance(payload.present_ids, date.today().isoformat())
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


# --- Attendance (past date) ---
@app.get("/api/attendance/for-date")
async def get_attendance_for_date_api(date_str: str):
    """Returns members with their attendance status for a given past date."""
    try:
        target = date.fromisoformat(date_str)
    except ValueError:
        return JSONResponse(content={"error": "Invalid date format."}, status_code=400)
    if target > date.today():
        return JSONResponse(content={"error": "Cannot access future dates."}, status_code=400)
    return JSONResponse(content=logic.get_attendance_for_date(target))

@app.post("/api/attendance/for-date")
async def mark_attendance_for_date_api(payload: AttendanceForDatePayload):
    """Records attendance for a specific past date."""
    try:
        target = date.fromisoformat(payload.date)
    except ValueError:
        return JSONResponse(content={"error": "Invalid date format."}, status_code=400)
    if target > date.today():
        return JSONResponse(content={"error": "Cannot record attendance for future dates."}, status_code=400)
    result = logic.mark_attendance(payload.present_ids, payload.date)
    if "error" in result:
        return JSONResponse(content=result, status_code=400)
    return JSONResponse(content=result)


# --- Chores (today) ---
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
    result = logic.swap_assignment(payload.assignment_id, payload.new_member_id)
    if "error" in result:
        return JSONResponse(content=result, status_code=400)
    return JSONResponse(content=result)


# --- Chores (past date) ---
@app.post("/api/chores/assign-for-date")
async def assign_chores_for_date_api(payload: AssignForDatePayload):
    """Assigns chores for a past date that has no chore data yet."""
    try:
        target = date.fromisoformat(payload.date)
    except ValueError:
        return JSONResponse(content={"error": "Invalid date format."}, status_code=400)
    if target > date.today():
        return JSONResponse(content={"error": "Cannot assign chores for future dates."}, status_code=400)
    assignments, message = logic.assign_chores_for_date(target)
    if not assignments:
        return JSONResponse(content={"message": message}, status_code=400)
    return JSONResponse(content={"assignments": assignments, "message": message})

@app.get("/api/chores/for-date")
async def get_chores_for_date_api(date_str: str):
    """Returns chore assignments for a specific date."""
    try:
        target = date.fromisoformat(date_str)
    except ValueError:
        return JSONResponse(content={"error": "Invalid date format."}, status_code=400)
    return JSONResponse(content=logic.get_daily_assignments(target))


# --- History & Schedule ---
@app.get("/api/history/summary")
async def get_history_summary_api():
    return JSONResponse(content=logic.get_history_summary())

@app.get("/api/schedule")
async def get_schedule_api(days: int = 30):
    return JSONResponse(content=logic.get_schedule(days))