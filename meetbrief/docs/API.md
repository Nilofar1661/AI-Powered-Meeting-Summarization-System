# Meetbrief API

FastAPI exposes interactive OpenAPI docs at `/docs` and a schema at `/openapi.json` while the server is running. All API paths are same-origin under `/api`; authenticated routes use an HttpOnly `meetbrief_session` cookie. Every state-changing authenticated request requires the `X-CSRF-Token` returned by `/api/auth/login` or `/api/auth/me`.

## Authentication and access

| Method | Path | Access | Purpose |
|---|---|---|---|
| POST | `/api/auth/login` | Public | Sign in; returns identity and CSRF token |
| GET | `/api/auth/me` | Signed-in | Get current role and CSRF token |
| POST | `/api/auth/logout` | Signed-in + CSRF | Revoke this session |
| POST | `/api/auth/change-password` | Signed-in + CSRF | Change own password; invalidates sessions |
| GET | `/api/admin/users` | Admin | List accounts |
| POST | `/api/admin/users` | Admin + CSRF | Create Admin, Editor/Reviewer, or Viewer |

## Meetings

| Method | Path | Access | Purpose |
|---|---|---|---|
| GET | `/api/health` | Public | Liveness and AI mode |
| GET | `/api/settings` | Signed-in | Safe configuration and retention disclosures; no keys |
| POST | `/api/meetings/preview` | Editor/Reviewer + CSRF | Validate pasted text or TXT/DOCX/SRT upload without storing |
| POST | `/api/meetings` | Editor/Reviewer + CSRF | Create a local draft (multipart form) |
| GET | `/api/meetings` | Signed-in | Search and filter, with limit/offset pagination |
| GET | `/api/meetings/{id}` | Signed-in | Inspect a meeting; viewers see only approved items |
| POST | `/api/meetings/{id}/process` | Editor/Reviewer + CSRF | Analyze; external provider requires `allow_external_ai=true` |
| PUT | `/api/meetings/{id}/analysis` | Editor/Reviewer + CSRF | Save edited summary/decisions/actions/questions/topics |
| PUT | `/api/meetings/{id}/topics` | Editor/Reviewer + CSRF | Edit topic names and line boundaries |
| POST | `/api/meetings/{id}/topics/{topic_id}/split` | Editor/Reviewer + CSRF | Split a topic at a transcript line |
| POST | `/api/meetings/{id}/topics/{topic_id}/merge` | Editor/Reviewer + CSRF | Merge neighboring topics |
| PATCH | `/api/meetings/{id}/metadata` | Editor/Reviewer + CSRF | Edit title/date/notes on a draft |
| GET | `/api/meetings/{id}/evidence/{line_id}` | Signed-in | Inspect an exact excerpt/timestamp; viewer only for approved meetings |
| GET | `/api/meetings/{id}/history` | Signed-in | Read audit snapshots and actions |
| POST | `/api/meetings/{id}/approve` | Editor/Reviewer + CSRF | Approve after evidence checks |
| POST | `/api/meetings/{id}/reopen` | Admin + CSRF | Reopen approved record; audited |
| GET | `/api/meetings/{id}/export/{md|txt|json|csv}` | Signed-in | Approved-only downloads |
| DELETE | `/api/meetings/{id}` | Admin + CSRF | Permanently remove meeting and linked history |

`POST /api/meetings/preview` accepts multipart `file` or `transcript`. `POST /api/meetings` accepts multipart `title`, `meeting_date` (`YYYY-MM-DD`), optional `notes`, and `file` or `transcript`. Recordings/audio/video are rejected by extension/type. Errors return standard JSON `detail` messages with 4xx/5xx codes; provider timeout/invalid responses fall back to local extraction. Search supports `q`, `status`, `date_from`, `date_to`, `limit` (1–100) and `offset`.

A default Admin is bootstrapped from `ADMIN_USERNAME` and `ADMIN_PASSWORD` on first database initialization. Create other roles through the Admin account; the API enforces permissions regardless of what the UI displays.


## Response notes and recovery

The meeting analysis includes `repeated_points`: exact normalized duplicate transcript lines, their occurrence count, and all cited source line IDs. It is a review cue only; repeated statements are not removed or merged. `ai_mode` reports provider status. A provider HTTP 429 is surfaced as a rate-limit message and processing returns the local extractive result; timeout, invalid JSON, and unavailable-provider cases also fall back locally. Transcript text is never sent externally unless that processing request includes `allow_external_ai=true` and the provider is configured. If a request is interrupted, reopen the saved draft and retry processing; the original transcript remains in SQLite. Restart performs database initialization and normal SQLite WAL recovery.

Session cookies are `HttpOnly`. HTTPS Preview uses `SameSite=None; Secure`; plain HTTP localhost uses `SameSite=Lax` without Secure so the browser accepts and returns the cookie. Set `COOKIE_SECURE=true` only when served through HTTPS.
