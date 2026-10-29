from dataclasses import replace
from io import BytesIO
import pytest
from docx import Document
import app.parsers as parsers
from app.parsers import TranscriptError, extract_file_text, normalize_timestamp, parse_transcript


def test_txt_normalizes_timestamp_and_preserves_original_speaker_label():
    raw = "[2:09] Dr. Rivera: We approved the copy.\nA line without a label."
    lines = parse_transcript(raw, "notes.txt")
    assert lines[0]["timestamp"] == "00:02:09"
    assert lines[0]["speaker"] == "Dr. Rivera"
    assert lines[0]["original"] == "[2:09] Dr. Rivera: We approved the copy."
    assert lines[1]["speaker"] == "Unknown speaker"
    assert lines[1]["text"] == "A line without a label."


def test_semantic_prefixes_are_not_mistaken_for_people():
    lines = parse_transcript("Topic: Roadmap\nDecision: We decided to defer the launch.\nAction item: Owner: Lee Chen. Send the update.")
    assert lines[0]["text"] == "Topic: Roadmap"
    assert lines[0]["speaker"] == "Unknown speaker"
    assert lines[1]["text"].startswith("Decision:")
    assert lines[2]["text"].startswith("Action item:")


def test_srt_cues_keep_normalized_start_timestamps():
    source = "1\n00:00:03,500 --> 00:00:06,000\nSam: The build passed.\n\n2\n00:01:08,000 --> 00:01:10,000\nIt needs review."
    lines = parse_transcript(source, "meeting.srt")
    assert len(lines) == 2
    assert lines[0]["timestamp"] == "00:00:03.500"
    assert lines[0]["speaker"] == "Sam"
    assert lines[1]["timestamp"] == "00:01:08.000"
    assert lines[1]["speaker"] == "Unknown speaker"


def test_docx_parsing():
    document = Document()
    document.add_paragraph("Alex: We confirmed the test is complete.")
    content = BytesIO()
    document.save(content)
    text = extract_file_text("notes.docx", content.getvalue())
    assert "test is complete" in text
    assert parse_transcript(text)[0]["speaker"] == "Alex"


def test_empty_input_and_unsupported_files_are_actionable():
    with pytest.raises(TranscriptError, match="empty"):
        parse_transcript(" \n")
    with pytest.raises(TranscriptError, match="Unsupported file type"):
        extract_file_text("recording.mp4", b"video")
    with pytest.raises(TranscriptError, match="malformed"):
        extract_file_text("bad.docx", b"not a zip file")
    with pytest.raises(TranscriptError, match="empty"):
        extract_file_text("empty.txt", b"")


def test_large_text_is_rejected_before_processing(monkeypatch):
    monkeypatch.setattr(parsers, "settings", replace(parsers.settings, max_transcript_chars=10))
    with pytest.raises(TranscriptError, match="character limit"):
        parse_transcript("x" * 11)


def test_timestamp_validation():
    assert normalize_timestamp("2:03") == "00:02:03"
    assert normalize_timestamp("1:02:03,4") == "01:02:03.400"
    with pytest.raises(TranscriptError, match="out of range"):
        normalize_timestamp("00:61:02")
