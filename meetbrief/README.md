# Meetbrief — evidence-first meeting summaries

Meetbrief is a working local-first meeting-notes system. Add an approved transcript or notes, review the normalized source, process it with free offline extraction or an optional configured AI provider, inspect evidence links, edit and approve the result, then search and export approved summaries. It does **not** accept or ingest audio/video recordings.

The browser dashboard is powered by FastAPI and SQLite. An optional Streamlit UI uses the same data store and Python workflows. OpenAPI docs are served at `/docs`. Offline processing needs no paid account, API key, or internet connection (other than installing Python packages once).

## Quick start on Windows 10/11

Install Python 3.11 or newer from python.org (check **Add Python to PATH**), then open PowerShell in the project folder. The `py` launcher is used below; substitute `python` if that is how Python is installed.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11 or newer is required'"
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` before you use real meeting information. Set a unique `ADMIN_PASSWORD` (at least 12 characters) and replace `APP_SECRET` with a long random string. You can generate a secret with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Keep `COOKIE_SECURE=false` for plain `http://localhost`; use Secure cookies behind an HTTPS reverse proxy. Then create the local SQLite database and run the browser app:

```powershell
.\.venv\Scripts\python.exe db_setup.py
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. The API reference is **http://127.0.0.1:8000/docs** and the liveness endpoint is **http://127.0.0.1:8000/api/health**. The first admin is created from `ADMIN_USERNAME` and `ADMIN_PASSWORD` when the database is initialized. If you have not changed the example values, the local demo login is `admin` / `ChangeMe123!`. Change it before sharing your instance.

For a one-command start after setup, double-click `scripts\start_windows.bat`. To start the optional Streamlit local interface in a second window, use `scripts\start_streamlit_windows.bat` or run:

```powershell
.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py --server.address 127.0.0.1 --server.port 8501
```

Streamlit is a convenience UI for a trusted localhost environment; for multi-user use, prefer the FastAPI dashboard, which enforces CSRF and role checks on every API mutation. Do not expose Streamlit to a network without additional authentication and deployment hardening.

## Use the app

1. Sign in as an Admin and optionally add Editor/Reviewer or Viewer accounts under **Security & settings**. Passwords must be at least 12 characters.
2. Select **Add a meeting** and enter a title and date. Paste transcript text or upload `.txt`, `.docx`, or `.srt`. Use **Preview & validate** before saving. Only transcript/notes files are accepted; no recording processing is included.
3. Review the preview and save a private draft. Click **Process transcript**. Offline extractive analysis runs without a key. If an LLM provider is configured, the user must explicitly opt in before each transcript is sent externally.
4. Inspect each evidence citation, edit summary/decisions/actions/questions, and adjust topic names and line boundaries. Missing action owners or dates stay **Unspecified**. Use topic controls to split/merge neighboring sections; the repeat check highlights identical normalized wording with source links.
5. Save the draft and choose **Approve for sharing**. Approval is blocked if cited summary/action evidence is unsupported. Approved meetings are locked; only an Admin can reopen them, and the transition is recorded.
6. Search/filter the library. Download approved summaries as Markdown, TXT or JSON, and action items as CSV. Viewers only see approved meetings.

## Optional external AI

Set all three environment variables in `.env` to use an OpenAI-compatible chat-completions service:

```dotenv
LLM_BASE_URL=https://your-provider.example/v1
LLM_API_KEY=your-server-side-key
LLM_MODEL=your-supported-model-id
LLM_TIMEOUT_SECONDS=20
```

Restart the app after editing `.env`. Provider credentials are not sent to the browser. External processing remains disabled unless the user opts in for the individual transcript. The provider receives transcript content; check its storage, residency, and training terms first. Invalid JSON, unavailable providers, timeouts, and HTTP 429 rate limits fall back to offline extraction with a visible status. Do not use this sample with a real provider until its contract and privacy practices are approved. No API key is required for the basic local workflow.

## Configuration and database

`.env.example` documents supported settings. `DATABASE_PATH` chooses the SQLite file; default is `meetbrief.db` in the current working directory. `MAX_UPLOAD_MB` and `MAX_TRANSCRIPT_CHARS` bound intake; `MAX_LLM_CHARS` bounds transcript text sent to a provider. `SESSION_HOURS` controls session lifetime. `RETENTION_DAYS=0` means retain until an Admin deletes the meeting. A positive value permanently removes meetings whose last update is older than that many days when the database initializes; protect the database and backups. The first Admin is only seeded if its username does not already exist, so later environment password changes do not overwrite an existing account. `COOKIE_SECURE` should be false only on plain localhost HTTP and true for HTTPS. Never commit `.env`, database files, or real transcripts.

To initialize or reinitialize an empty database, run `.\.venv\Scripts\python.exe db_setup.py`. Startup also initializes missing tables and the initial Admin. Back up the SQLite file while the app is stopped; SQLite uses WAL mode, so include the corresponding `-wal`/`-shm` files if copying a live database. Restore by placing the backed-up DB at `DATABASE_PATH` and restarting.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests use isolated temporary SQLite files and synthetic transcripts. The test suite exercises TXT/DOCX/SRT parsing, empty and malformed input, extraction/evidence checks, timeout/invalid-response/rate-limit fallback, repeated-point citations, HTTPS/local cookie behavior, access roles, approval/reopen, search, exports, and denial of unsupported claims. The actual final run is recorded in `TEST_RESULTS.md`.

## Project map

`app/main.py` contains the FastAPI routes and server-side access controls. `app/parsers.py` handles text formats and normalization. `app/analysis.py` contains deterministic extraction, optional provider calls, and transcript-support validation. `app/service.py` owns SQLite meeting workflows and audit snapshots. `app/auth.py` owns salted password hashes and sessions. `app/exports.py` renders downloads. `app/static/` contains the responsive dashboard. `streamlit_app.py` provides a supplemental localhost UI. `docs/API.md` lists endpoints, `docs/SECURITY.md` explains privacy/security and AI limitations, and `docs/architecture.mmd` plus `docs/er.mmd` describe architecture and storage relationships. `samples/` contains synthetic-only example transcripts.

## Limitations and responsible use

The fallback is extractive and phrase-based, not a human-level semantic model; it can omit important context and miss indirectly phrased actions. It marks unprovided speaker identity unknown, and owners/dates unspecified unless explicit. Evidence matching is a useful warning, not a guarantee of truth. Human review is mandatory before sharing. This code is a local student-friendly prototype, not a certified enterprise compliance platform: no MFA, encryption-at-rest layer, email recovery, rate limiting, multi-tenant isolation, distributed workers, or production deployment hardening is included. Use synthetic/approved transcripts; assess applicable privacy, consent, retention, and provider rules before processing real data.


## Recovery, performance, and compatibility

Processing is synchronous per meeting. The dashboard shows an in-progress state; upload size, transcript length, and optional provider input are bounded. Search is filtered and paginated. There is no bulk multi-meeting import/processing queue in this student-scale build. If a browser request is interrupted, reload the library and reopen the meeting: its source and saved drafts remain in SQLite. For a draft or failed processing attempt, retry **Process transcript** after reviewing the displayed status; an approved record must first be reopened by an Admin. Restarting the app initializes missing schema and SQLite WAL handles normal interrupted writes. If the database is damaged, stop the app and restore a protected backup as described above.

Target local operating systems are Windows 10/11 (the included setup/start scripts use PowerShell and `.bat`), Linux, and macOS with Python 3.11+. The UI targets current evergreen Chrome, Edge, Firefox, and Safari; legacy Internet Explorer is not supported. Automated verification ran in a Linux sandbox with Python 3.12; Windows scripts and graphical browser compatibility were not executed in this environment. Required external packages are listed in `requirements.txt`; no provider is needed for offline mode. The optional LLM requires network access and a compatible provider account/key.
