import base64

import pytest

from app.tuwel_token import TokenFehler, schreibe_env_wert, token_aus_link

TOKEN = "0123456789abcdef0123456789abcdef"


def kodiert(text: str, urlsafe: bool = False) -> str:
    funktion = base64.urlsafe_b64encode if urlsafe else base64.b64encode
    return funktion(text.encode()).decode()


def test_nur_base64_teil():
    assert token_aus_link(kodiert(f"pruefwert:::{TOKEN}")) == TOKEN


def test_ganzer_link_mit_privatem_token_und_leerraum():
    link = f"  moodledownloader://token={kodiert(f'abc:::{TOKEN}:::privat123privat123')}  \n"
    assert token_aus_link(link) == TOKEN


def test_ohne_auffuellung_urlsafe_und_url_kodiert():
    text = kodiert(f"x:::{TOKEN}", urlsafe=True).rstrip("=")
    assert token_aus_link(text) == TOKEN
    assert token_aus_link(kodiert(f"x:::{TOKEN}").replace("=", "%3D")) == TOKEN


@pytest.mark.parametrize("eingabe, meldung", [
    ("", "Leere"),
    ("%%%nicht-base64%%%", "Base64"),
    (kodiert("ohne trenner"), ":::"),
    (kodiert("a:::kurz"), "nicht wie ein Token"),
])
def test_fehler_ohne_token_in_meldung(eingabe, meldung):
    with pytest.raises(TokenFehler, match=meldung) as fehler:
        token_aus_link(eingabe)
    assert TOKEN not in str(fehler.value)


def test_schreibe_env_ersetzt_und_behaelt_andere_zeilen(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# Kommentar\nTUWEL_TOKEN=altersschluessel\nTUWEL_URL=https://tuwel.tuwien.ac.at\n", encoding="utf-8")
    schreibe_env_wert(env, "TUWEL_TOKEN", TOKEN)
    assert env.read_text(encoding="utf-8") == f"# Kommentar\nTUWEL_TOKEN={TOKEN}\nTUWEL_URL=https://tuwel.tuwien.ac.at\n"
    assert not list(tmp_path.glob(".env.*.tmp"))  # keine Temp-Dateien übrig


def test_schreibe_env_haengt_an_und_legt_an(tmp_path):
    env = tmp_path / ".env"
    schreibe_env_wert(env, "TUWEL_TOKEN", TOKEN)
    assert env.read_text(encoding="utf-8") == f"TUWEL_TOKEN={TOKEN}\n"
    schreibe_env_wert(env, "ANDERES", "1")
    assert env.read_text(encoding="utf-8").splitlines() == [f"TUWEL_TOKEN={TOKEN}", "ANDERES=1"]
