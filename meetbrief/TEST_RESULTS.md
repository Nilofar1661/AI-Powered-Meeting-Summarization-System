# Verification results

Final run from the project root in the provided sandbox on 2026-10-28:

```text
$ python3 -m pytest -q
.........................                                                [100%]
25 passed, 1 warning in 6.45s
```

Runtime: Python 3.12.3. The only warning is a third-party Starlette TestClient deprecation notice for `anyio.abc.BlockingPortal`; it is not a test failure.

The passing suite covers TXT/DOCX/SRT parsing, timestamp and speaker normalization, semantic-prefix preservation, malformed/empty/oversized inputs, extractive summaries, confirmed versus tentative decisions, action fields and `Unspecified`, evidence validation, exact repeated-point references, invalid-provider-response/timeout/HTTP-429 fallback, provider opt-in and input caps, HTTPS versus localhost cookie policy, CSRF, Admin/Editor/Reviewer/Viewer permissions, topic split/merge and overlap validation, approval/reopen gates, uploaded-TXT processing/evidence/edit/approval/search/export/audit, and approved-only Viewer history including non-empty CSV action text.

Additional checks completed successfully:

```text
python3 -m compileall -q app streamlit_app.py db_setup.py tests
node --check app/static/app.js
python3 -m json.tool manus-routes.json
```

Live HTTP checks returned `200` for `/`, `/api/health`, `/docs`, `/openapi.json`, and `/manus-routes.json` on the Preview listener (port 3000), and for `/`, `/api/health`, `/docs`, and `/openapi.json` on the documented local listener (port 8000). The health response confirmed `offline-extractive` mode. Architecture and ER diagrams rendered as PNG files. The project was not published; automatic publishing was disabled in the existing project configuration.
