# Security, privacy, and responsible use

## Data and retention

Meetbrief accepts public, synthetic, or explicitly approved transcript text and meeting notes only; it does not transcribe or ingest recordings. The original text and normalized lines are stored in SQLite in the configured `DATABASE_PATH`, alongside generated analysis, users, sessions, and audit history. Default retention is indefinite (`RETENTION_DAYS=0`) until an Admin deletes a meeting or securely removes the database. A positive `RETENTION_DAYS` value permanently deletes meetings whose last update is older than that many days when the database initializes; deletion cascades to audit history. Choose an appropriate period and maintain protected backups. Encrypt the disk, protect backup media, restrict database-file access, and do not put confidential transcript data into a shared or public instance without an approved hosting/privacy assessment. Application diagnostics do not log transcript request bodies or provider credentials; audit history records workflow actions and actor/meeting identifiers.

## Identity and access

Roles are enforced in FastAPI, not just in the UI. Admin manages accounts, deletes records, and alone can reopen approved summaries. Editor/Reviewer can ingest, process, edit, review, approve, search and export. Viewer can read approved summaries and cited excerpts only. Passwords use PBKDF2-HMAC-SHA256 with random salts and 310,000 iterations. Sessions use random opaque tokens; only token hashes are stored in SQLite. Cookies are HttpOnly and use `SameSite=None; Secure` for HTTPS Preview; plain-HTTP localhost uses `SameSite=Lax` without Secure so browsers retain the session. Mutations require a database-bound CSRF token. The default local demo credentials are intentionally convenient: change them before anyone else can access the app.

The app is designed for a single trusted local deployment. It does not include MFA, password reset/email delivery, account lockout/rate limiting, database encryption at rest, tenant isolation, or an enterprise identity provider. Do not expose it directly to the public internet without a security review, TLS-terminating reverse proxy, strong secrets, backups, and additional abuse protections. Use a strong unique `APP_SECRET`, restrict the host firewall, and keep `.env` and SQLite files out of Git.

## Optional external AI

Offline extractive mode requires no API key and keeps processing on the app host. It selects transcript sentences; it can miss context, does not understand implied meaning, and requires human checking. If all of `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL` are set, an OpenAI-compatible chat-completions provider becomes available. The user must opt in per transcript/processing request. When opted in, transcript text (up to `MAX_LLM_CHARS`, 80,000 by default) is sent to that provider; larger inputs stay local. Review provider retention, residency, and training policies before use. Secrets remain in server environment variables and are never returned to the browser. Provider timeouts, HTTP 429 rate limits, invalid responses, and unsupported output fall back to extractive mode with a visible status.

LLM summaries cite source line IDs and are checked for lexical support against those lines. A match score is not proof that the claim is true or complete. Unsupported claims are visibly flagged and approval is blocked until corrected or removed. Decisions/actions/questions in offline mode are conservative phrase-based candidates, not guaranteed complete. No names, owners, due dates, or decisions are inferred; missing owner/date fields are `Unspecified`. Speaker labels reflect only the source label; missing identities remain `Unknown speaker`.

## Human review and sharing

AI output is a draft, not an official record. Approved summaries are human-approved, locked against editing, and are the only records downloadable or visible to Viewers. Approval checks evidence links; users remain responsible for source context, transcription accuracy, legal basis, and distribution. Admin reopening and record deletion are auditable where the history itself remains.
