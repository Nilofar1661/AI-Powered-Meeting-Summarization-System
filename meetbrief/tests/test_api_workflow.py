import csv
import io
from tests.conftest import sign_in, csrf, make_draft


def test_upload_process_evidence_edit_approve_search_export_and_audit(client):
    token = sign_in(client)
    transcript = ("Topic: Release readiness\n"
                  "[00:00:18] Morgan: The staging checklist is complete, and the accessibility review found two contrast issues.\n"
                  "[00:01:05] Unknown speaker: We agreed to keep the release date as October 31, provided those contrast fixes pass review.\n"
                  "[00:02:12] Action: Owner: Priya Shah. Fix the two contrast issues by October 29, 2026.\n"
                  "Topic: Open items\n"
                  "[00:08:42] Unknown speaker: Do we have confirmation from the payment provider about test credentials?")
    uploaded = {"file": ("launch_review.txt", transcript.encode("utf-8"), "text/plain")}
    preview = client.post("/api/meetings/preview", files=uploaded, headers=csrf(token))
    assert preview.status_code == 200
    assert preview.json()["line_count"] == 6
    meeting_response = client.post("/api/meetings", data={"title": "Launch review", "meeting_date": "2026-10-28"},
                                   files={"file": ("launch_review.txt", transcript.encode("utf-8"), "text/plain")}, headers=csrf(token))
    assert meeting_response.status_code == 201, meeting_response.text
    meeting = meeting_response.json()
    meeting_id = meeting["id"]
    processed = client.post(f"/api/meetings/{meeting_id}/process", data={"allow_external_ai": "false"}, headers=csrf(token))
    assert processed.status_code == 200, processed.text
    data = processed.json()
    assert data["status"] == "processed"
    assert data["analysis"]["summary_claims"]
    evidence_id = data["analysis"]["summary_claims"][0]["evidence_line_ids"][0]
    evidence = client.get(f"/api/meetings/{meeting_id}/evidence/{evidence_id}")
    assert evidence.status_code == 200
    assert evidence.json()["text"]
    assert evidence.json()["line_id"] == evidence_id

    analysis = data["analysis"]
    original_claim = analysis["summary_claims"][0]["text"]
    analysis["summary_claims"][0]["text"] = original_claim + " Unstated moon base confirmed."
    unsaved = client.put(f"/api/meetings/{meeting_id}/analysis", json={"analysis": analysis}, headers=csrf(token))
    assert unsaved.status_code == 200
    assert unsaved.json()["analysis"]["summary_claims"][0]["supported"] is False
    blocked = client.post(f"/api/meetings/{meeting_id}/approve", headers=csrf(token))
    assert blocked.status_code == 409

    analysis = unsaved.json()["analysis"]
    analysis["summary_claims"][0]["text"] = original_claim
    saved = client.put(f"/api/meetings/{meeting_id}/analysis", json={"analysis": analysis}, headers=csrf(token))
    assert saved.status_code == 200
    approved = client.post(f"/api/meetings/{meeting_id}/approve", headers=csrf(token))
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    search = client.get("/api/meetings", params={"q": "Launch review", "status": "approved"})
    assert search.status_code == 200
    assert len(search.json()) == 1
    assert search.json()[0]["id"] == meeting_id
    md = client.get(f"/api/meetings/{meeting_id}/export/md")
    txt = client.get(f"/api/meetings/{meeting_id}/export/txt")
    js = client.get(f"/api/meetings/{meeting_id}/export/json")
    action_csv = client.get(f"/api/meetings/{meeting_id}/export/csv")
    assert md.status_code == txt.status_code == js.status_code == action_csv.status_code == 200
    assert "Evidence" in md.text
    assert '"summary_claims"' in js.text
    assert "action,owner,due_date" in action_csv.text
    rows = list(csv.DictReader(io.StringIO(action_csv.text)))
    assert rows[0]["owner"] == "Priya Shah"
    assert "Fix the two contrast issues" in rows[0]["action"]
    history = client.get(f"/api/meetings/{meeting_id}/history")
    assert history.status_code == 200
    assert any("Approved" in item["action"] for item in history.json())


def test_roles_hide_drafts_and_only_admin_can_reopen(client):
    admin_token = sign_in(client)
    user = client.post("/api/admin/users", json={"username": "readonly", "password": "ViewerPass123!", "role": "Viewer"}, headers=csrf(admin_token))
    assert user.status_code == 201
    editor = client.post("/api/admin/users", json={"username": "reviewer", "password": "EditorPass123!", "role": "Editor/Reviewer"}, headers=csrf(admin_token))
    assert editor.status_code == 201
    draft = make_draft(client, admin_token)

    viewer_client = client.__class__(client.app, base_url="https://testserver")
    viewer_token = sign_in(viewer_client, "readonly", "ViewerPass123!")
    assert viewer_client.get("/api/meetings").json() == []
    assert viewer_client.get(f"/api/meetings/{draft['id']}").status_code == 404
    assert viewer_client.post(f"/api/meetings/{draft['id']}/process", data={"allow_external_ai":"false"}, headers=csrf(viewer_token)).status_code == 403

    process = client.post(f"/api/meetings/{draft['id']}/process", data={"allow_external_ai":"false"}, headers=csrf(admin_token))
    assert process.status_code == 200
    approval = client.post(f"/api/meetings/{draft['id']}/approve", headers=csrf(admin_token))
    assert approval.status_code == 200
    editor_client = client.__class__(client.app, base_url="https://testserver")
    editor_token = sign_in(editor_client, "reviewer", "EditorPass123!")
    reviewer_draft = make_draft(editor_client, editor_token, title="Editor approval")
    reviewer_process = editor_client.post(f"/api/meetings/{reviewer_draft['id']}/process", data={"allow_external_ai":"false"}, headers=csrf(editor_token))
    assert reviewer_process.status_code == 200
    reviewer_approval = editor_client.post(f"/api/meetings/{reviewer_draft['id']}/approve", headers=csrf(editor_token))
    assert reviewer_approval.status_code == 200
    assert editor_client.post(f"/api/meetings/{draft['id']}/reopen", headers=csrf(editor_token)).status_code == 403
    assert editor_client.put(f"/api/meetings/{draft['id']}/analysis", json={"analysis": approval.json()["analysis"]}, headers=csrf(editor_token)).status_code == 409
    visible = viewer_client.get("/api/meetings")
    assert len(visible.json()) == 2
    assert all(item["status"] == "approved" for item in visible.json())
    assert {item["id"] for item in visible.json()} == {draft["id"], reviewer_draft["id"]}
    detail = viewer_client.get(f"/api/meetings/{draft['id']}")
    assert detail.status_code == 200
    assert "cleaned_lines" not in detail.json()
    assert viewer_client.get(f"/api/meetings/{draft['id']}/export/md").status_code == 200

    assert client.post(f"/api/meetings/{draft['id']}/reopen", headers=csrf(admin_token)).status_code == 200
    assert client.get(f"/api/meetings/{draft['id']}/export/json").status_code == 403
    remaining_viewer_records = viewer_client.get("/api/meetings").json()
    assert len(remaining_viewer_records) == 1
    assert remaining_viewer_records[0]["id"] == reviewer_draft["id"]
    assert viewer_client.get(f"/api/meetings/{draft['id']}").status_code == 404


def test_empty_upload_and_invalid_file_return_validation_errors(client):
    token = sign_in(client)
    empty = client.post("/api/meetings/preview", data={"transcript": "  "}, headers=csrf(token))
    assert empty.status_code == 422
    unsupported = client.post("/api/meetings/preview", files={"file": ("recording.mp4", b"no", "video/mp4")}, headers=csrf(token))
    assert unsupported.status_code == 422
    malformed = client.post("/api/meetings/preview", files={"file": ("broken.docx", b"not-docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}, headers=csrf(token))
    assert malformed.status_code == 422


def test_csrf_required_and_approved_summary_cannot_be_exported_as_draft(client):
    token = sign_in(client)
    meeting = make_draft(client, token)
    assert client.post(f"/api/meetings/{meeting['id']}/process", data={"allow_external_ai":"false"}).status_code == 403
    assert client.get(f"/api/meetings/{meeting['id']}/export/json").status_code == 403


def test_search_filters_dates_and_missing_meeting_is_404(client):
    token = sign_in(client)
    make_draft(client, token, title="Planning notes")
    assert len(client.get("/api/meetings", params={"q":"Planning"}).json()) == 1
    assert client.get("/api/meetings", params={"date_from":"2026-10-29"}).json() == []
    assert client.get("/api/meetings/does-not-exist").status_code == 404


def test_cookie_policy_supports_https_preview_and_http_localhost(client, monkeypatch):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    import app.main as main_module

    preview_login = client.post("/api/auth/login", json={"username":"admin", "password":"ChangeMe123!"})
    assert preview_login.status_code == 200
    preview_cookie = preview_login.headers["set-cookie"].casefold()
    assert "samesite=none" in preview_cookie and "secure" in preview_cookie

    monkeypatch.setattr(main_module, "settings", replace(main_module.settings, cookie_secure=False))
    with TestClient(client.app, base_url="http://testserver") as local_client:
        local_login = local_client.post("/api/auth/login", json={"username":"admin", "password":"ChangeMe123!"})
        assert local_login.status_code == 200
        local_cookie = local_login.headers["set-cookie"].casefold()
        assert "samesite=lax" in local_cookie
        assert "secure" not in local_cookie
        assert local_client.get("/api/auth/me").status_code == 200
