"""
Zentrale Sprachverwaltung (I18n) für OHRICUT.
Unterstützt Deutsch ('de') und Englisch ('en').
Standardsprache bei Neuinstallation ist Englisch ('en').
Fehlende Übersetzungsschlüssel führen nie zum Absturz.
"""
import os
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LANG_DIR = os.path.join(SCRIPT_DIR, "lang")

AKTUELLER_CODE = "en"
UEBERSETZUNGEN = {}


def lade_uebersetzungen():
    global UEBERSETZUNGEN
    UEBERSETZUNGEN.clear()
    for code in ("de", "en"):
        datei = os.path.join(LANG_DIR, f"{code}.json")
        if os.path.isfile(datei):
            try:
                with open(datei, "r", encoding="utf-8") as fh:
                    UEBERSETZUNGEN[code] = json.load(fh)
            except Exception as ex:
                print(f"Warnung: Sprachdatei {datei} konnte nicht geladen werden: {ex}")
                UEBERSETZUNGEN[code] = {}
        else:
            UEBERSETZUNGEN[code] = {}


lade_uebersetzungen()


def setze_sprache(code):
    global AKTUELLER_CODE
    if code in ("de", "en"):
        AKTUELLER_CODE = code
    else:
        AKTUELLER_CODE = "en"


def hole_sprache():
    return AKTUELLER_CODE


def t(schluessel, standard=None, **kwargs):
    """
    Holt eine Übersetzung anhand eines Punkt-getrennten Schlüssels (z. B. 'ui.cut.btn_process').
    Unterstützt Formatierungs-Argumente kwargs.
    Falls der Schlüssel nicht gefunden wird, wird der Schlüssel oder standard zurückgegeben.
    """
    teile = schluessel.split(".")
    akt = UEBERSETZUNGEN.get(AKTUELLER_CODE, {})
    for teil in teile:
        if isinstance(akt, dict) and teil in akt:
            akt = akt[teil]
        else:
            akt = None
            break

    if akt is None:
        # Fallback auf Englisch, falls die aktuelle Sprache Deutsch war
        if AKTUELLER_CODE != "en":
            akt = UEBERSETZUNGEN.get("en", {})
            for teil in teile:
                if isinstance(akt, dict) and teil in akt:
                    akt = akt[teil]
                else:
                    akt = None
                    break

    if akt is None:
        akt = standard if standard is not None else schluessel

    if kwargs and isinstance(akt, str):
        try:
            return akt.format(**kwargs)
        except Exception:
            return akt
    return akt
