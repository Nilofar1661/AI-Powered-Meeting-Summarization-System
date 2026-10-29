"""Meetbrief FastAPI application. All authorization is enforced in these handlers."""
from contextlib import asynccontextmanager
from datetime import date, datetime
import json
import secrets
from pathlib import Path
from typing import Annotated, Literal
from fastapi import FastAPI, Depends, File, Form, HTTPException, UploadFile, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from app.config import settings
from app.db import init_db, db_session, utc_now
from app.auth import (COOKIE_NAME, authenticate, current_user, make_session, hash_password,
                      verify_password, require_user, require_editor, require_admin, _token_hash)
from app.schemas import LoginRequest, UserCreate, PasswordChange, AnalysisEdit, TopicEdit, TopicSplit, TopicMerge
from app.parsers import TranscriptError, extract_file_text, parse_transcript
from app.service import (create_meeting, get_meeting, list_meetings, process_meeting,
                         save_analysis, approve_meeting, reopen_meeting, get_history,
                         evidence_for, delete_meeting)
from app.exports import export_content

STATIC_DIR = Path(__file__).parent / "static"

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="Meetbrief API", description="Evidence-first transcript summarization and review.", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

def _cookie_samesite() -> Literal["none", "lax"]:
    return "none" if settings.cookie_secure else "lax"

@app.middleware("http")
async def request_size_guard(request: Request, call_next):
    length = request.headers.get("content-length")
    if length:
        try:
            if int(length) > settings.max_upload_bytes + 1_000_000:
                return JSONResponse(status_code=413, content={"detail": "Request is too large. Reduce the upload or split the transcript."})
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length header."})
    return await call_next(request)


def _user_public(user: dict) -> dict:
    return {"id": user["id"], "username": user["username"], "role": user["role"]}


def _meeting_public(meeting: dict, user: dict) -> dict:
    result = {key: value for key, value in meeting.items() if key not in {"original_text", "cleaned_lines", "analysis_json", "cleaned_lines_json"}}
    result["analysis"] = meeting.get("analysis", {})
    if user["role"] != "Viewer":
        result["cleaned_lines"] = [{key: line.get(key) for key in ("id", "text", "timestamp", "speaker")} for line in meeting.get("cleaned_lines", [])]
    return result


def _read_upload(file: UploadFile | None, transcript: str) -> tuple[str, str | None]:
    if file is not None and file.filename:
        data = file.file.read(settings.max_upload_bytes + 1)
        if len(data) > settings.max_upload_bytes:
            raise HTTPException(413, f"File is too large. Maximum upload size is {settings.max_upload_bytes // (1024*1024)} MB.")
        try:
            return extract_file_text(file.filename, data), file.filename
        except TranscriptError as exc:
            raise HTTPException(422, str(exc)) from exc
    if not transcript.strip():
        raise HTTPException(422, "Transcript is empty. Paste notes or upload a transcript first.")
    if len(transcript) > settings.max_transcript_chars:
        raise HTTPException(413, f"Transcript exceeds the {settings.max_transcript_chars:,}-character limit. Split it into smaller meetings.")
    return transcript, None


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/manus-routes.json", include_in_schema=False)
def route_manifest():
    return FileResponse(Path(__file__).parent.parent / "manus-routes.json", media_type="application/json")

@app.get("/api/health")
def health():
    return {"status": "ok", "app": "Meetbrief", "mode": "offline-extractive" if not settings.llm_enabled else "LLM available; explicit per-transcript opt-in required"}

@app.post("/api/auth/login")
def login(payload: LoginRequest, response: Response):
    user = authenticate(payload.username, payload.password)
    if not user:
        raise HTTPException(401, "Username or password is incorrect.")
    token, csrf = make_session(user["id"])
    response.set_cookie(COOKIE_NAME, token, httponly=True, secure=settings.cookie_secure, samesite=_cookie_samesite(), max_age=settings.session_hours * 3600, path="/")
    return {"user": _user_public(user), "csrf_token": csrf}

@app.get("/api/auth/me")
def whoami(user: dict = Depends(require_user)):
    return {"user": _user_public(user), "csrf_token": user["csrf_token"]}

@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    user = current_user(request, write=True)
    token = request.cookies.get(COOKIE_NAME, "")
    with db_session() as db:
        db.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))
    response.delete_cookie(COOKIE_NAME, path="/", secure=settings.cookie_secure, httponly=True, samesite=_cookie_samesite())
    return {"ok": True, "username": user["username"]}

@app.post("/api/auth/change-password")
def change_password(payload: PasswordChange, request: Request):
    user = current_user(request, write=True)
    with db_session() as db:
        row = db.execute("SELECT password_hash FROM users WHERE id=?", (user["id"],)).fetchone()
        if not row or not verify_password(payload.current_password, row["password_hash"]):
            raise HTTPException(400, "Current password is incorrect.")
        db.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(payload.new_password), user["id"]))
        db.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
    return {"ok": True, "message": "Password changed. Sign in again."}

@app.get("/api/settings")
def settings_view(user: dict = Depends(require_user)):
    return {"role": user["role"], "llm_configured": settings.llm_enabled, "llm_model": settings.llm_model if settings.llm_enabled else None,
            "max_upload_mb": settings.max_upload_bytes // (1024 * 1024), "max_transcript_chars": settings.max_transcript_chars,
            "retention_days": settings.retention_days, "external_processing_requires_opt_in": True,
            "retention_note": (f"Records older than {settings.retention_days} days since their last update are removed when the database initializes." if settings.retention_days else "SQLite records remain on this machine until an Admin removes a meeting or the database is securely deleted.")}

@app.get("/api/admin/users")
def users_list(user: dict = Depends(require_admin)):
    with db_session() as db:
        rows = db.execute("SELECT id,username,role,created_at,active FROM users ORDER BY username").fetchall()
    return [dict(row) for row in rows]

@app.post("/api/admin/users", status_code=201)
def add_user(payload: UserCreate, user: dict = Depends(require_admin)):
    with db_session() as db:
        try:
            cursor = db.execute("INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,?,?)",
                                (payload.username, hash_password(payload.password), payload.role, utc_now()))
        except Exception as exc:
            if "unique" in str(exc).lower():
                raise HTTPException(409, "That username already exists.") from exc
            raise
        row = db.execute("SELECT id,username,role,created_at,active FROM users WHERE id=?", (cursor.lastrowid,)).fetchone()
    return dict(row)

@app.post("/api/meetings/preview")
async def preview_transcript(user: dict = Depends(require_editor), file: UploadFile | None = File(default=None), transcript: str = Form(default="")):
    text, filename = _read_upload(file, transcript)
    try:
        lines = parse_transcript(text, filename)
    except TranscriptError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"filename": filename, "character_count": len(text), "line_count": len(lines), "preview": lines[:12], "warnings": ["Recording uploads are not accepted; use only transcripts or notes you are authorized to process."]}

@app.post("/api/meetings", status_code=201)
async def create_meeting_route(user: dict = Depends(require_editor), title: str = Form(...), meeting_date: str = Form(...), notes: str = Form(default=""), transcript: str = Form(default=""), file: UploadFile | None = File(default=None)):
    try:
        parsed_date = date.fromisoformat(meeting_date)
    except ValueError as exc:
        raise HTTPException(422, "Meeting date must be a valid YYYY-MM-DD date.") from exc
    text, filename = _read_upload(file, transcript)
    try:
        meeting = create_meeting(title, parsed_date, notes, text, filename, user)
    except TranscriptError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _meeting_public(meeting, user)

@app.get("/api/meetings")
def meetings_list(q: str = "", status: str = "", date_from: str = "", date_to: str = "", limit: int = 50, offset: int = 0, user: dict = Depends(require_user)):
    allowed = {"", "draft", "processing", "processed", "approved", "failed"}
    if status not in allowed:
        raise HTTPException(422, "Unknown meeting status filter.")
    return list_meetings(user, q, status, date_from, date_to, limit, offset)

@app.get("/api/meetings/{meeting_id}")
def meeting_detail(meeting_id: str, user: dict = Depends(require_user)):
    return _meeting_public(get_meeting(meeting_id, user), user)

@app.post("/api/meetings/{meeting_id}/process")
def process(meeting_id: str, allow_external_ai: bool = Form(default=False), user: dict = Depends(require_editor)):
    meeting = get_meeting(meeting_id, user)
    if meeting["status"] == "approved":
        raise HTTPException(409, "Approved meetings are locked. An Admin must reopen this meeting before processing.")
    if allow_external_ai and not settings.llm_enabled:
        # Do not imply consent succeeded when no provider is configured; fallback still works.
        allow_external_ai = False
    try:
        result = __import__("app.analysis", fromlist=["analyze"]).analyze(meeting["cleaned_lines"], allow_external_ai=allow_external_ai)
        now = utc_now()
        with db_session() as db:
            db.execute("UPDATE meetings SET analysis_json=?,status='processed',updated_at=? WHERE id=?", (json.dumps(result, ensure_ascii=False), now, meeting_id))
        updated = get_meeting(meeting_id, user)
        updated["analysis"], updated["status"] = result, "processed"
        from app.service import _record_history
        with db_session() as db:
            _record_history(db, updated, user, "Processed transcript" + (" with opted-in external AI" if allow_external_ai else " with offline extractive analysis"))
        return _meeting_public(updated, user)
    except HTTPException:
        raise
    except Exception as exc:
        with db_session() as db:
            db.execute("UPDATE meetings SET status='failed',updated_at=? WHERE id=?", (utc_now(), meeting_id))
        raise HTTPException(502, f"Processing failed safely. Your transcript is saved; retry or use the offline fallback. ({type(exc).__name__})") from exc

@app.put("/api/meetings/{meeting_id}/analysis")
def analysis_update(meeting_id: str, payload: AnalysisEdit, user: dict = Depends(require_editor)):
    return _meeting_public(save_analysis(meeting_id, payload.analysis, user), user)

@app.put("/api/meetings/{meeting_id}/topics")
def topics_update(meeting_id: str, payload: TopicEdit, user: dict = Depends(require_editor)):
    meeting = get_meeting(meeting_id, user)
    analysis = dict(meeting.get("analysis", {}))
    analysis["topics"] = payload.topics
    return _meeting_public(save_analysis(meeting_id, analysis, user), user)

@app.post("/api/meetings/{meeting_id}/topics/{topic_id}/split")
def split_topic(meeting_id: str, topic_id: str, payload: TopicSplit, user: dict = Depends(require_editor)):
    meeting = get_meeting(meeting_id, user)
    analysis = dict(meeting.get("analysis", {}))
    topics = [dict(topic) for topic in analysis.get("topics", [])]
    target = next((topic for topic in topics if topic.get("id") == topic_id), None)
    if not target or payload.at_line <= target["start_line"] or payload.at_line > target["end_line"]:
        raise HTTPException(422, "Choose a transcript line inside the topic, after its first line.")
    left = dict(target, end_line=payload.at_line - 1)
    right = dict(target, id=f"{topic_id}-split-{payload.at_line}", name=f"{target['name']} (continued)", start_line=payload.at_line)
    index = topics.index(target)
    topics[index:index+1] = [left, right]
    analysis["topics"] = topics
    return _meeting_public(save_analysis(meeting_id, analysis, user), user)

@app.post("/api/meetings/{meeting_id}/topics/{topic_id}/merge")
def merge_topic(meeting_id: str, topic_id: str, payload: TopicMerge, user: dict = Depends(require_editor)):
    meeting = get_meeting(meeting_id, user)
    analysis = dict(meeting.get("analysis", {}))
    topics = [dict(topic) for topic in analysis.get("topics", [])]
    source = next((topic for topic in topics if topic.get("id") == topic_id), None)
    target = next((topic for topic in topics if topic.get("id") == payload.target_topic_id), None)
    if not source or not target or source is target:
        raise HTTPException(422, "Select two different topics to merge.")
    if abs(topics.index(source) - topics.index(target)) != 1:
        raise HTTPException(422, "Only neighboring topics can be merged.")
    combined = dict(target, name=(target["name"] if target["name"] == source["name"] else f"{target['name']} + {source['name']}")[:100],
                    start_line=min(source["start_line"], target["start_line"]), end_line=max(source["end_line"], target["end_line"]))
    # Dicts are unhashable, so remove the two topics by their stable identifiers.
    topics = [topic for topic in topics if topic.get("id") not in {source.get("id"), target.get("id")}]
    topics.append(combined)
    topics.sort(key=lambda item: item["start_line"])
    analysis["topics"] = topics
    return _meeting_public(save_analysis(meeting_id, analysis, user), user)

@app.patch("/api/meetings/{meeting_id}/metadata")
def metadata_update(meeting_id: str, title: str = Form(...), meeting_date: str = Form(...), notes: str = Form(default=""), user: dict = Depends(require_editor)):
    meeting = get_meeting(meeting_id, user)
    if meeting["status"] == "approved":
        raise HTTPException(409, "Approved records are locked. Ask an Admin to reopen this meeting.")
    try:
        parsed_date = date.fromisoformat(meeting_date)
    except ValueError as exc:
        raise HTTPException(422, "Meeting date must be YYYY-MM-DD.") from exc
    title = title.strip()
    if not title:
        raise HTTPException(422, "A meeting title is required.")
    now = utc_now()
    with db_session() as db:
        db.execute("UPDATE meetings SET title=?,meeting_date=?,notes=?,updated_at=? WHERE id=?", (title, str(parsed_date), notes[:2000], now, meeting_id))
    updated = get_meeting(meeting_id, user)
    from app.service import _record_history
    with db_session() as db:
        _record_history(db, updated, user, "Edited meeting metadata")
    return _meeting_public(updated, user)

@app.post("/api/meetings/{meeting_id}/approve")
def approve(meeting_id: str, user: dict = Depends(require_editor)):
    return _meeting_public(approve_meeting(meeting_id, user), user)

@app.post("/api/meetings/{meeting_id}/reopen")
def reopen(meeting_id: str, user: dict = Depends(require_admin)):
    return _meeting_public(reopen_meeting(meeting_id, user), user)

@app.get("/api/meetings/{meeting_id}/evidence/{line_id}")
def evidence(meeting_id: str, line_id: int, user: dict = Depends(require_user)):
    return evidence_for(meeting_id, line_id, user)

@app.get("/api/meetings/{meeting_id}/history")
def history(meeting_id: str, user: dict = Depends(require_user)):
    return get_history(meeting_id, user)

@app.get("/api/meetings/{meeting_id}/export/{fmt}")
def export(meeting_id: str, fmt: str, user: dict = Depends(require_user)):
    meeting = get_meeting(meeting_id, user)
    content, media_type, filename = export_content(meeting, fmt)
    return Response(content=content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{meeting_id[:8]}-{filename}"'})

@app.delete("/api/meetings/{meeting_id}")
def remove_meeting(meeting_id: str, user: dict = Depends(require_admin)):
    delete_meeting(meeting_id, user)
    return {"ok": True, "message": "Meeting and associated audit history were permanently removed."}
