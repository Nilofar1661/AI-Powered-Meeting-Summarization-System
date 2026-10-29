from tests.conftest import sign_in, csrf, make_draft


def test_topics_can_be_split_merged_and_cannot_overlap(client):
    token = sign_in(client)
    transcript = ("Topic: Design\n"
                  "Alice: The review identified two open questions.\n"
                  "Alice: We agreed to keep the current palette.\n"
                  "Topic: Delivery\n"
                  "Bob: Action item: Owner: Alice Chen, due 2026-10-30. Send the final specifications.\n"
                  "Bob: Could we add a dark mode icon?")
    draft = make_draft(client, token, transcript=transcript, title="Topic controls")
    meeting_id = draft["id"]
    processed = client.post(f"/api/meetings/{meeting_id}/process", data={"allow_external_ai":"false"}, headers=csrf(token))
    assert processed.status_code == 200
    topics = processed.json()["analysis"]["topics"]
    assert len(topics) == 2
    assert topics[0]["summary_claims"]

    split = client.post(f"/api/meetings/{meeting_id}/topics/{topics[0]['id']}/split", json={"at_line":3}, headers=csrf(token))
    assert split.status_code == 200, split.text
    split_topics = split.json()["analysis"]["topics"]
    assert len(split_topics) == 3
    assert split_topics[0]["end_line"] == 2
    assert split_topics[1]["start_line"] == 3

    merged = client.post(f"/api/meetings/{meeting_id}/topics/{split_topics[0]['id']}/merge",
                         json={"target_topic_id":split_topics[1]["id"]}, headers=csrf(token))
    assert merged.status_code == 200, merged.text
    merged_topics = merged.json()["analysis"]["topics"]
    assert len(merged_topics) == 2
    assert merged_topics[0]["start_line"] == 2 and merged_topics[0]["end_line"] == 3
    assert merged_topics[0]["summary_claims"]

    edited = merged.json()["analysis"]
    edited["topics"][1]["start_line"] = 3  # overlaps the preceding topic
    rejected = client.put(f"/api/meetings/{meeting_id}/topics", json={"topics":edited["topics"]}, headers=csrf(token))
    assert rejected.status_code == 422


def test_approval_rejects_owners_and_deadlines_not_in_source(client):
    token = sign_in(client)
    transcript = "Alex: The team completed the final review.\nAction item: Please send the release notes after the call."
    draft = make_draft(client, token, transcript=transcript, title="Owner evidence")
    meeting_id = draft["id"]
    processed = client.post(f"/api/meetings/{meeting_id}/process", data={"allow_external_ai":"false"}, headers=csrf(token))
    assert processed.status_code == 200
    analysis = processed.json()["analysis"]
    action = analysis["actions"][0]
    assert action["owner"] == "Unspecified" and action["due_date"] == "Unspecified"
    action["owner"] = "Invented Person"
    action["due_date"] = "2026-11-30"
    saved = client.put(f"/api/meetings/{meeting_id}/analysis", json={"analysis":analysis}, headers=csrf(token))
    assert saved.status_code == 200
    checked_action = saved.json()["analysis"]["actions"][0]
    assert checked_action["owner_supported"] is False
    assert checked_action["due_date_supported"] is False
    blocked = client.post(f"/api/meetings/{meeting_id}/approve", headers=csrf(token))
    assert blocked.status_code == 409
    analysis = saved.json()["analysis"]
    analysis["actions"][0]["owner"] = "Unspecified"
    analysis["actions"][0]["due_date"] = "Unspecified"
    reset = client.put(f"/api/meetings/{meeting_id}/analysis", json={"analysis":analysis}, headers=csrf(token))
    assert reset.status_code == 200
    approved = client.post(f"/api/meetings/{meeting_id}/approve", headers=csrf(token))
    assert approved.status_code == 200


def test_service_layer_also_denies_viewer_writes(client):
    token = sign_in(client)
    client.post("/api/admin/users", json={"username":"viewonly","password":"ViewerOnly123!","role":"Viewer"}, headers=csrf(token))
    viewer = client.__class__(client.app, base_url="https://testserver")
    from tests.conftest import sign_in as login
    login(viewer, "viewonly", "ViewerOnly123!")
    import pytest
    from fastapi import HTTPException
    from app.service import create_meeting
    with pytest.raises(HTTPException) as error:
        create_meeting("No access", "2026-10-28", "", "An approved transcript sentence.", None, {"id":2,"username":"viewonly","role":"Viewer"})
    assert error.value.status_code == 403
