from dataclasses import replace
import httpx
import pytest
import app.analysis as analysis
from app.parsers import parse_transcript

TRANSCRIPT = """Jordan: We decided to keep the October 30 release date.
Action item: Owner: Casey Lee, due 2026-10-29. Publish release notes.
Action item: Please check the staging environment after the call.
Jordan: We should consider a weekend support rotation, but this is only an idea.
Unknown speaker: Is the mobile build included?"""


def test_extracts_grounded_summary_decisions_actions_and_questions():
    lines = parse_transcript(TRANSCRIPT)
    result = analysis.analyze(lines)
    assert result["summary_claims"]
    assert all(c["supported"] and c["evidence_line_ids"] for c in result["summary_claims"])
    assert any(d["status"] == "Confirmed decision" for d in result["decisions"])
    assert any(d["status"] == "Tentative idea" for d in result["decisions"])
    assert any(a["owner"] == "Casey Lee" and a["due_date"] == "2026-10-29" for a in result["actions"])
    assert any(a["owner"] == "Unspecified" and a["due_date"] == "Unspecified" for a in result["actions"])
    assert any("mobile build" in q["text"] for q in result["questions"])
    assert result["ai_mode"] == "offline-extractive"


def test_evidence_support_flags_unsupported_edits_and_bad_line_ids():
    lines = parse_transcript("Morgan: The deadline is Friday.")
    draft = {"summary_claims": [{"text": "The deadline is Friday.", "evidence_line_ids": [1]}],
             "actions": [{"text": "The deadline is Friday.", "owner": "Alice", "due_date": "Unspecified", "evidence_line_ids": [1]}]}
    checked = analysis.revalidate_analysis(draft, lines)
    assert checked["summary_claims"][0]["supported"] is True
    assert checked["actions"][0]["owner_supported"] is False
    assert checked["actions"][0]["evidence_line_ids"] == [1]
    forged = analysis.revalidate_analysis({"summary_claims": [{"text": "A moon colony is confirmed.", "evidence_line_ids": [99]}]}, lines)
    assert forged["summary_claims"][0]["supported"] is False
    assert forged["unsupported_count"] == 1


def test_empty_analysis_fails_clearly():
    with pytest.raises(ValueError, match="empty transcript"):
        analysis.analyze([])


def test_llm_timeout_falls_back_to_extractive(monkeypatch):
    monkeypatch.setattr(analysis, "settings", replace(analysis.settings, llm_base_url="https://provider.invalid/v1", llm_api_key="secret", llm_model="sample-model"))
    class TimeoutClient:
        def __init__(self, timeout): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def post(self, *args, **kwargs): raise httpx.TimeoutException("request timed out")
    monkeypatch.setattr(analysis.httpx, "Client", TimeoutClient)
    result = analysis.analyze(parse_transcript("Alex: The migration completed on Friday."), allow_external_ai=True)
    assert result["summary_claims"]
    assert result["summary_claims"][0]["supported"]
    assert "offline-extractive" in result["ai_mode"]
    assert "TimeoutException" in result["ai_mode"]


def test_invalid_llm_response_falls_back(monkeypatch):
    monkeypatch.setattr(analysis, "settings", replace(analysis.settings, llm_base_url="https://provider.invalid/v1", llm_api_key="secret", llm_model="sample-model"))
    class FakeResponse:
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": "not-json"}}]}
    class FakeClient:
        def __init__(self, timeout): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def post(self, *args, **kwargs): return FakeResponse()
    monkeypatch.setattr(analysis.httpx, "Client", FakeClient)
    result = analysis.analyze(parse_transcript("Alex: The migration completed on Friday."), allow_external_ai=True)
    assert "offline-extractive" in result["ai_mode"]
    assert result["summary_claims"][0]["supported"]


def test_provider_is_not_called_without_explicit_opt_in(monkeypatch):
    monkeypatch.setattr(analysis, "settings", replace(analysis.settings, llm_base_url="https://provider.invalid/v1", llm_api_key="secret", llm_model="sample-model"))
    def must_not_call(*args, **kwargs):
        raise AssertionError("Provider must not be called without consent")
    monkeypatch.setattr(analysis.httpx, "Client", must_not_call)
    result = analysis.analyze(parse_transcript("Alex: The migration completed on Friday."))
    assert result["ai_mode"] == "offline-extractive"


def test_oversized_provider_prompt_falls_back_without_sending(monkeypatch):
    monkeypatch.setattr(analysis, "settings", replace(analysis.settings, llm_base_url="https://provider.invalid/v1", llm_api_key="secret", llm_model="sample-model", llm_max_chars=20))
    def must_not_call(*args, **kwargs):
        raise AssertionError("Oversized transcript must remain local")
    monkeypatch.setattr(analysis.httpx, "Client", must_not_call)
    result = analysis.analyze(parse_transcript("Alex: The migration completed on Friday and the staging checklist is ready."), allow_external_ai=True)
    assert result["summary_claims"]
    assert "input limit exceeded" in result["ai_mode"]


def test_exact_repeated_points_keep_all_source_line_ids():
    lines = parse_transcript("Alex: The launch checklist needs a complete final review.\nMorgan: the launch checklist needs a complete final review!")
    result = analysis.analyze(lines)
    assert len(result["repeated_points"]) == 1
    point = result["repeated_points"][0]
    assert point["occurrences"] == 2
    assert point["evidence_line_ids"] == [1, 2]
    assert point["supported"] is True


def test_provider_rate_limit_has_clear_local_fallback_status(monkeypatch):
    monkeypatch.setattr(analysis, "settings", replace(analysis.settings, llm_base_url="https://provider.invalid/v1", llm_api_key="secret", llm_model="sample-model"))
    class RateLimitedResponse:
        def raise_for_status(self):
            request = httpx.Request("POST", "https://provider.invalid/v1/chat/completions")
            response = httpx.Response(429, request=request)
            raise httpx.HTTPStatusError("rate limited", request=request, response=response)
    class FakeClient:
        def __init__(self, timeout): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def post(self, *args, **kwargs): return RateLimitedResponse()
    monkeypatch.setattr(analysis.httpx, "Client", FakeClient)
    result = analysis.analyze(parse_transcript("Alex: The migration completed on Friday."), allow_external_ai=True)
    assert "provider rate limit: HTTP 429" in result["ai_mode"]
    assert result["summary_claims"][0]["supported"] is True
