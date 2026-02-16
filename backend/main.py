from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from datetime import date
import os

from . import logic
from .database import setup_database_and_tables

app = FastAPI()

# Mount the 'frontend' directory to serve static files
# This makes index.html, css, and js files accessible
static_files_path = os.path.join(os.path.dirname(__file__), '..', 'frontend')
app.mount("/static", StaticFiles(directory=static_files_path), name="static")


class AttendancePayload(BaseModel):
    present_ids: list[int]


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


# --- API Endpoints ---

@app.get("/setup")
async def setup_db_endpoint():
    """A one-time endpoint to initialize the database and tables."""
    try:
        setup_database_and_tables()
        return JSONResponse(content={
            "message": "Database and tables initialized successfully."},
                            status_code=200)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/api/members")
async def get_members_api():
    members = logic.get_active_members()
    return JSONResponse(content=members)


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
    today_str = date.today().isoformat()
    result = logic.mark_attendance(payload.present_ids, today_str)
    if "error" in result:
        return JSONResponse(content=result, status_code=400)
    return JSONResponse(content=result)


@app.post("/api/chores/assign")
async def assign_chores_api():
    assignments, message = logic.assign_chores_for_today()
    if not assignments:
        return JSONResponse(content={"message": message}, status_code=400)
    return JSONResponse(
        content={"assignments": assignments, "message": message})


@app.get("/api/chores/today")
async def get_todays_chores_api():
    assignments = logic.get_daily_assignments(date.today())
    return JSONResponse(content=assignments)


@app.get("/api/history/summary")
async def get_history_summary_api():
    summary = logic.get_history_summary()
    return JSONResponse(content=summary)