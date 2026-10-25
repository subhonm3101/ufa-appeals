"""Тесты разбора и проверки файла: без базы данных."""
import io

import pytest
from openpyxl import Workbook

from app.services.importer import ImportFileError, read_table, validate_rows

CATS = {"roads": 1, "дороги": 1, "garbage": 2}
DISTS = {"калининский": 10, "дёмский": 11}


def _csv(text_: str, enc="utf-8-sig") -> bytes:
    return text_.encode(enc)


def test_csv_comma_and_semicolon_delimiters():
    a = read_table("a.csv", _csv("text,created_at\nЯма,2026-10-01 10:00\n"))
    b = read_table("b.csv", _csv("text;created_at\nЯма;2026-10-01 10:00\n"))
    assert a == b and a[0][0] == 2


def test_csv_windows1251():
    rows = read_table("a.csv", "text;created_at\nЯма на дороге;01.10.2026 10:00\n".encode("cp1251"))
    assert rows[0][1]["text"] == "Яма на дороге"


def test_xlsx_read():
    wb = Workbook()
    ws = wb.active
    ws.append(["text", "created_at", "category"])
    ws.append(["Яма", "2026-10-01 10:00", "roads"])
    buf = io.BytesIO()
    wb.save(buf)
    rows = read_table("a.xlsx", buf.getvalue())
    assert rows[0][1]["category"] == "roads"


def test_missing_required_column():
    with pytest.raises(ImportFileError, match="created_at"):
        read_table("a.csv", _csv("text,category\nЯма,roads\n"))


def test_unsupported_format():
    with pytest.raises(ImportFileError):
        read_table("a.pdf", b"x")


def test_empty_rows_skipped_and_row_numbers():
    rows = read_table("a.csv", _csv("text,created_at\nA,2026-10-01\n,\nB,2026-10-02\n"))
    assert [n for n, _ in rows] == [2, 4]


def _validate(csv_body: str):
    return validate_rows(read_table("a.csv", _csv(csv_body)), CATS, DISTS)


def test_valid_row_with_optional_fields():
    valid, errors = _validate(
        "external_id,text,created_at,district,lat,lon,category\n"
        "X1,Яма во дворе,2026-10-01T10:00,Калининский,\"54,79\",55.99,Дороги\n"
    )
    assert not errors
    r = valid[0]
    assert r["category_id"] == 1 and r["district_id"] == 10 and r["lat"] == 54.79
    assert r["created_at"].utcoffset().total_seconds() == 5 * 3600  # пояс Уфы по умолчанию


def test_category_optional():
    valid, errors = _validate("text,created_at\nЯма,01.10.2026 10:00\n")
    assert not errors and valid[0]["category_id"] is None


@pytest.mark.parametrize("row, fragment", [
    (",2026-10-01", "пустой текст"),
    ("Яма,не дата", "не удалось разобрать дату"),
    ("Яма,2999-01-01", "в будущем"),
    ("Яма,1999-01-01", "слишком ранняя"),
    ("Яма,2026-10-01,fish", "неизвестная категория"),
])
def test_row_errors(row, fragment):
    valid, errors = _validate("text,created_at,category\n" + row + "\n")
    assert not valid and fragment in errors[0].message


def test_lat_without_lon_and_range():
    _, e1 = _validate("text,created_at,lat,lon\nЯма,2026-10-01,54.7,\n")
    _, e2 = _validate("text,created_at,lat,lon\nЯма,2026-10-01,154.7,55\n")
    assert "lat" in e1[0].message and "диапазона" in e2[0].message


def test_duplicate_external_id_inside_file():
    valid, errors = _validate("external_id,text,created_at\nA,Яма,2026-10-01\nA,Яма 2,2026-10-02\n")
    assert len(valid) == 1 and errors[0].row == 3 and "повтор" in errors[0].message
