"""Application workflows, access rules, audit snapshots and status transitions."""
import json
import uuid
from datetime import date
from fastapi import HTTPException
from app.db import db_session, row_to_meeting, utc_now
from app.analysis import analyze, revalidate_analysis, summarize_lines
from app.parsers import parse_transcript


def _require_editor(user: dict) -> None:
    if user.get("role") not in {"Admin", "Editor/Reviewer"}:
        raise HTTPException(403, "Editor/Reviewer access is required for this change.")


def _require_admin(user: dict) -> None:
    if user.get("role") != "Admin":
        raise HTTPException(403, "Admin access is required for this action.")


def _snapshot(meeting: dict) -> str:
    safe = {key: meeting.get(key) for key in ("title", "meeting_date", "status", "analysis", "notes", "updated_at", "approved_at", "approved_by")}
    return json.dumps(safe, ensure_ascii=False)


def _record_history(db, meeting: dict, user: dict, action: str) -> None:
    db.execute("INSERT INTO history(meeting_id,actor_id,action,snapshot_json,created_at) VALUES(?,?,?,?,?)",
               (meeting["id"], user["id"], action, _snapshot(meeting), utc_now()))


def create_meeting(title: str, meeting_date: date | str, notes: str, original_text: str, filename: str | None, user: dict) -> dict:
    _require_editor(user)
    lines = parse_transcript(original_text, filename)
    meeting_id, now = str(uuid.uuid4()), utc_now()
    payload = {"id": meeting_id, "title": title.strip(), "meeting_date": str(meeting_date), "notes": notes or "", "original_text": original_text,
               "cleaned_lines": lines, "analysis": {}, "status": "draft", "created_by": user["id"], "created_at": now, "updated_at": now, "approved_by": None, "approved_at": None}
    if not payload["title"]:
        raise ValueError("A meeting title is required.")
    if len(payload["title"]) > 200 or len(notes or "") > 2000:
        raise ValueError("Meeting title must be at most 200 characters and context notes at most 2,000 characters.")
    with db_session() as db:
        db.execute("""INSERT INTO meetings(id,title,meeting_date,notes,original_text,cleaned_lines_json,analysis_json,status,created_by,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (meeting_id, payload["title"], str(meeting_date), notes or "", original_text,
              json.dumps(lines, ensure_ascii=False), "{}", "draft", user["id"], now, now))
        _record_history(db, payload, user, "Created draft from approved transcript/notes")
    return payload


def get_meeting(meeting_id: str, user: dict) -> dict:
    with db_session() as db:
        row = db.execute("SELECT * FROM meetings WHERE id=?", (meeting_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Meeting not found.")
    meeting = row_to_meeting(row)
    if user["role"] == "Viewer" and meeting["status"] != "approved":
        raise HTTPException(404, "Meeting not found.")
    return meeting


def list_meetings(user: dict, q: str = "", status: str = "", date_from: str = "", date_to: str = "", limit: int = 50, offset: int = 0) -> list[dict]:
    clauses, values = [], []
    if user["role"] == "Viewer":
        clauses.append("status='approved'")
    if status:
        clauses.append("status=?")
        values.append(status)
    if q.strip():
        clauses.append("(title LIKE ? OR notes LIKE ? OR original_text LIKE ?)")
        values.extend([f"%{q.strip()}%"] * 3)
    if date_from:
        clauses.append("meeting_date>=?")
        values.append(date_from)
    if date_to:
        clauses.append("meeting_date<=?")
        values.append(date_to)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with db_session() as db:
        rows = db.execute(f"SELECT id,title,meeting_date,status,created_at,updated_at,approved_at FROM meetings{where} ORDER BY meeting_date DESC, updated_at DESC LIMIT ? OFFSET ?", (*values, min(max(limit, 1), 100), max(offset, 0))).fetchall()
    return [dict(row) for row in rows]


def process_meeting(meeting_id: str, user: dict) -> dict:
    _require_editor(user)
    meeting = get_meeting(meeting_id, user)
    if meeting["status"] == "approved":
        raise HTTPException(409, "Reopen this meeting before processing it again.")
    try:
        result = analyze(meeting["cleaned_lines"])
        with db_session() as db:
            db.execute("UPDATE meetings SET analysis_json=?,status='processed',updated_at=? WHERE id=?", (json.dumps(result, ensure_ascii=False), utc_now(), meeting_id))
            meeting["analysis"], meeting["status"], meeting["updated_at"] = result, "processed", utc_now()
            _record_history(db, meeting, user, "Processed transcript")
        return meeting
    except Exception as exc:
        with db_session() as db:
            db.execute("UPDATE meetings SET status='failed',updated_at=? WHERE id=?", (utc_now(), meeting_id))
        raise HTTPException(502, f"Processing failed safely: {str(exc)[:240]}") from exc


def save_analysis(meeting_id: str, analysis: dict, user: dict) -> dict:
    _require_editor(user)
    meeting = get_meeting(meeting_id, user)
    if meeting["status"] == "approved":
        raise HTTPException(409, "Approved meetings are locked. An Admin must reopen this draft before editing.")
    checked = revalidate_analysis(analysis, meeting["cleaned_lines"])
    # Prevent forged topic source content; only editable labels/boundaries are accepted.
    legal_ids = {line["id"] for line in meeting["cleaned_lines"]}
    topics = []
    previous_end = 0
    for topic in checked.get("topics", []):
        start, end = topic.get("start_line"), topic.get("end_line")
        if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start or end > len(legal_ids):
            raise HTTPException(422, "Topic boundaries must reference valid transcript lines.")
        if start <= previous_end:
            raise HTTPException(422, "Topic boundaries cannot overlap; arrange topics in transcript order.")
        topic = dict(topic)
        topic["name"] = str(topic.get("name", "Topic"))[:100]
        source_lines = [line for line in meeting["cleaned_lines"] if start <= line["id"] <= end]
        topic["lines"] = [{"id": line["id"], "text": line["text"], "timestamp": line["timestamp"], "speaker": line["speaker"]} for line in source_lines]
        topic["summary_claims"] = summarize_lines(source_lines, 3)
        topics.append(topic)
        previous_end = end
    checked["topics"] = topics
    now = utc_now()
    with db_session() as db:
        db.execute("UPDATE meetings SET analysis_json=?,status='processed',updated_at=? WHERE id=?", (json.dumps(checked, ensure_ascii=False), now, meeting_id))
        meeting["analysis"], meeting["status"], meeting["updated_at"] = checked, "processed", now
        _record_history(db, meeting, user, "Saved reviewed draft")
    return meeting


def approve_meeting(meeting_id: str, user: dict) -> dict:
    _require_editor(user)
    meeting = get_meeting(meeting_id, user)
    if meeting["status"] == "approved":
        raise HTTPException(409, "This meeting is already approved.")
    analysis = revalidate_analysis(meeting.get("analysis", {}), meeting["cleaned_lines"])
    if not analysis.get("summary_claims"):
        raise HTTPException(409, "Process the transcript and add a summary before approval.")
    if analysis.get("unsupported_count", 0):
        raise HTTPException(409, "Unsupported summary claims must be edited or removed before approval.")
    if any(not item.get("supported") for section in ("decisions", "actions", "questions") for item in analysis.get(section, [])):
        raise HTTPException(409, "Every decision, action, and question needs transcript evidence before approval.")
    if any(not item.get("owner_supported", True) or not item.get("due_date_supported", True) for item in analysis.get("actions", [])):
        raise HTTPException(409, "An action owner or due date is not supported by its cited transcript excerpt.")
    now = utc_now()
    with db_session() as db:
        db.execute("UPDATE meetings SET analysis_json=?,status='approved',approved_by=?,approved_at=?,updated_at=? WHERE id=?",
                   (json.dumps(analysis, ensure_ascii=False), user["id"], now, now, meeting_id))
        meeting.update({"analysis": analysis, "status": "approved", "approved_by": user["id"], "approved_at": now, "updated_at": now})
        _record_history(db, meeting, user, "Approved for sharing")
    return meeting


def reopen_meeting(meeting_id: str, user: dict) -> dict:
    _require_admin(user)
    meeting = get_meeting(meeting_id, user)
    if meeting["status"] != "approved":
        raise HTTPException(409, "Only approved meetings can be reopened.")
    now = utc_now()
    with db_session() as db:
        db.execute("UPDATE meetings SET status='processed',approved_by=NULL,approved_at=NULL,updated_at=? WHERE id=?", (now, meeting_id))
        meeting.update({"status": "processed", "approved_by": None, "approved_at": None, "updated_at": now})
        _record_history(db, meeting, user, "Admin reopened approved meeting")
    return meeting


def get_history(meeting_id: str, user: dict) -> list[dict]:
    get_meeting(meeting_id, user)
    with db_session() as db:
        rows = db.execute("""SELECT h.id,h.action,h.snapshot_json,h.created_at,u.username FROM history h JOIN users u ON h.actor_id=u.id
            WHERE h.meeting_id=? ORDER BY h.id DESC""", (meeting_id,)).fetchall()
    return [{**dict(row), "snapshot": json.loads(row["snapshot_json"])} for row in rows]


def evidence_for(meeting_id: str, line_id: int, user: dict) -> dict:
    meeting = get_meeting(meeting_id, user)
    for line in meeting["cleaned_lines"]:
        if line["id"] == line_id:
            return {"meeting_id": meeting_id, "line_id": line_id, "text": line["text"], "original": line["original"], "timestamp": line["timestamp"], "speaker": line["speaker"]}
    raise HTTPException(404, "Evidence line not found.")


def delete_meeting(meeting_id: str, user: dict) -> None:
    _require_admin(user)
    meeting = get_meeting(meeting_id, user)
    with db_session() as db:
        db.execute("DELETE FROM meetings WHERE id=?", (meeting_id,))
