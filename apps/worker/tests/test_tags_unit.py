"""Caption → tags and OCR → words, pure string processing."""

from __future__ import annotations

from yearbook_worker.stages.tags import extract_caption_tags, extract_ocr_words

CAPTION = (
    "The image shows a man and a woman standing in front of an American flag. They are both "
    "wearing blue spacesuits with various patches. The woman has long dark hair and is smiling "
    "at the camera, the Birthday-Cake on the table has candles."
)


def test_caption_tags_drop_stopwords_and_scaffolding() -> None:
    tags = extract_caption_tags(CAPTION)
    assert tags[:4] == ["man", "woman", "standing", "american"]
    for word in ("the", "image", "shows", "front", "camera", "and", "has"):
        assert word not in tags
    assert "spacesuits" in tags and "birthday-cake" in tags
    assert len(tags) == len(set(tags))


def test_caption_tags_are_lowercase_unicode_aware() -> None:
    tags = extract_caption_tags("Ein Mädchen mit Luftballons vor der Kirche. Schöne Straße!")
    assert tags == [
        "ein", "mädchen", "mit", "luftballons", "vor", "der", "kirche", "schöne", "straße",
    ]  # fmt: skip


def test_caption_tags_limit_and_min_length() -> None:
    assert extract_caption_tags("ox ax a an it", limit=5) == []
    many = " ".join(f"tag{chr(97 + i // 26)}{chr(97 + i % 26)}" for i in range(100))
    assert len(extract_caption_tags(many, limit=10)) == 10


def test_ocr_words() -> None:
    words = extract_ocr_words("NASA 2024 Gate B12 ok Willkommen!")
    assert words == ["nasa", "2024", "gate", "b12", "willkommen"]
    assert extract_ocr_words("") == []
    assert extract_ocr_words("12 34 56") == []  # short numbers are noise
