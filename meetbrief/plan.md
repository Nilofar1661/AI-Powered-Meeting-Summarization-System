# Meetbrief implementation and design plan

## Product approach

Meetbrief is an evidence-first, local-first meeting summary system. The browser dashboard is served by FastAPI on the project's configured port and talks only to same-origin API endpoints. The distributable project also exposes a Streamlit UI and Windows launchers, while both interfaces use the same Python services and SQLite schema. No audio or video ingestion is implemented. Transcript text stays in the local SQLite database unless an operator explicitly configures an external LLM provider.

The backend is separated into parsing/normalization, extraction and model adapter, evidence verification, authorization, persistence/audit, and API layers. Pydantic models validate request and model data. SQLite is initialized on startup with indexed meeting/history/session tables. Passwords are PBKDF2-hashed; signed opaque session tokens are stored as hashes. Role checks happen on the server. Users can inspect source excerpts, modify generated content and topics, save drafts, approve, and export approved records. Reopen is an Admin-only audited transition. Offline extraction works without credentials. Optional LLM output is treated as untrusted and claims without exact transcript support are flagged, not accepted as facts.

Input is capped, previewable, decoded safely and parsed only as TXT, DOCX or SRT. The original content is retained alongside a cleaned representation. Unknown speakers remain unknown. Topic segmentation starts from explicit headings/paragraph structure and falls back to small consecutive line groups; topic boundaries are editable. Decisions/actions/questions are deterministic, rule-based candidates linked to real source lines; absence of an explicit owner/date is shown as `Unspecified`.

## Project structure

- `app/main.py`: FastAPI application, HTTP routes, static dashboard serving, lifecycle and auth wiring.
- `app/config.py`: environment-backed settings and size/timeout limits.
- `app/db.py`: SQLite connections, schema, initialization and transaction helpers.
- `app/auth.py`: password hashing, sessions, current-user dependency and role checks.
- `app/parsers.py`: TXT/DOCX/SRT decoding, validation, timestamp/speaker normalization.
- `app/analysis.py`: topic segmentation, extractive summaries, decisions/actions/questions, optional LLM and evidence validation.
- `app/schemas.py`: Pydantic request/response contracts.
- `app/service.py`: meeting workflow, permission-aware search, edits, approval and audit history.
- `app/exports.py`: approved Markdown, TXT, JSON and action CSV rendering.
- `app/static/`: responsive dashboard (HTML/CSS/JS), same-origin API client.
- `streamlit_app.py`: optional Streamlit local interface using the same store and workflows.
- `tests/`: pytest coverage for parser, extraction, evidence, access, lifecycle, search, exports and error handling.
- `samples/`: synthetic-only transcript examples.
- `docs/`: architecture/ER diagram, API and security/retention notes.
- `scripts/`: Windows setup and launch scripts.

## Design

Three distinct low-probability visual directions considered: (1) warm editorial field-notes, 0.06; (2) neon collaboration cockpit, 0.04; (3) quiet evidence ledger with restrained teal, 0.08. Chosen: **quiet evidence ledger**.

- **Design movement:** Swiss editorial information design, softened for a contemporary research notebook.
- **Core principles:** evidence is visible; status is legible; dense content stays calm; review remains deliberate.
- **Color philosophy:** warm paper and deep ink establish trust; muted sea-glass teal identifies verified evidence; amber denotes uncertainty and pending work; restrained red marks warnings.
- **Layout paradigm:** narrow persistent left rail, broad document workspace, and a contextual right evidence drawer; on small screens these become stacked, collapsible regions.
- **Signature elements:** slim evidence rails beside cited content; monospaced timestamp chips; numbered topic markers.
- **Interaction philosophy:** changes are explicit, drafts autosave only when requested, and approval is a distinct confirmation step. Evidence links open exact excerpts.
- **Animation:** short (120–180 ms) opacity/height transitions for drawers and status changes; no looping or motion that distracts from reading; respect reduced-motion settings.
- **Typography:** Inter/system sans-serif fallbacks for UI/body and DM Mono/system monospace for IDs, timestamps and metadata; large sentence-case editorial headings, restrained weights and generous line height. No third-party font request is required.
- **Brand essence:** an accountable meeting-notes workspace for teams who need to know not only what was written, but where it came from; precise, calm, inspectable.
- **Brand voice:** concise and transparent. Examples: “Start with the transcript. Keep every claim traceable.” “No owner was stated; this stays unspecified.”
- **Wordmark & logo:** a paired note-sheet glyph with a teal source-marker notch, followed by the lowercase wordmark `meetbrief`.
- **Signature brand color:** sea-glass teal (`#16877B`).

## Dependencies and operation

Python 3.11+; FastAPI, Uvicorn, Streamlit, Pydantic, python-docx, httpx and pytest. SQLite is standard library. The default analysis works offline. An optional OpenAI-compatible endpoint uses `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL`; prompts contain transcript text, so external processing is disclosed and opt-in. The project's browser dashboard is a Python app, not a separate paid frontend service. Keep provider credentials server-side. The local development server uses port 3000 in the managed Preview. The standalone local Windows launcher uses configurable local ports and SQLite data files.
