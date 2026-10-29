"""Render approved meeting data into portable formats."""
import csv
import io
import json
from fastapi import HTTPException


def export_content(meeting: dict, fmt: str) -> tuple[str, str, str]:
    if meeting.get("status") != "approved":
        raise HTTPException(403, "Only approved summaries can be exported.")
    analysis = meeting.get("analysis", {})
    if fmt == "json":
        content = json.dumps({"title": meeting["title"], "date": meeting["meeting_date"], "status": meeting["status"], "summary_claims": analysis.get("summary_claims", []), "topics": analysis.get("topics", []), "repeated_points": analysis.get("repeated_points", []), "decisions": analysis.get("decisions", []), "actions": analysis.get("actions", []), "unresolved_questions": analysis.get("questions", [])}, ensure_ascii=False, indent=2)
        return content, "application/json; charset=utf-8", "json"
    if fmt == "csv":
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=["action", "owner", "due_date", "status", "evidence_line_ids"], extrasaction="ignore")
        writer.writeheader()
        for action in analysis.get("actions", []):
            writer.writerow({"action": action.get("text", ""), "owner": action.get("owner", "Unspecified"),
                             "due_date": action.get("due_date", "Unspecified"), "status": action.get("status", "Open"),
                             "evidence_line_ids": ",".join(map(str, action.get("evidence_line_ids", [])))})
        return stream.getvalue(), "text/csv; charset=utf-8", "actions.csv"
    lines = [f"# {meeting['title']}", f"Date: {meeting['meeting_date']}", "", "## Summary"]
    for item in analysis.get("summary_claims", []):
        refs = ", ".join(f"line {value}" for value in item.get("evidence_line_ids", [])) or "Unspecified"
        lines.append(f"- {item['text']}  _(Evidence: {refs})_")
    lines += ["", "## Topic summaries"]
    for topic in analysis.get("topics", []):
        lines.append(f"### {topic.get('name', 'Topic')}")
        for claim in topic.get("summary_claims", []):
            refs = ", ".join(f"line {value}" for value in claim.get("evidence_line_ids", [])) or "Unspecified"
            lines.append(f"- {claim['text']}  _(Evidence: {refs})_")
    lines += ["", "## Potential repeated points"]
    for point in analysis.get("repeated_points", []):
        refs = ", ".join(f"line {value}" for value in point.get("evidence_line_ids", [])) or "Unspecified"
        lines.append(f"- {point['text']} ({point.get('occurrences', 0)} exact occurrences; evidence: {refs})")
    lines += ["", "## Decisions"]
    for item in analysis.get("decisions", []):
        lines.append(f"- **{item.get('status','Decision')}:** {item['text']} (evidence lines: {', '.join(map(str,item.get('evidence_line_ids',[]))) or 'Unspecified'})")
    lines += ["", "## Action items"]
    for item in analysis.get("actions", []):
        lines.append(f"- {item['text']} — Owner: {item.get('owner','Unspecified')}; Due: {item.get('due_date','Unspecified')} (evidence lines: {', '.join(map(str,item.get('evidence_line_ids',[]))) or 'Unspecified'})")
    lines += ["", "## Unresolved questions"]
    for item in analysis.get("questions", []):
        lines.append(f"- {item['text']} (evidence lines: {', '.join(map(str,item.get('evidence_line_ids',[]))) or 'Unspecified'})")
    lines += ["", "Generated with Meetbrief. Human-approved summary; AI output is not a guaranteed record."]
    content = "\n".join(lines)
    if fmt == "md":
        return content, "text/markdown; charset=utf-8", "summary.md"
    if fmt == "txt":
        return content.replace("# ", "").replace("## ", ""), "text/plain; charset=utf-8", "summary.txt"
    raise HTTPException(404, "Format not found. Use md, txt, json, or csv.")
