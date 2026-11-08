"""Проверка вложений без базы."""
import pytest

from app.services.attachments import MAX_FILES, MAX_SIZE, check_files, detect
from app.services.intake import IntakeError

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20
JPG = b"\xff\xd8\xff\xe0" + b"0" * 20
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"0" * 20


def test_detect_by_content():
    assert detect(PNG) == ("image/png", "png")
    assert detect(JPG) == ("image/jpeg", "jpg")
    assert detect(WEBP) == ("image/webp", "webp")
    assert detect(b"<html>not an image</html>") is None
    assert detect(b"GIF89a....") is None


def test_name_cannot_fake_type():
    with pytest.raises(IntakeError):
        check_files([("photo.jpg", b"MZ\x90\x00 executable")])


def test_valid_files_pass():
    got = check_files([("a.png", PNG), ("b.jpg", JPG)])
    assert [g.ext for g in got] == ["png", "jpg"]


def test_too_many_files():
    with pytest.raises(IntakeError):
        check_files([("a.png", PNG)] * (MAX_FILES + 1))


def test_too_big_and_empty():
    with pytest.raises(IntakeError):
        check_files([("a.png", PNG + b"0" * MAX_SIZE)])
    with pytest.raises(IntakeError):
        check_files([("a.png", b"")])


def test_name_is_sanitized():
    got = check_files([("../../etc/pass wd<>.png", PNG)])
    assert "/" not in got[0].name and "<" not in got[0].name
