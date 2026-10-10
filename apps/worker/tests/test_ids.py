import pytest

from yearbook_worker import ids


def test_roundtrip() -> None:
    raw = ids.new_id()
    text = ids.encode(raw)
    assert len(text) == 22
    assert "=" not in text and "+" not in text and "/" not in text
    assert ids.decode(text) == raw


def test_known_vector() -> None:
    assert ids.encode(bytes(16)) == "AAAAAAAAAAAAAAAAAAAAAA"
    assert ids.encode(bytes([255] * 16)) == "_____________________w"
    assert ids.decode("_____________________w") == bytes([255] * 16)


@pytest.mark.parametrize("bad", ["", "short", "AAAAAAAAAAAAAAAAAAAAAA=", "AAAAAAAAAAAAAAAAAAAAA!"])
def test_decode_rejects(bad: str) -> None:
    with pytest.raises(ValueError):
        ids.decode(bad)


def test_decode_rejects_non_canonical() -> None:
    # Last character carries 2 unused bits; a non-zero padding bit pattern is not canonical.
    with pytest.raises(ValueError):
        ids.decode("AAAAAAAAAAAAAAAAAAAAAB")


def test_encode_requires_16_bytes() -> None:
    with pytest.raises(ValueError):
        ids.encode(b"123")
