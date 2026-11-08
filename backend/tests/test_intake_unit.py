"""Проверка данных нового обращения (без базы)."""
import pytest

from app.services.intake import IntakeError, NewAppeal, clean

GOOD = "На улице Ленина яма посреди дороги, уже месяц."


def test_text_is_normalized():
    assert clean(NewAppeal(text="  " + GOOD.replace(" ", "   ") + " ")).text == GOOD


@pytest.mark.parametrize("body", ["", "коротко", None, "x" * 5001])
def test_bad_text_rejected(body):
    with pytest.raises(IntakeError):
        clean(NewAppeal(text=body))


def test_unknown_source_rejected():
    with pytest.raises(IntakeError):
        clean(NewAppeal(text=GOOD, source="import"))


@pytest.mark.parametrize("email", ["abc", "a@b", "a b@c.ru", "@c.ru"])
def test_bad_email_rejected(email):
    with pytest.raises(IntakeError):
        clean(NewAppeal(text=GOOD, contact_email=email))


def test_email_is_lowercased_and_empty_becomes_none():
    assert clean(NewAppeal(text=GOOD, contact_email=" Ivan@Mail.RU ")).contact_email == "ivan@mail.ru"
    assert clean(NewAppeal(text=GOOD, contact_email="  ", address_text=" ")).contact_email is None


@pytest.mark.parametrize("lat,lon", [(54.7, None), (None, 55.9), (91, 55.9), (54.7, 181)])
def test_bad_coordinates_rejected(lat, lon):
    with pytest.raises(IntakeError):
        clean(NewAppeal(text=GOOD, lat=lat, lon=lon))


def test_valid_coordinates_kept():
    d = clean(NewAppeal(text=GOOD, lat=54.73, lon=55.96))
    assert (d.lat, d.lon) == (54.73, 55.96)
