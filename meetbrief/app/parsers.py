"""Transcript parsing/normalization. Originals are retained separately in SQLite."""
from dataclasses import dataclass, asdict
from io import BytesIO
from pathlib import PurePath
import re
from docx import Document
from app.config import settings

class TranscriptError(ValueError):
    """A validation error suitable for returning to an upload form."""

@dataclass
class TranscriptLine:
    id: int
    text: str
    original: str
    timestamp: str | None = None
    speaker: str = "Unknown speaker"

    def to_dict(self) -> dict:
        return asdict(self)

_TIME = re.compile(r"^\s*\[?(\d{1,2}:\d{2}(?::\d{2})?(?:[,.]\d{1,3})?)\]?\s*(?:[-–|]\s*)?(.*)$")
_SRT_TIME = re.compile(r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})")
_SPEAKER = re.compile(r"^([^:\n]{1,60}):\s+(.+)$")


def normalize_timestamp(value: str) -> str:
    value = value.strip().replace(",", ".")
    core, dot, millis = value.partition(".")
    parts = [int(part) for part in core.split(":")]
    if len(parts) == 2:
        hours, minutes, seconds = 0, parts[0], parts[1]
    elif len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        raise TranscriptError(f"Timestamp is not in mm:ss or hh:mm:ss format: {value}")
    if minutes > 59 or seconds > 59:
        raise TranscriptError(f"Timestamp is out of range: {value}")
    normalized = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    if dot:
        normalized += "." + (millis + "000")[:3]
    return normalized


def _decode(data: bytes) -> str:
    if len(data) > settings.max_upload_bytes:
        raise TranscriptError(f"File is too large. Maximum upload size is {settings.max_upload_bytes // (1024*1024)} MB.")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return data.decode("cp1252")
        except UnicodeDecodeError as exc:
            raise TranscriptError("Unable to decode this file. Save it as UTF-8 text and retry.") from exc


def extract_file_text(filename: str, data: bytes) -> str:
    suffix = PurePath(filename or "").suffix.lower()
    if not data:
        raise TranscriptError("The uploaded file is empty.")
    if suffix in {".txt", ".srt"}:
        return _decode(data)
    if suffix == ".docx":
        try:
            doc = Document(BytesIO(data))
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception as exc:
            raise TranscriptError("This DOCX file is malformed or unreadable.") from exc
    raise TranscriptError("Unsupported file type. Please upload TXT, DOCX, or SRT. Recordings are not accepted.")


def _srt_to_lines(text: str) -> list[str]:
    cues = re.split(r"\n\s*\n", text.strip())
    lines: list[str] = []
    for cue in cues:
        cue_lines = [part.strip() for part in cue.splitlines() if part.strip()]
        if not cue_lines:
            continue
        timestamp = None
        content = []
        for cue_line in cue_lines:
            m = _SRT_TIME.search(cue_line)
            if m:
                timestamp = normalize_timestamp(m.group(1))
            elif not cue_line.isdigit():
                content.append(cue_line)
        if content:
            prefix = f"[{timestamp}] " if timestamp else ""
            lines.append(prefix + " ".join(content))
    return lines


def parse_transcript(text: str, filename: str | None = None) -> list[dict]:
    if not isinstance(text, str) or not text.strip():
        raise TranscriptError("Transcript is empty. Paste notes or upload a transcript first.")
    if len(text) > settings.max_transcript_chars:
        raise TranscriptError(f"Transcript exceeds the {settings.max_transcript_chars:,}-character limit. Split it into smaller meetings.")
    if filename and PurePath(filename).suffix.lower() == ".srt":
        raw_lines = _srt_to_lines(text)
    else:
        raw_lines = text.splitlines()
    result: list[TranscriptLine] = []
    for raw in raw_lines:
        original = raw.rstrip("\r\n")
        clean = original.strip()
        if not clean:
            continue
        timestamp = None
        match = _TIME.match(clean)
        if match:
            try:
                timestamp = normalize_timestamp(match.group(1))
                clean = match.group(2).strip()
            except TranscriptError:
                # Preserve an invalid-looking timestamp as transcript text rather than dropping it.
                pass
        speaker = "Unknown speaker"
        speaker_match = _SPEAKER.match(clean)
        if speaker_match:
            candidate = speaker_match.group(1).strip()
            semantic_prefixes = {"topic", "agenda", "section", "decision", "action", "action item", "question", "todo", "note", "resolution", "owner", "due", "due date"}
            # Keep explicit section/action markers intact; only source-provided speaker labels are normalized.
            if candidate and candidate.casefold() not in semantic_prefixes:
                speaker = candidate
                clean = speaker_match.group(2).strip()
        if clean:
            result.append(TranscriptLine(len(result) + 1, clean, original, timestamp, speaker))
    if not result:
        raise TranscriptError("No readable transcript lines were found.")
    return [line.to_dict() for line in result]
