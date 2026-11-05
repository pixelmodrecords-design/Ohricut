"""
OHRICUT Logik-Modul: Verwaltung von Einstellungen, Pool, Caching und Musik-Generierung.
"""
import os
import wave
import json
import shutil
import random
import datetime
import math
import uuid
import numpy as np

import ohricut_kern as kern

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(SCRIPT_DIR, "RESULTS")
POOL_DIR = os.path.join(SCRIPT_DIR, "POOL")
OUT_DIR = os.path.join(SCRIPT_DIR, "GENERATED_MUSIC")
EINSTELLUNGEN_PFAD = os.path.join(SCRIPT_DIR, "ohricut_einstellungen.json")
CACHE_PFAD = os.path.join(POOL_DIR, "pool_cache.json")
AUSWAHL_PFAD = os.path.join(SCRIPT_DIR, "auswahl_generator.json")

STANDARD_EINSTELLUNGEN = {
    "drum_modus": "break",              # straight / break / shuffle
    "sidechain": "mid",                 # soft (-1.5dB) / mid (-3.0dB) / hard (-6.0dB)
    "bass_synth": True,
    "bass_synth_klangart": "saettigung", # saegeszahn / saettigung / slap / flaechig
    "uebergang_melodie": True,
    "uebergang_drums": True,
    "voice_variation": 0,               # 0 bis 5
    "melodie_variation": 0              # 0 bis 5
}

SIDECHAIN_DB = {
    "soft": -1.5,
    "mid": -3.0,
    "hard": -6.0
}


# ============ Einstellungen ============
def lade_einstellungen():
    einstellungen = dict(STANDARD_EINSTELLUNGEN)
    if os.path.isfile(EINSTELLUNGEN_PFAD):
        try:
            with open(EINSTELLUNGEN_PFAD, "r", encoding="utf-8") as fh:
                daten = json.load(fh)
                einstellungen.update({k: v for k, v in daten.items() if k in STANDARD_EINSTELLUNGEN})
        except Exception as ex:
            print(f"Fehler beim Laden der Einstellungen: {ex}")
    return einstellungen


def speichere_einstellungen(einstellungen):
    try:
        with open(EINSTELLUNGEN_PFAD, "w", encoding="utf-8") as fh:
            json.dump(einstellungen, fh, ensure_ascii=False, indent=2)
    except Exception as ex:
        print(f"Fehler beim Speichern der Einstellungen: {ex}")


# ============ Pool-Verwaltung & Cache ============
def init_pool_struktur():
    os.makedirs(POOL_DIR, exist_ok=True)
    for kat in kern.POOL_KATS:
        os.makedirs(os.path.join(POOL_DIR, kat), exist_ok=True)


def _lese_cache_datei():
    """Liest den Cache nur. Fehlt er oder ist er defekt, kommt ein leeres Dict zurück."""
    if not os.path.isfile(CACHE_PFAD):
        return {}
    try:
        with open(CACHE_PFAD, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def lese_pool_cache():
    """Nur lesen, ohne Analyse. Für die Oberfläche gedacht."""
    return _lese_cache_datei()


def _schreibe_cache(cache):
    """Atomar schreiben, damit nie eine halbe Datei gelesen wird."""
    tmp = CACHE_PFAD + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, CACHE_PFAD)
    except Exception as ex:
        print(f"Fehler beim Schreiben des Pool-Cache: {ex}")


def _analysiere_pool_datei(kat, dateiname):
    pfad = os.path.join(POOL_DIR, kat, dateiname)
    try:
        mono, sr = kern.read_wav_mono(pfad)
        feats = kern.features(dateiname, mono, sr)
        feats.pop("_fp", None)   # numpy-Array ist nicht JSON-fähig
        feats["mtime"] = os.path.getmtime(pfad)
        feats["size"] = os.path.getsize(pfad)
        feats["rel_pfad"] = os.path.join(kat, dateiname)
        return feats
    except Exception as ex:
        print(f"Fehler beim Analysieren von Pool-Sample {dateiname}: {ex}")
        return None


def sync_pool_cache():
    """Gleicht den Cache mit den Ordnern ab. Neue oder geänderte Dateien werden analysiert,
    gelöschte Einträge fallen weg. Die Ordner sind maßgeblich."""
    init_pool_struktur()
    alt = _lese_cache_datei()
    alt_map = {(k, e.get("file")): e for k in kern.POOL_KATS for e in alt.get(k, [])}
    neu = {k: [] for k in kern.POOL_KATS}
    for kat in kern.POOL_KATS:
        kat_dir = os.path.join(POOL_DIR, kat)
        for dateiname in sorted(os.listdir(kat_dir)):
            if dateiname.startswith("_") or not dateiname.lower().endswith(".wav"):
                continue
            pfad = os.path.join(kat_dir, dateiname)
            if not os.path.isfile(pfad):
                continue
            mtime, size = os.path.getmtime(pfad), os.path.getsize(pfad)
            e = alt_map.get((kat, dateiname))
            if e and e.get("mtime") == mtime and e.get("size") == size:
                neu[kat].append(e)
                continue
            feats = _analysiere_pool_datei(kat, dateiname)
            if feats:
                neu[kat].append(feats)
    _schreibe_cache(neu)
    return neu


def _setze_eintrag(kat, dateiname):
    """Analysiert genau eine Datei neu und trägt sie in den Cache ein."""
    cache = _lese_cache_datei()
    for k in kern.POOL_KATS:
        cache.setdefault(k, [])
    cache[kat] = [e for e in cache[kat] if e.get("file") != dateiname]
    feats = _analysiere_pool_datei(kat, dateiname)
    if feats:
        cache[kat].append(feats)
    cache[kat].sort(key=lambda e: e.get("file", ""))
    _schreibe_cache(cache)


def _entferne_eintrag(kat, dateiname):
    cache = _lese_cache_datei()
    if kat in cache:
        cache[kat] = [e for e in cache[kat] if e.get("file") != dateiname]
        _schreibe_cache(cache)


def _wav_dauer(pfad):
    """Dauer einer WAV-Datei in Sekunden, None wenn sie sich nicht lesen lässt."""
    try:
        with wave.open(pfad, "rb") as wf:
            return wf.getnframes() / float(wf.getframerate())
    except Exception:
        return None


def _pruefe_voice_dauer(pfad, kategorie):
    """VOICE-Samples unter VOICE_MIN_S werden nie gespielt und dürfen nicht in den Pool."""
    if kategorie != "VOICE":
        return
    dauer = _wav_dauer(pfad)
    if dauer is not None and dauer < VOICE_MIN_S:
        raise ValueError(f"VOICE unter {VOICE_MIN_S} s nicht erlaubt ({dauer:.2f} s)")


def freigeben_in_pool(quelle_pfad, ziel_kategorie):
    """Verschiebt ein Sample von RESULTS in den Pool und aktualisiert nur diesen Eintrag."""
    if ziel_kategorie not in kern.POOL_KATS:
        raise ValueError(f"Ungültige Kategorie: {ziel_kategorie}")
    _pruefe_voice_dauer(quelle_pfad, ziel_kategorie)

    init_pool_struktur()
    dateiname = os.path.basename(quelle_pfad)
    ziel_dir = os.path.join(POOL_DIR, ziel_kategorie)
    ziel_pfad = os.path.join(ziel_dir, dateiname)

    if os.path.exists(ziel_pfad):
        base, ext = os.path.splitext(dateiname)
        dateiname = f"{base}_{uuid.uuid4().hex[:4]}{ext}"
        ziel_pfad = os.path.join(ziel_dir, dateiname)

    shutil.move(quelle_pfad, ziel_pfad)
    _setze_eintrag(ziel_kategorie, dateiname)
    return ziel_pfad


def verschiebe_in_pool(rel, ziel_kategorie):
    """Verschiebt ein Pool-Sample in eine andere Kategorie. Die Auswahl bleibt erhalten, der Pfad wird angepasst."""
    alt_kat = _kat_aus_rel(rel)
    if ziel_kategorie not in kern.POOL_KATS:
        raise ValueError(f"Ungültige Kategorie: {ziel_kategorie}")
    if alt_kat == ziel_kategorie:
        raise ValueError(f"Das Sample liegt schon in {ziel_kategorie}")
    quelle = os.path.join(POOL_DIR, rel)
    if not os.path.isfile(quelle):
        raise ValueError("Datei ist nicht in der LIBRARY")
    _pruefe_voice_dauer(quelle, ziel_kategorie)

    init_pool_struktur()
    dateiname = os.path.basename(rel)
    ziel_dir = os.path.join(POOL_DIR, ziel_kategorie)
    ziel_pfad = os.path.join(ziel_dir, dateiname)
    if os.path.exists(ziel_pfad):
        base, ext = os.path.splitext(dateiname)
        dateiname = f"{base}_{uuid.uuid4().hex[:4]}{ext}"
        ziel_pfad = os.path.join(ziel_dir, dateiname)
    auswahl = lade_auswahl()          # vor dem Verschieben, sonst fallen Einträge ohne Datei weg
    if rel in auswahl[alt_kat] and ziel_kategorie in DRUM_KATS and len(auswahl[ziel_kategorie]) >= DRUM_PLAETZE:
        raise ValueError(f"{ziel_kategorie} ist voll ({DRUM_PLAETZE}/{DRUM_PLAETZE})")
    shutil.move(quelle, ziel_pfad)

    neu_rel = f"{ziel_kategorie}/{dateiname}"
    if rel in auswahl[alt_kat]:
        auswahl[alt_kat].remove(rel)
        auswahl[ziel_kategorie].append(neu_rel)
        _schreibe_auswahl(auswahl)
    sync_pool_cache()
    return neu_rel


def loesche_aus_pool(kategorie, dateiname):
    pfad = os.path.join(POOL_DIR, kategorie, dateiname)
    if os.path.isfile(pfad):
        os.remove(pfad)
    _entferne_eintrag(kategorie, dateiname)
    lade_auswahl()  # entfernt Eintraege ohne Datei aus der Auswahl


def _leere_auswahl():
    return {k: [] for k in kern.POOL_KATS}


def _schreibe_auswahl(auswahl):
    tmp = AUSWAHL_PFAD + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(auswahl, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, AUSWAHL_PFAD)


def lade_auswahl():
    """Liest auswahl_generator.json neu. Fehlt sie, wird eine leere angelegt.
    Eintraege ohne vorhandene Datei in POOL/ fallen weg. Eine defekte Datei wird als .defekt gesichert.
    Es wird nichts automatisch ergaenzt."""
    init_pool_struktur()
    if not os.path.isfile(AUSWAHL_PFAD):
        auswahl = _leere_auswahl()
        _schreibe_auswahl(auswahl)
        return auswahl
    try:
        with open(AUSWAHL_PFAD, encoding="utf-8") as fh:
            daten = json.load(fh)
        if not isinstance(daten, dict):
            raise ValueError("kein Objekt")
    except Exception:
        os.replace(AUSWAHL_PFAD, AUSWAHL_PFAD + ".defekt")
        auswahl = _leere_auswahl()
        _schreibe_auswahl(auswahl)
        return auswahl
    auswahl = _leere_auswahl()
    for kat in kern.POOL_KATS:
        eintraege = daten.get(kat)
        if not isinstance(eintraege, list):
            continue
        for rel in eintraege:
            if not isinstance(rel, str) or not rel.startswith(kat + "/") or rel in auswahl[kat]:
                continue
            if os.path.isfile(os.path.join(POOL_DIR, rel)):
                auswahl[kat].append(rel)
        if kat in DRUM_KATS:
            auswahl[kat] = auswahl[kat][:DRUM_PLAETZE]      # mehr als zwei Plätze gibt es nicht
    if auswahl != daten:
        _schreibe_auswahl(auswahl)
    return auswahl


def _kat_aus_rel(rel):
    """Kategorie aus einem Pfad wie 'KICK/s0001.wav'. Ungueltige Pfade werfen ValueError."""
    if not isinstance(rel, str) or "/" not in rel:
        raise ValueError(f"Ungültiger Eintrag: {rel}")
    kat = rel.split("/", 1)[0]
    if kat not in kern.POOL_KATS:
        raise ValueError(f"Unbekannte Kategorie: {kat}")
    return kat


def auswahl_hinzufuegen(rel):
    kat = _kat_aus_rel(rel)
    if not os.path.isfile(os.path.join(POOL_DIR, rel)):
        raise ValueError("Datei ist nicht in der LIBRARY")
    _pruefe_voice_dauer(os.path.join(POOL_DIR, rel), kat)
    auswahl = lade_auswahl()
    if rel in auswahl[kat]:
        raise ValueError("Schon in der Auswahl")
    if kat in DRUM_KATS and len(auswahl[kat]) >= DRUM_PLAETZE:
        raise ValueError(f"{kat} ist voll ({DRUM_PLAETZE}/{DRUM_PLAETZE})")
    auswahl[kat].append(rel)
    _schreibe_auswahl(auswahl)
    return auswahl


def auswahl_entfernen(rel):
    kat = _kat_aus_rel(rel)
    auswahl = lade_auswahl()
    if rel not in auswahl[kat]:
        raise ValueError("Nicht in der Auswahl")
    auswahl[kat].remove(rel)
    _schreibe_auswahl(auswahl)
    return auswahl


# ============ Generator ============
SCHRITTE = 16
SLOT_TAKTE = 8
VOICE_MIN_S = 0.2                 # kürzestes VOICE-Sample, das gespielt werden kann (= Untergrenze Chop)
GAIN = {"KICK": -1.5, "KICK_ACCENT": -4.5, "BASS": -3.5,
        "SNARE": -2.5, "SNARE_GHOST": -2.5 + 20 * math.log10(2 / 3),   # Ghostnote: 2/3 der Lautstärke
        "PERC": -4.0, "PERC_HIGH": -7.0, "HATS": -7.5, "HATS_LEISE": -9.5,
        "MELODY": -6.0, "SHOUT": -1.5, "TRANS": -4.5, "CHOP": -3.0}
SKALA_DUR = [0, 2, 4, 5, 7, 9, 11]        # Dur-Tonleiter in Halbtönen
SKALA_MOLL = [0, 2, 3, 5, 7, 8, 10]       # natürliches Moll
TERZ = {"Dur": 4, "Moll": 3}              # Platzhalter "T" im Bassmuster
TRANS_SCHRITTE = [-7, -5, -2, 2, 5, 7]
TRANS_WAHRSCHEINLICHKEIT = 0.3
GRUNDTON_BASIS_HZ = 32.70        # C1, Basis für die Grundnote
TONART_SICHER_MIN = 60.0
STANDARD_OPTIONEN = {"transposition": False, "bass_verlauf": True}
STIMMUNGEN_GEN = ("Energetisch", "Entspannt", "Minimal")
MAX_DAUER_S = 300

# "T" = Terz: 4 Halbtöne in Dur, 3 in Moll
BASS_MUSTER = {
    "Energetisch": [(0, 0, 3), (3, 0, 1), (4, 12, 2), (6, 7, 2), (8, 0, 3), (11, 0, 1), (12, 5, 2), (14, "T", 2)],
    "Entspannt":   [(0, 0, 6), (8, 0, 4), (12, -2, 4)],
    "Minimal":     [(0, 0, 8)],
}
# Minimal: Synth-Bass mit 2 bzw. 3 Ereignissen pro Takt, Wechsel alle 4 Takte. Nie auf einem Kick-Schritt.
BASS_MINIMAL = [[(4, 0, 4), (10, 7, 4)],
                [(4, 0, 3), (10, 7, 3), (13, 0, 3)]]
BASS_KLANG_DAUER = {"slap": 0.5, "saegeszahn": 0.9, "saettigung": 1.0, "flaechig": 1.5}

# ---------- Drums: je Kategorie zwei feste Plätze (oben = Primär, unten = Sekundär) ----------
DRUM_KATS = ("KICK", "HIHAT", "PERC", "SNARE_CLAP")
DRUM_PLAETZE = 2
DRUM_ROLLEN = {"KICK": ("Regular", "Accent"), "HIHAT": ("Closed", "Open"),
               "PERC": ("Low", "High"), "SNARE_CLAP": ("Regular", "Fill")}

FILL_AB = 12                              # ab diesem Schritt im letzten Takt jedes 4-Takt-Blocks
HAT_BETONT = [0, 8]
SNARE_FILL = [12, 14]
MINIMAL_KICK = [0, 8]                     # Minimal: Kick nur auf 0 und 8
# Drum-Modi. open_entspannt: in Entspannt spielen die Hats nur auf diesen Schritten (kein Closed).
# hop_kick / hop_hat: Chance je Treffer, in einem Takt um einen Schritt zu "hüpfen" (nur Shuffle).
DRUM_MODI = {
    "straight": {"kick": [0, 4, 8, 12], "accent": [14], "snare": [4, 12], "ghost": [2, 10],
                 "open": [2, 6, 10, 14], "closed": [0, 4, 8, 12], "open_entspannt": [6, 14],
                 "hop_kick": 0.0, "hop_hat": 0.0, "swing": 0.0},
    "break":    {"kick": [0, 4, 8, 12], "accent": [14], "snare": [6, 12], "ghost": [4, 10],
                 "open": [6, 14], "closed": [0, 2, 4, 8, 10, 12], "open_entspannt": [6, 14],
                 "hop_kick": 0.0, "hop_hat": 0.0, "swing": 0.0},
    "shuffle":  {"kick": [0, 4, 8, 12], "accent": [7, 14], "snare": [4, 11], "ghost": [2, 9],
                 "open": [7, 15], "closed": [0, 2, 5, 8, 10, 13], "open_entspannt": [7, 15],
                 "hop_kick": 0.25, "hop_hat": 0.25, "swing": 0.2},
}
SHUFFLE_JITTER_S = 0.004                  # Shuffle muss nicht präzise sein: kleine zufällige Zeitabweichung
PERC_LOW_FILL = [13, 15]
PERC_HIGH_KANDIDATEN = [5, 7, 9, 11]

# Variationen der Drums je Stimmung. Zusätzlich: Minimal spielt die Kick nur auf 0 und 8,
# Entspannt spielt die Hats nur auf den Schritten open_entspannt (ohne Closed).
# accent_takte / ghost_takte: Kick-Accent bzw. Snare-Ghostnote in jedem n-ten Takt (0 = aus)
# perc_p / perc_max: Chance je Kandidat und Höchstzahl der Perc-High-Ghostnotes pro Takt
# hat_dynamik: Closed-Hat auf 0 und 8 lauter; fill_takte: Fill im letzten Takt jedes n-Takt-Blocks
# open_takte: Hihat Open nur in jedem n-ten Takt (1 = in jedem)
DRUM_VARIATION = {
    "Energetisch": {"accent_takte": 2, "ghost_takte": 2, "perc_p": 0.3, "perc_max": 2, "hat_dynamik": True,
                    "fill_takte": 4, "open_takte": 1},
    "Entspannt":   {"accent_takte": 8, "ghost_takte": 4, "perc_p": 0.15, "perc_max": 1, "hat_dynamik": True,
                    "fill_takte": 4, "open_takte": 1},
    # Minimal: die sekundären Drums (Accent, Open, Perc High, Fill) behalten ihre Rollen, spielen aber deutlich seltener
    "Minimal":     {"accent_takte": 16, "ghost_takte": 0, "perc_p": 0.08, "perc_max": 1, "hat_dynamik": False,
                    "fill_takte": 8, "open_takte": 4},
}


def _wurzel(tonart):
    if not tonart:
        return None
    name = str(tonart).split()[0]
    return kern.TONART_NAMEN.index(name) if name in kern.TONART_NAMEN else None


def grundnote_hz(ziel):
    w = _wurzel(ziel)
    if w is None:
        return 55.0
    f = GRUNDTON_BASIS_HZ * 2 ** (w / 12)
    while f < 41:
        f *= 2
    return f


def ziel_tonart(pools):
    gew = {}
    for kat, faktor in (("MELODY", 0.5), ("VOICE", 0.5)):
        for e in pools[kat]:
            t = e.get("tonart")
            if _wurzel(t) is not None and e.get("tonart_sicherheit", 0) >= TONART_SICHER_MIN:
                gew[t] = gew.get(t, 0.0) + faktor * e["w"]
    return max(gew, key=gew.get) if gew else None


# Gewählter Grundton und Dur/Moll (nicht gespeichert, Start C Dur). Wirkt auf Melodie und Bass.
ZIEL = {"grund": 0, "modus": "Dur"}


def ziel_string():
    return f"{kern.TONART_NAMEN[ZIEL['grund']]} {ZIEL['modus']}"


def setze_ziel(grund=None, modus=None):
    if grund is not None:
        ZIEL["grund"] = grund % 12
    if modus is not None:
        ZIEL["modus"] = modus


def setze_ziel_aus_tonart(t):
    """Messung im Cut: übernimmt den erkannten Wert. Ohne Erkennung bleibt der aktuelle Wert."""
    if not t:
        return False
    teile = str(t).split()
    if len(teile) != 2 or teile[0] not in kern.TONART_NAMEN:
        return False
    ZIEL["grund"] = kern.TONART_NAMEN.index(teile[0])
    ZIEL["modus"] = "Moll" if teile[1] == "Moll" else "Dur"
    return True


def melodien_auf_ziel(mel, ziel):
    """Grundton und Dur/Moll wirken nicht mehr auf die Melodie. Die Regler unten übernehmen das."""
    return list(mel)

def zufall(rnd, liste):
    if not liste:
        return None
    return rnd.choices(liste, weights=[max(1e-6, z["w"]) for z in liste])[0]["x"]


def vokal_rollen(voices, beat_s):
    """Teilt VOICE-Samples nach Länge in vier Rollen. Priorität: Chop, Shout, Übergang, Lange Phrase.
    Jedes Sample gehört zur ersten Rolle, deren Länge passt.
    Übergang wird auf 1 Beat, Lange Phrase auf 2 Beats gekürzt."""
    chops, shouts, trans, lang = [], [], [], []
    for v in voices:
        d = v["dauer"]
        if VOICE_MIN_S <= d < 0.5:
            chops.append(v)
        elif 0.5 <= d <= 0.8 and v.get("anschlag"):
            shouts.append(v)
        elif d >= beat_s and d < 2 * beat_s:
            trans.append(dict(v, x=kern.chop(v["x"], beat_s), dauer=min(d, beat_s)))
        elif d >= 2 * beat_s:
            lang.append(dict(v, x=kern.chop(v["x"], 2 * beat_s), dauer=min(d, 2 * beat_s)))
    return shouts, trans, chops, lang


def lange_slots(lang, takte, takt_s, rnd):
    lang = list(lang)
    rnd.shuffle(lang)
    out = []
    for i, v in enumerate(lang):
        bar = i * SLOT_TAKTE
        if bar >= takte:
            break
        out.append((int(bar * takt_s * kern.SR), v["x"]))
    return out


def _bass_note(cache, freq, dauer_s, klang):
    key = (round(freq, 2), round(dauer_s, 3), klang)
    if key not in cache:
        cache[key] = kern.synthesisiere_bass(dauer_s, freq_hz=freq, typ=klang)
    return cache[key]


def ist_moll(ziel):
    return bool(ziel) and "Moll" in str(ziel)


def intervall(wert, moll):
    if wert == "T":
        return TERZ["Moll" if moll else "Dur"]
    return wert


_AUDIO_CACHE = {}   # Pfad relativ zu POOL -> (Zeitstempel, Eintrag). LIBRARY wird nur gelesen.


def _lade_eintrag(rel):
    """Liest eine Auswahl-Datei. Neu eingelesen wird nur, wenn sich der Zeitstempel geaendert hat."""
    pfad = os.path.join(POOL_DIR, rel)
    mtime = os.path.getmtime(pfad)
    alt = _AUDIO_CACHE.get(rel)
    if alt and alt[0] == mtime:
        return alt[1]
    mono, sr = kern.read_wav_mono(pfad)
    f = kern.features(os.path.basename(rel), mono, sr)
    x = kern.resample(mono, sr)

    kat = rel.replace("\\", "/").split("/", 1)[0]
    if kat in ("KICK", "HIHAT", "SNARE_CLAP", "PERC"):
        x = kern.trim_leading_silence(x, kern.SR)

    x = kern.nulldurchgang_fade(x, kern.SR)
    e = {"x": x, "w": 1.0, "dauer": len(x) / kern.SR, "leer": bool(f.get("leer")),
         "centroid": float(f.get("centroid", 0) or 0), "stimmhaft": float(f.get("stimmhaft", 0) or 0),
         "anschlag": bool(f.get("anschlag", False)), "tonart": f.get("tonart"),
         "tonart_sicherheit": float(f.get("tonart_sicherheit", 0) or 0), "f0": float(f.get("f0", 0) or 0)}
    _AUDIO_CACHE[rel] = (mtime, e)
    return e


def lade_auswahl_pools(bpm):
    """Nur die Bausteine aus der Auswahl (Pool, Abschnitt 2), nach Rolle getrennt.
    Drum-Kategorien: Liste mit festen Plätzen (Index 0 = Primär, 1 = Sekundär), None = Platz leer oder unbrauchbar."""
    auswahl = lade_auswahl()
    pools = {k: [] for k in kern.POOL_KATS}
    aktiv = set()
    for kat in kern.POOL_KATS:
        for rel in auswahl.get(kat, []):
            aktiv.add(rel)
            try:
                e = _lade_eintrag(rel)
            except Exception:
                e = None
            if e is None or e["leer"] or e["dauer"] < kern.MIN_DUR_S:
                if kat in DRUM_KATS:
                    pools[kat].append(None)      # Platz bleibt belegt, die Rolle schweigt
                continue
            pools[kat].append(dict(e, x=e["x"], dauer=len(e["x"]) / kern.SR))
    for rel in list(_AUDIO_CACHE):
        if rel not in aktiv:
            del _AUDIO_CACHE[rel]
    return pools


MOTIV_SCHRITTE_MAX = 5                  # höchstens so viele Melodie-Schläge im Motiv
CHOP_WAHRSCHEINLICHKEIT = 0.35          # Chance je passendem Vocal-Schritt
MELODIE_BLOCK_VERSCHIEBUNG = [0, 2, 0, -2]   # Halbtöne je 2-Takt-Wiederholung
MELODIE_MIN_S = 0.25                    # kürzester Melodie-Klang beim Kürzen
MELODIE_LANG_S = 0.5                    # Minimal: Samples ab dieser Länge werden bevorzugt
MELODIE_KURZ_S = (0.25, 0.5)            # Minimal bei MM/MMM: Samples von 0,25 bis 0,49 s werden bevorzugt
MELODIE_BEVORZUGT = 3.0                 # Gewicht der bevorzugten Samples (alle anderen 1,0)


def _mutiere(motiv, pool, skala, mel, rnd):
    """Neue Phrase: ein Schlag wandert auf einen anderen freien Schritt, eine Note ändert sich,
    manchmal wechselt auch der Klang."""
    if not motiv:
        return motiv
    neu = [list(t) for t in motiv]
    belegt = {t[0] for t in neu}
    ziele = [s_ for s_ in pool if s_ not in belegt]
    if ziele:
        neu[rnd.randrange(len(neu))][0] = rnd.choice(ziele)
    neu[rnd.randrange(len(neu))][2] = rnd.choice(skala)
    if rnd.random() < 0.3:
        neu[rnd.randrange(len(neu))][1] = rnd.choice(mel)["x"]
    return sorted((tuple(t) for t in neu), key=lambda t: t[0])


def _melodie_ziehen(rnd, mel, kurz=False):
    """Minimal: bei jedem Einsatz neu gewürfelt. Lange Samples (ab 0,5 s) bevorzugt, in Läufen (MM, MMM)
    stattdessen kurze Samples (0,25 bis 0,49 s)."""
    def gewicht(e):
        d = len(e["x"]) / kern.SR
        bevorzugt = (MELODIE_KURZ_S[0] <= d < MELODIE_KURZ_S[1]) if kurz else (d >= MELODIE_LANG_S)
        return MELODIE_BEVORZUGT if bevorzugt else 1.0
    return rnd.choices(mel, weights=[gewicht(e) for e in mel])[0]["x"]


def _laufstufen(schritte):
    """Je Schlag die Länge der Folge unmittelbar aufeinanderfolgender Schritte (1 = allein, 2 = MM, 3 = MMM)."""
    out = [1] * len(schritte)
    i = 0
    while i < len(schritte):
        j = i
        while j + 1 < len(schritte) and schritte[j + 1] == schritte[j] + 1:
            j += 1
        for k in range(i, j + 1):
            out[k] = j - i + 1
        i = j + 1
    return out


def _bass_frei_von_kick(muster, verboten):
    """Setzt Bass-Schläge, die auf einem Kick-Schritt liegen, auf den nächsten freien Schritt."""
    belegt = {s_ for s_, _, _ in muster if s_ not in verboten}
    out = []
    for s_, iv, ln in muster:
        if s_ in verboten:
            for d in (1, -1, 2, -2, 3, -3):
                z = s_ + d
                if 0 <= z < SCHRITTE and z not in verboten and z not in belegt:
                    s_ = z
                    break
            belegt.add(s_)
        out.append((s_, iv, ln))
    return out


def _hop(steps, prob, rnd):
    """Jeder Schritt (außer 0) hüpft mit der Chance prob um einen Schritt vor oder zurück."""
    if not prob:
        return set(steps)
    out = set()
    for s_ in steps:
        if s_ != 0 and rnd.random() < prob:
            s_ = min(SCHRITTE - 1, max(0, s_ + rnd.choice([-1, 1])))
        out.add(s_)
    return out


def _naechster_onset(p, onsets):
    spaeter = [o for o in onsets if o > p]
    return min(spaeter) if spaeter else SCHRITTE


def _melodie_setzen(mix, snd, pos, schritt_s, onsets, p):
    """Melodie-Klang wird bis zum nächsten Schlag von Drums, Bass oder Vocal gekürzt."""
    naechster = _naechster_onset(p, onsets)
    grenze_s = max(MELODIE_MIN_S, (naechster - p) * schritt_s)
    n = int(grenze_s * kern.SR)
    if len(snd) > n:
        snd = kern.fade(snd[:n], 10)
    kern.lege_ab(mix, snd, pos, GAIN["MELODY"])


def _sequenz(pools, rnd, einst, takte, bpm, stimmung, opt):
    beat_s = 60.0 / bpm
    step_s = beat_s / 4
    takt_s = beat_s * 4
    takte = max(8, takte)

    ziel = ziel_string()
    grund = grundnote_hz(ziel)
    moll = ist_moll(ziel)
    skala = SKALA_MOLL if moll else SKALA_DUR
    mel = melodien_auf_ziel(pools["MELODY"], ziel)
    plaetze = {}
    for kat in DRUM_KATS:
        belegt = (list(pools[kat]) + [None] * DRUM_PLAETZE)[:DRUM_PLAETZE]
        plaetze[kat] = [d["x"] if d else None for d in belegt]
    kick_reg, kick_acc = plaetze["KICK"]
    hat_closed, hat_open = plaetze["HIHAT"]
    perc_low, perc_high = plaetze["PERC"]
    snare_reg, snare_fill = plaetze["SNARE_CLAP"]
    minimal = stimmung == "Minimal"
    shouts, trans, chops, lang = vokal_rollen(pools["VOICE"], beat_s)
    gesang = lange_slots(lang, takte, takt_s, rnd)

    target = int(takte * takt_s * kern.SR)
    total = max([target] + [p + len(x) for p, x in gesang])
    gesamt_takte = math.ceil(total / (takt_s * kern.SR))
    bass = np.zeros(total, np.float32)      # wird gesidechaint
    mel_mix = np.zeros(total, np.float32)   # Melodie, nicht gesidechaint
    rhy = np.zeros(total, np.float32)
    for p, x in gesang:
        kern.lege_ab(rhy, x, p, GAIN["TRANS"])

    dv = DRUM_VARIATION.get(stimmung, DRUM_VARIATION["Energetisch"])
    modus = einst.get("drum_modus", "break")
    dm = DRUM_MODI.get(modus, DRUM_MODI["break"])
    kick_base = MINIMAL_KICK if minimal else dm["kick"]
    open_base = dm["open_entspannt"] if stimmung == "Entspannt" else dm["open"]
    closed_base = [] if stimmung == "Entspannt" else dm["closed"]
    if hat_open is None:
        closed_base = sorted(set(closed_base) | set(open_base))     # ohne Open spielt Closed auch dort
    kick_set = set(kick_base) if kick_reg is not None else set()
    if kick_acc is not None and dv["accent_takte"]:
        kick_set |= set(dm["accent"])
    snare_set = set(dm["snare"]) if snare_reg is not None else set()
    if snare_reg is not None and dv["ghost_takte"]:
        snare_set |= set(dm["ghost"])
    hat_set = set()
    if hat_open is not None:
        hat_set |= set(open_base)
    if hat_closed is not None:
        hat_set |= set(closed_base)
    ueb_drums = einst.get("uebergang_drums", True)
    p_trans = TRANS_WAHRSCHEINLICHKEIT if opt["transposition"] else 0.0
    mel_var = int(einst.get("melodie_variation", 0) or 0)
    voice_var = int(einst.get("voice_variation", 0) or 0)

    # ---------- Bass ----------
    bass_steps = set()
    klang = einst.get("bass_synth_klangart", "saettigung")
    dfak = BASS_KLANG_DAUER.get(klang, 1.0)
    muster = BASS_MUSTER.get(stimmung, BASS_MUSTER["Entspannt"])
    cache = {}
    if minimal:
        # nie auf einem Kick-Schritt (auch nicht dort, wohin eine Kick im Shuffle hüpfen kann)
        verboten = set(kick_set)
        if dm["hop_kick"]:
            verboten |= {z for k_ in kick_base if k_ != 0 for z in (k_ - 1, k_ + 1)}
        bass_min = [_bass_frei_von_kick(m_, verboten) for m_ in BASS_MINIMAL]
    if einst.get("bass_synth", True):
        if minimal:
            bass_steps |= {s_ for m_ in bass_min for s_, _, _ in m_}
        else:
            bass_steps |= {s_ for s_, _, _ in muster}
        for bar in range(gesamt_takte):
            # Minimal: 2 Ereignisse pro Takt, dann 3, Wechsel alle 4 Takte
            m = bass_min[(bar // 4) % len(bass_min)] if minimal else muster
            for s_, iv, ln in m:
                pos = int((bar * SCHRITTE + s_) * step_s * kern.SR)
                if pos >= total:
                    continue
                stufe = intervall(iv, moll) if opt["bass_verlauf"] else 0
                snd = _bass_note(cache, grund * 2 ** (stufe / 12), max(0.05, ln * step_s * dfak), klang)
                kern.lege_ab(bass, snd, pos, GAIN["BASS"])

    # ---------- Raster: welche Schritte gehören welcher Rolle ----------
    kick_snare = set(kick_set) | set(snare_set)
    alle_drum = kick_snare | hat_set
    frei_mel = ([s for s in range(FILL_AB) if s not in kick_snare and s not in bass_steps]
                or [s for s in range(FILL_AB) if s not in kick_snare]
                or list(range(FILL_AB)))

    # Motiv: fester Melodie-Schlag je Takt-Paar, nur auf freien Schritten
    motiv = []
    if mel:
        # Minimal: Linie mit 3 bis 4 Tönen pro Takt, sonst Motiv mit 3 bis MOTIV_SCHRITTE_MAX Schlägen
        slots = sorted(rnd.sample(frei_mel, min(len(frei_mel), rnd.randint(3, 4 if minimal else MOTIV_SCHRITTE_MAX))))
        motiv = [(s, rnd.choice(mel)["x"], rnd.choice(skala)) for s in slots]
    motiv_steps = {s for s, _, _ in motiv}

    # Vocal-Chops: nur synkopiert, neben einem Drum-Schlag, nie auf Bass- oder Melodie-Schritten
    chop_steps = [s for s in range(SCHRITTE)
                  if s not in alle_drum and s not in bass_steps and s not in motiv_steps
                  and ((s - 1) % SCHRITTE in alle_drum or (s + 1) % SCHRITTE in alle_drum)]
    if not chop_steps:
        chop_steps = [s for s in range(SCHRITTE) if s not in alle_drum and s not in bass_steps and s not in motiv_steps]
    if not chops:
        chop_steps = []
    onsets = alle_drum | bass_steps | set(chop_steps)
    mel_var_steps = [s for s in frei_mel if s not in chop_steps and s not in motiv_steps]
    mel_pool = [s_ for s_ in frei_mel if s_ not in chop_steps] or list(frei_mel)   # Ziele für wandernde Schläge

    # ---------- Melodie ----------
    if minimal and motiv:
        # Linie: Grundton am Phrasenanfang, jede 4-Takt-Phrase ändert Rhythmus und eine Note, manchmal den Klang
        linie = motiv
        for bar in range(gesamt_takte):
            if bar and bar % 4 == 0:
                linie = _mutiere(linie, mel_pool, skala, mel, rnd)
            lauf = _laufstufen([t[0] for t in linie])
            for i, (s_, _motiv_snd, ht) in enumerate(linie):
                in_lauf = lauf[i] >= 2                       # MM oder MMM
                snd = _melodie_ziehen(rnd, mel, kurz=in_lauf)   # bei jedem Einsatz neu gewürfelt
                h = 0 if (bar % 4 == 0 and i == 0) else ht
                x = kern.pitch(snd, h) if h else snd
                pos = int((bar * SCHRITTE + s_) * step_s * kern.SR)
                if pos >= total:
                    continue
                if in_lauf:
                    kern.lege_ab(mel_mix, kern.chop(x, step_s), pos, GAIN["MELODY"])   # auf einen Step gekürzt
                else:
                    _melodie_setzen(mel_mix, x, pos, step_s, onsets, s_)
    elif motiv:
        for block in range(max(1, gesamt_takte // 2)):
            if block and block % 2 == 0:
                motiv = _mutiere(motiv, mel_pool, skala, mel, rnd)    # neue 4-Takt-Phrase: Rhythmus und Note ändern sich
            if stimmung == "Entspannt" and block % 4 == 3:
                continue                    # Atempause
            shift = MELODIE_BLOCK_VERSCHIEBUNG[block % len(MELODIE_BLOCK_VERSCHIEBUNG)]
            bs = block * 2 * SCHRITTE
            for bar in range(2):
                for s, snd, ht in motiv:
                    h = rnd.choice(skala) if (bar == 1 and rnd.random() < 0.3) else ht
                    h += shift
                    if p_trans and rnd.random() < p_trans:
                        h += rnd.choice(TRANS_SCHRITTE)
                    x = kern.pitch(snd, h) if h else snd
                    pos = int((bs + bar * SCHRITTE + s) * step_s * kern.SR)
                    if pos < total:
                        _melodie_setzen(mel_mix, x, pos, step_s, onsets, s)

    # ---------- Schritt-Raster: Drums und Vocal-Chops ----------
    kick_pos = []
    perc_treffer = set()
    for step in range(gesamt_takte * SCHRITTE):
        takt, p = divmod(step, SCHRITTE)
        pos = int(step * step_s * kern.SR)
        if pos >= total:
            break
        fill_takt = (takt + 1) % dv["fill_takte"] == 0
        fill = p >= FILL_AB and fill_takt
        if dm["swing"]:
            dpos = pos + (int(dm["swing"] * step_s * kern.SR) if p % 2 == 1 else 0)
            dpos = max(0, dpos + int(rnd.uniform(-SHUFFLE_JITTER_S, SHUFFLE_JITTER_S) * kern.SR))
        else:
            dpos = pos
        accent_takt = bool(dv["accent_takte"]) and takt % dv["accent_takte"] == 1
        ghost_takt = bool(dv["ghost_takte"]) and takt % dv["ghost_takte"] == 1

        if p == 0:
            bar_kick = _hop(kick_base, dm["hop_kick"], rnd)
            open_takt = takt % dv["open_takte"] == 1 % dv["open_takte"]
            bar_open = _hop(open_base, dm["hop_hat"], rnd) if open_takt else set()
            bar_closed = _hop(closed_base, dm["hop_hat"], rnd)
            bar_closed = (bar_closed - bar_open) if hat_open is not None else (bar_closed | bar_open)
            perc_treffer = set()
            if perc_high is not None and dv["perc_max"] and not fill_takt:
                kand = [s_ for s_ in PERC_HIGH_KANDIDATEN if rnd.random() < dv["perc_p"]]
                if len(kand) > dv["perc_max"]:
                    kand = rnd.sample(kand, dv["perc_max"])
                perc_treffer = set(kand)

        if fill:
            if snare_fill is not None and p in SNARE_FILL:
                kern.lege_ab(rhy, snare_fill, dpos, GAIN["SNARE"])
            if perc_low is not None and p in PERC_LOW_FILL:
                kern.lege_ab(rhy, perc_low, dpos, GAIN["PERC"])
        else:
            if snare_reg is not None:
                if p in dm["snare"]:
                    kern.lege_ab(rhy, snare_reg, dpos, GAIN["SNARE"])
                if ghost_takt and p in dm["ghost"]:
                    kern.lege_ab(rhy, snare_reg, dpos, GAIN["SNARE_GHOST"])
            if kick_reg is not None and p in bar_kick:
                kern.lege_ab(rhy, kick_reg, dpos, GAIN["KICK"])
                kick_pos.append(dpos)
            if kick_acc is not None and accent_takt and p in dm["accent"]:
                kern.lege_ab(rhy, kick_acc, dpos, GAIN["KICK_ACCENT"])
                kick_pos.append(dpos)
            if hat_open is not None and p in bar_open:
                kern.lege_ab(rhy, hat_open, dpos, GAIN["HATS"])
            if hat_closed is not None and p in bar_closed:
                betont = p in HAT_BETONT or not dv["hat_dynamik"]
                kern.lege_ab(rhy, hat_closed, dpos, GAIN["HATS"] if betont else GAIN["HATS_LEISE"])

        if perc_high is not None and p in perc_treffer:
            kern.lege_ab(rhy, perc_high, dpos, GAIN["PERC_HIGH"])

        if p == 12 and (takt + 1) % 4 == 0 and trans and ueb_drums:
            kern.lege_ab(rhy, zufall(rnd, trans), pos, GAIN["TRANS"])

        if chops and p in chop_steps and rnd.random() < CHOP_WAHRSCHEINLICHKEIT:
            kern.lege_ab(rhy, zufall(rnd, chops), pos, GAIN["CHOP"])

        # Variations-Regler: zusätzliche Treffer, nur auf freien Schritten
        if p == 0:
            if mel and mel_var and not minimal and mel_var_steps and rnd.random() < mel_var / 6:
                s2 = rnd.choice(mel_var_steps)
                snd = rnd.choice(mel)["x"]
                _melodie_setzen(mel_mix, snd, int((step + s2) * step_s * kern.SR), step_s, onsets, s2)
            if chops and chop_steps and voice_var and rnd.random() < voice_var / 6:
                s2 = rnd.choice(chop_steps)
                kern.lege_ab(rhy, zufall(rnd, chops), int((step + s2) * step_s * kern.SR), GAIN["CHOP"])

    # Sidechain nur auf den Bass, Melodie und Vocals bleiben unberührt
    bass = kern.wende_sidechain_ducking_an(bass, kick_pos,
                                           duck_db=SIDECHAIN_DB.get(einst.get("sidechain", "mid"), -3.0))
    mix = bass + mel_mix + rhy
    if shouts:
        kern.lege_ab(mix, zufall(rnd, shouts), 0, GAIN["SHOUT"])
    return mix


def hat_drum_sample(pools):
    """True, wenn mindestens ein nutzbares Drum-Sample in der Auswahl liegt."""
    return any(d is not None for kat in DRUM_KATS for d in pools.get(kat, []))


def generiere_track(bpm=125, takte=32, stimmung="Entspannt", optionen=None):
    """Erzeugt einen Track aus der Auswahl (POOL, Abschnitt 2). Gibt den Dateipfad zurueck.
    optionen: dict mit transposition und bass_verlauf (Standard: bass_verlauf an, Transposition aus)."""
    if stimmung not in STIMMUNGEN_GEN:
        raise ValueError(f"Unbekannte Stimmung '{stimmung}'")
    if not isinstance(bpm, int) or not 40 <= bpm <= 240:
        raise ValueError("BPM muss eine ganze Zahl zwischen 40 und 240 sein")
    if not isinstance(takte, int) or not 8 <= takte <= 256:
        raise ValueError("Takte muss eine ganze Zahl zwischen 8 und 256 sein")
    dauer = takte * 4 * 60.0 / bpm
    if dauer > MAX_DAUER_S:
        raise ValueError(f"Tracklänge {dauer:.0f} s überschreitet {MAX_DAUER_S} s. Weniger Takte oder höheres BPM wählen.")

    opt = dict(STANDARD_OPTIONEN)
    opt.update(optionen or {})
    einst = lade_einstellungen()
    pools = lade_auswahl_pools(bpm)
    if not hat_drum_sample(pools):
        raise ValueError("Mindestens ein Drum-Sample in der Auswahl")

    rnd = random.Random(random.randrange(1, 1000000))
    mix = _sequenz(pools, rnd, einst, takte, bpm, stimmung, opt)
    mix = kern.normiere(mix, ziel=0.89)

    os.makedirs(OUT_DIR, exist_ok=True)
    jetzt = datetime.datetime.now()
    basis = f"beat_{jetzt:%Y%m%d}_{jetzt:%H%M%S}"
    pfad = os.path.join(OUT_DIR, basis + ".wav")
    n = 0
    while os.path.exists(pfad):
        n += 1
        pfad = os.path.join(OUT_DIR, f"{basis}_{n}.wav")
    tmp = pfad + ".tmp"
    kern.write_wav(tmp, mix, kern.SR)
    os.replace(tmp, pfad)
    return pfad
