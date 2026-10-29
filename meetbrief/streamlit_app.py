"""Optional local Streamlit client. The FastAPI dashboard remains the complete primary UI."""
from datetime import date
import streamlit as st
from app.db import init_db
from app.auth import authenticate
from app.parsers import parse_transcript, TranscriptError
from app.service import create_meeting, list_meetings, get_meeting, process_meeting, save_analysis, approve_meeting
from app.exports import export_content
from app.config import settings

st.set_page_config(page_title="Meetbrief", page_icon="▤", layout="wide")
init_db()
st.title("Meetbrief")
st.caption("Evidence-first meeting summaries · transcript/notes only")
if "user" not in st.session_state:
    st.session_state.user = None
if not st.session_state.user:
    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Sign in"):
            account = authenticate(username, password)
            if account:
                st.session_state.user = account
                st.rerun()
            st.error("Username or password is incorrect.")
    st.info("Local demo admin: admin / ChangeMe123! Change this before sharing the app.")
    st.stop()
user = st.session_state.user
st.sidebar.write(f"Signed in as **{user['username']}** · {user['role']}")
if st.sidebar.button("Sign out"):
    del st.session_state.user
    st.rerun()
st.sidebar.caption("Only authorized TXT, DOCX or SRT transcripts are accepted. Recordings are not ingested.")
if user["role"] in {"Admin", "Editor/Reviewer"}:
    with st.expander("Add a meeting", expanded=True):
        title = st.text_input("Meeting title", key="new_title")
        meeting_date = st.date_input("Meeting date", value=date.today(), key="new_date")
        notes = st.text_area("Context (optional)")
        upload = st.file_uploader("Upload TXT, DOCX or SRT", type=["txt", "docx", "srt"])
        pasted = st.text_area("Or paste transcript / notes", height=160)
        allow_ai = st.checkbox("If a provider is configured, I authorize sending this transcript for external AI processing")
        if st.button("Validate and save draft", type="primary"):
            try:
                text, filename = ("", None)
                if upload:
                    from app.parsers import extract_file_text
                    text, filename = extract_file_text(upload.name, upload.getvalue()), upload.name
                else:
                    text = pasted
                lines = parse_transcript(text, filename)
                st.write(f"Validated {len(lines)} transcript lines. Original text will be retained locally.")
                draft = create_meeting(title, meeting_date, notes, text, filename, user)
                st.session_state.selected = draft["id"]
                st.session_state.allow_ai = allow_ai
                st.success("Draft saved. Open it below to process and review.")
            except (TranscriptError, ValueError) as exc:
                st.error(str(exc))
meetings = list_meetings(user, limit=100)
st.subheader("Meeting library")
query = st.text_input("Search meetings", key="search")
if query:
    meetings = list_meetings(user, q=query, limit=100)
if not meetings:
    st.info("No meetings found yet.")
for item in meetings:
    with st.container(border=True):
        left, mid, right = st.columns([5, 2, 2])
        left.markdown(f"**{item['title']}**  ·  {item['meeting_date']}")
        mid.write(item["status"].title())
        if right.button("Review", key=f"open-{item['id']}"):
            st.session_state.selected = item["id"]
        selected_id = st.session_state.get("selected")
        if selected_id == item["id"]:
            meeting = get_meeting(item["id"], user)
            st.markdown("---")
            st.markdown("#### Summary")
            if meeting["status"] == "draft" or not meeting["analysis"]:
                if st.button("Process transcript", key=f"process-{item['id']}"):
                    meeting = process_meeting(item["id"], user)
                    st.rerun()
            analysis = meeting.get("analysis", {})
            for claim in analysis.get("summary_claims", []):
                st.write(("✓ " if claim.get("supported") else "⚠ Unsupported · ") + claim["text"])
                st.caption("Evidence lines: " + ", ".join(map(str, claim.get("evidence_line_ids", []))))
            if user["role"] != "Viewer":
                st.markdown("#### Transcript")
                for line in meeting.get("cleaned_lines", []):
                    st.caption(f"{line['id']} · {line.get('timestamp') or 'time unspecified'} · {line.get('speaker','Unknown speaker')}")
                    st.write(line["text"])
                if analysis:
                    edit_summary = st.text_area("Edit first summary claim", value=analysis["summary_claims"][0]["text"] if analysis.get("summary_claims") else "", key=f"edit-summary-{item['id']}")
                    if st.button("Save summary edit", key=f"save-{item['id']}"):
                        if analysis.get("summary_claims"):
                            analysis["summary_claims"][0]["text"] = edit_summary
                            save_analysis(item["id"], analysis, user)
                            st.success("Draft saved; evidence is rechecked.")
                    st.markdown("#### Action items")
                    for action in analysis.get("actions", []):
                        st.write(f"{action['text']} · Owner: {action['owner']} · Due: {action['due_date']}")
                    if meeting["status"] != "approved" and st.button("Approve for sharing", key=f"approve-{item['id']}"):
                        try:
                            approve_meeting(item["id"], user)
                            st.success("Approved.")
                        except Exception as exc:
                            st.error(str(exc))
            if meeting["status"] == "approved":
                for fmt in ["md", "txt", "json", "csv"]:
                    try:
                        content, mime, filename = export_content(meeting, fmt)
                        st.download_button(f"Export {fmt.upper()}", content, file_name=filename, mime=mime, key=f"export-{fmt}-{item['id']}")
                    except Exception:
                        pass
            if st.button("Close review", key=f"close-{item['id']}"):
                st.session_state.pop("selected", None)
                st.rerun()
st.divider()
st.caption("Offline extractive mode is free and private by default. External AI is used only with configured credentials and per-transcript opt-in; AI output must be reviewed.")
