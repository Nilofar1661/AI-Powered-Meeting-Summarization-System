"""Evidence-first analysis with an offline extractive mode and optional LLM summary."""
import json
import re
from collections import Counter
from typing import Any
import httpx
from app.config import settings

ACTION_RE = re.compile(r"\b(?:action\s*item\b|action\s*:|todo\b|to-do\b|follow up\b|follow-up\b|will\s+[a-z]+\b|assigned to\b|owner\s*:|responsible for\b)", re.I)
DECISION_RE = re.compile(r"\b(decision\s*:|decided\s+to|we decided|agreed\s+to|approved\s+the|confirmed\s+that|the team agreed)\b", re.I)
TENTATIVE_RE = re.compile(r"\b(maybe|perhaps|might|could|consider|proposed?|tentative|idea\s*:|should)\b", re.I)
QUESTION_RE = re.compile(r"\?|\b(open question|unresolved|unclear whether|need to confirm)\b", re.I)
OWNER_RE = re.compile(r"\b(?:owner|assigned to)\s*[:=]?\s+([A-Z][\w-]*(?:\s+[A-Z][\w-]*)?)\b", re.I)
DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}(?:,\s*\d{4})?)\b", re.I)
DUE_CONTEXT_RE = re.compile(r"\b(?:due|by|before|deadline|no later than)\b", re.I)


def _token_set(text: str) -> set[str]:
    return {word.lower() for word in re.findall(r"[A-Za-z0-9']+", text) if len(word) > 2}


def is_supported(claim: str, evidence_text: str) -> bool:
    if not claim.strip() or not evidence_text.strip():
        return False
    if claim.strip().casefold() in evidence_text.casefold():
        return True
    a, b = _token_set(claim), _token_set(evidence_text)
    if not a:
        return False
    # Conservative threshold: a few matching words must not legitimize appended claims.
    return len(a & b) / len(a) >= 0.85


def _topics(lines: list[dict]) -> list[dict]:
    groups: list[dict] = []
    current: list[dict] = []
    current_name = "Discussion"
    start = None
    for line in lines:
        text = line["text"]
        head = re.match(r"^(?:topic|agenda|section)\s*[:#-]\s*(.+)$", text, re.I)
        if head:
            if current:
                groups.append(_make_topic(len(groups) + 1, current_name, current))
            current, current_name, start = [], head.group(1).strip()[:80], line
            continue
        if not current:
            current_name = "Discussion"
        current.append(line)
        if len(current) >= 7:
            groups.append(_make_topic(len(groups) + 1, current_name, current))
            current = []
            current_name = "Discussion"
    if current:
        groups.append(_make_topic(len(groups) + 1, current_name, current))
    if not groups:
        groups = [_make_topic(1, "Discussion", lines)]
    # Give unheaded group names a grounded phrase from their first source line.
    for topic in groups:
        if topic["name"] == "Discussion":
            topic["name"] = topic["lines"][0]["text"][:52].rstrip(" .,;:") or "Discussion"
    return groups


def _make_topic(index: int, name: str, lines: list[dict]) -> dict:
    return {"id": f"topic-{index}", "name": name, "start_line": lines[0]["id"], "end_line": lines[-1]["id"], "lines": lines}


def _summary_claims(lines: list[dict], limit: int = 5) -> list[dict]:
    # Prefer substantive sentences; claims remain direct transcript excerpts in fallback mode.
    selected = sorted(lines, key=lambda item: (len(_token_set(item["text"])), len(item["text"])), reverse=True)
    claims = []
    seen = set()
    for line in selected:
        text = line["text"].strip()
        key = text.casefold()
        if key in seen or len(_token_set(text)) < 3:
            continue
        seen.add(key)
        claims.append({"text": text, "evidence_line_ids": [line["id"]], "supported": True, "source": "extractive"})
        if len(claims) >= limit:
            break
    return claims


def summarize_lines(lines: list[dict], limit: int = 3) -> list[dict]:
    """Create a small topic recap from source sentences and their real line IDs."""
    return _summary_claims(lines, limit)


def _extract_decisions(lines: list[dict]) -> list[dict]:
    results = []
    for line in lines:
        text = line["text"]
        if DECISION_RE.search(text) or TENTATIVE_RE.search(text):
            tentative = bool(TENTATIVE_RE.search(text)) and not bool(DECISION_RE.search(text))
            results.append({"id": f"decision-{line['id']}", "text": text, "status": "Tentative idea" if tentative else "Confirmed decision", "evidence_line_ids": [line["id"]], "supported": True})
    return results


def _extract_actions(lines: list[dict]) -> list[dict]:
    results = []
    for line in lines:
        text = line["text"]
        if ACTION_RE.search(text):
            owner_match, due_match = OWNER_RE.search(text), DATE_RE.search(text)
            if due_match and not DUE_CONTEXT_RE.search(text[max(0, due_match.start() - 35):due_match.start()]):
                due_match = None
            owner = owner_match.group(1) if owner_match else "Unspecified"
            due_date = due_match.group(1) if due_match else "Unspecified"
            results.append({"id": f"action-{line['id']}", "text": text, "owner": owner, "due_date": due_date,
                            "owner_supported": owner == "Unspecified" or owner.casefold() in text.casefold(),
                            "due_date_supported": due_date == "Unspecified" or due_date.casefold() in text.casefold(),
                            "status": "Open", "evidence_line_ids": [line["id"]], "supported": True})
    return results


def _extract_questions(lines: list[dict]) -> list[dict]:
    return [{"id": f"question-{line['id']}", "text": line["text"], "evidence_line_ids": [line["id"]], "supported": True} for line in lines if QUESTION_RE.search(line["text"])]


def _repeated_points(lines: list[dict]) -> list[dict]:
    """Detect exact normalized repeats in linear time; never merge or discard the source."""
    groups: dict[str, list[dict]] = {}
    for line in lines:
        normalized = " ".join(re.findall(r"[a-z0-9']+", line["text"].casefold()))
        if len(_token_set(normalized)) >= 4:
            groups.setdefault(normalized, []).append(line)
    repeated = []
    for group in groups.values():
        if len(group) > 1:
            ids = [line["id"] for line in group]
            repeated.append({"id": f"repeat-{ids[0]}", "text": group[0]["text"], "occurrences": len(ids),
                             "evidence_line_ids": ids, "kind": "Exact normalized wording", "supported": True})
    return repeated


def _llm_claims(lines: list[dict], fallback: list[dict], allow_external_ai: bool = False) -> tuple[list[dict], str]:
    if not settings.llm_enabled or not allow_external_ai:
        return fallback, "offline-extractive"
    source = "\n".join(f"[{line['id']}] {line['text']}" for line in lines)
    if len(source) > settings.llm_max_chars:
        return fallback, "offline-extractive (LLM input limit exceeded)"
    prompt = ("Summarize this meeting in 3-5 concise claims. Use only facts stated in the transcript. "
              "Return JSON only: {\"claims\":[{\"text\":\"...\",\"evidence_line_ids\":[1]}]}. "
              "Each claim must cite one or more exact source line IDs. Do not create owners, dates, names, or decisions.\n\n" + source)
    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    try:
        with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
            response = client.post(url, headers={"Authorization": f"Bearer {settings.llm_api_key}"}, json={
                "model": settings.llm_model,
                "messages": [{"role": "system", "content": "You are a conservative transcript summarizer. Output valid JSON."}, {"role": "user", "content": prompt}],
                "temperature": 0.1,
            })
            response.raise_for_status()
            body = response.json()
            content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
            if isinstance(content, list):
                content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
            parsed = json.loads(content)
            claims = parsed.get("claims")
            if not isinstance(claims, list) or not claims:
                raise ValueError("The model returned no claims.")
            index = {line["id"]: line for line in lines}
            checked = []
            for claim in claims[:7]:
                if not isinstance(claim, dict) or not isinstance(claim.get("text"), str):
                    continue
                ids = [int(value) for value in claim.get("evidence_line_ids", []) if str(value).isdigit() and int(value) in index]
                source_text = " ".join(index[value]["text"] for value in ids)
                supported = bool(ids) and is_supported(claim["text"], source_text)
                checked.append({"text": claim["text"], "evidence_line_ids": ids, "supported": supported, "source": "llm"})
            if not checked:
                raise ValueError("The model returned no usable claims.")
            return checked, "configured-llm"
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        detail = f"provider rate limit: HTTP {status}" if status == 429 else f"provider HTTP {status}"
        return [{**item, "source": "extractive"} for item in fallback], f"offline-extractive ({detail}; using local fallback)"
    except (httpx.TimeoutException, httpx.HTTPError, ValueError, KeyError, TypeError, IndexError, json.JSONDecodeError) as exc:
        # Never fail processing just because a provider timed out or returned malformed data.
        return [{**item, "source": "extractive"} for item in fallback], f"offline-extractive (LLM unavailable: {type(exc).__name__})"


def analyze(lines: list[dict], allow_external_ai: bool = False) -> dict[str, Any]:
    if not lines:
        raise ValueError("Cannot analyze an empty transcript.")
    fallback_claims = _summary_claims(lines)
    claims, mode = _llm_claims(lines, fallback_claims, allow_external_ai)
    topics = _topics(lines)
    for topic in topics:
        topic["summary_claims"] = _summary_claims(topic["lines"], 3)
        topic["lines"] = [{"id": line["id"], "text": line["text"], "timestamp": line["timestamp"], "speaker": line["speaker"]} for line in topic["lines"]]
    source_index = {line["id"]: line for line in lines}
    return {
        "summary_claims": claims,
        "topics": topics,
        "decisions": _extract_decisions(lines),
        "actions": _extract_actions(lines),
        "questions": _extract_questions(lines),
        "repeated_points": _repeated_points(lines),
        "ai_mode": mode,
        "limitations": "Extractive fallback selects transcript sentences; it may omit context. Configured LLM text is validated against cited transcript lines but still requires human review.",
        "unsupported_count": sum(1 for claim in claims if not claim["supported"]),
        "source_line_count": len(source_index),
    }


def revalidate_analysis(analysis: dict, lines: list[dict]) -> dict:
    """Recompute support flags against original source, including after user edits."""
    index = {line["id"]: line for line in lines}
    result = dict(analysis)
    for section in ("summary_claims", "decisions", "actions", "questions"):
        checked = []
        for item in result.get(section, []):
            item = dict(item)
            evidence_ids = [int(value) for value in item.get("evidence_line_ids", []) if str(value).isdigit() and int(value) in index]
            evidence = " ".join(index[value]["text"] for value in evidence_ids)
            claim = item.get("text", "")
            # Rule-based action/decision/question rows are quoted source lines. Edited versions need support too.
            item["evidence_line_ids"] = evidence_ids
            item["supported"] = bool(evidence_ids) and is_supported(claim, evidence)
            if section == "actions":
                owner = str(item.get("owner", "Unspecified"))
                due_date = str(item.get("due_date", "Unspecified"))
                item["owner_supported"] = owner == "Unspecified" or (bool(evidence_ids) and owner.casefold() in evidence.casefold())
                item["due_date_supported"] = due_date == "Unspecified" or (bool(evidence_ids) and due_date.casefold() in evidence.casefold())
            checked.append(item)
        result[section] = checked
    result["unsupported_count"] = sum(1 for item in result.get("summary_claims", []) if not item.get("supported"))
    return result
