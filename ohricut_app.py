"""
OHRICUT: Hauptmodul für Benutzeroberfläche (Pygame mit 4 Reitern) und Kommandozeile (CLI).
"""
import os
import sys
import shutil
import threading
import traceback

# pygame wird erst in ui_main() geladen, damit Hilfe, CUT und Generieren ohne Pygame laufen
pygame = None

import ohricut_kern as kern
import ohricut_logik as logik

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(SCRIPT_DIR, "RESULTS")
POOL_DIR = os.path.join(SCRIPT_DIR, "POOL")

# ============ Hintergrund-Auftragsverwaltung ============
STATUS = {"text": "bereit", "busy": False, "thread": None, "ergebnis": None}


def melde(text):
    STATUS["text"] = text


def leere_results():
    """Leert RESULTS/ vollständig. Fasst ausschließlich RESULTS_DIR an (nie POOL, Auswahl oder GENERATED_MUSIC)."""
    if not os.path.isdir(RESULTS_DIR):
        return
    for n in os.listdir(RESULTS_DIR):
        p = os.path.join(RESULTS_DIR, n)
        if os.path.isdir(p) and not os.path.islink(p):
            shutil.rmtree(p, ignore_errors=True)
        else:
            try:
                os.remove(p)
            except OSError:
                pass


def starte_auftrag(fn, *args):
    if STATUS["busy"]:
        melde("Es läuft schon ein Auftrag")
        return False
    STATUS["busy"] = True
    STATUS["ergebnis"] = None

    def lauf():
        try:
            res = fn(*args)
            STATUS["ergebnis"] = res
        except Exception as ex:
            melde(f"Fehler: {ex}")
            traceback.print_exc()
        finally:
            STATUS["busy"] = False

    t = threading.Thread(target=lauf)
    STATUS["thread"] = t
    t.start()
    return True


# ============ CLI Hilfe ============
def zeige_hilfe():
    hilfe_text = """
========================================================================
                       OHRICUT - Hilfe & Anleitung
========================================================================

OHRICUT ist ein Werkzeug zum schnellen Erstellen von Beats und Loops aus
eigenem Audiomaterial.

1. GRAPHISCHE OBERFLÄCHE (GUI)
------------------------------------------------------------------------
Aufruf ohne Argumente:
  python3 ohricut_app.py

Die Oberfläche gliedert sich in vier Reiter:
  - CUT:      WAV-Datei auswählen, auf Stille & Tempo untersuchen,
              auf Raster schneiden. In der unteren Hälfte werden alle
              Slices mit detaillierten Eigenschaften angezeigt.
  - POOL:     Slices vorhören und gezielt per Hand freigeben (verschieben)
              in die POOL-Ordner. Enthält eine Detailansicht aller Samples,
              die in den Generator geladen werden.
  - GENERATE: Beats aus dem freigegebenen POOL erzeugen (Dynamik,
              Sequenzer, Chaos/Fraktal). Output in GENERATED_MUSIC/.
  - Einstellungen (Drum-Modus, Sidechain, Bass, Übergänge, Variationen) liegen unter GENERATE.

2. KOMMANDOZEILE (CLI)
------------------------------------------------------------------------
- Hilfe anzeigen:
    python3 ohricut_app.py hilfe
    python3 ohricut_app.py --help

- Datei verarbeiten (CUT-Schritt):
    python3 ohricut_app.py verarbeite /pfad/zur/datei.wav

- Track generieren (GENERATE-Schritt):
    python3 ohricut_app.py generiere <Modus> [takte] [bpm] [stimmung]
========================================================================
"""
    print(hilfe_text)


# ============ Pygame UI Helpers ============
REITER_NAMEN = ["CUT", "POOL", "GENERATE"]
START_ORTE = [("App", SCRIPT_DIR), ("Download", "/sdcard/Download"), ("Musik", "/sdcard/Music"), ("Speicher", "/sdcard")]


def ordner_inhalt(pfad):
    try:
        namen = sorted(os.listdir(pfad), key=str.lower)
    except OSError:
        return [], []
    ordner = [n for n in namen if not n.startswith(".") and os.path.isdir(os.path.join(pfad, n))]
    wavs = [n for n in namen if n.lower().endswith(".wav") and os.path.isfile(os.path.join(pfad, n))]
    return ordner, wavs


def lade_kandidaten(ordner_name):
    """Kandidaten aus RESULTS/<ordner>/<KAT>/ – DUBLETTEN und LEER werden nicht gelesen."""
    if not ordner_name:
        return []
    basis = os.path.join(RESULTS_DIR, ordner_name)
    out = []
    for kat in kern.KATS:
        p = os.path.join(basis, kat)
        if not os.path.isdir(p):
            continue
        for f in sorted(os.listdir(p)):
            if f.lower().endswith(".wav") and not f.startswith("."):
                out.append((kat, f, os.path.join(p, f)))
    return out


def lade_pool_dateien_fuer_kategorie(kat):
    logik.init_pool_struktur()
    p = os.path.join(POOL_DIR, kat)
    if not os.path.isdir(p):
        return []
    files = []
    for f in sorted(os.listdir(p)):
        if f.lower().endswith(".wav") and not f.startswith("."):
            files.append((f, os.path.join(p, f)))
    return files


def lade_aktive_generator_pool_details():
    """Bausteine der Auswahl (auswahl_generator.json) mit Analysewerten aus dem Pool-Cache.
    Die vier Drum-Kategorien haben je zwei feste Plätze (oben Primär, unten Sekundär), leere Plätze
    erscheinen als Platzhalter ohne full_path."""
    cache = logik.lese_pool_cache()
    auswahl = logik.lade_auswahl()
    samples = []
    for kat in kern.POOL_KATS:
        eintraege = {e.get("file"): e for e in cache.get(kat, [])}
        rels = list(auswahl.get(kat, []))
        if kat in logik.DRUM_KATS:
            rollen = logik.DRUM_ROLLEN[kat]
            rels = (rels + [None] * logik.DRUM_PLAETZE)[:logik.DRUM_PLAETZE]
        else:
            rollen = [None] * len(rels)
        for rel, rolle in zip(rels, rollen):
            if rel is None:
                samples.append({"file": "", "cat": kat, "rolle": rolle, "full_path": None})
                continue
            name = os.path.basename(rel)
            e = dict(eintraege.get(name, {"file": name}))
            e["cat"] = kat
            e["rolle"] = rolle
            e["full_path"] = os.path.join(POOL_DIR, rel)
            samples.append(e)
    return samples


def kuerzen(t, n):
    return t if len(t) <= n else "..." + t[-(n - 3):]


def kat_anzeige(kat):
    """Anzeigename einer Kategorie. Nur für die Oberfläche; Ordner und interne Namen bleiben unverändert."""
    return "SNARE/CLAP" if kat == "SNARE_CLAP" else kat


def format_generator_zeile(item):
    """[KATEGORIE] Rolle: Dateiname | Länge | Tonart. Die Rolle steht nur bei Drum-Kategorien, die Tonart nur bei MELODY und VOICE."""
    kat = item.get("cat", "UNK")
    rolle = item.get("rolle")
    kopf = f"[{kat_anzeige(kat)}]" + (f" {rolle}:" if rolle else "")
    if not item.get("full_path"):
        return f"{kopf} leer" if rolle else f"{kopf}: leer"
    teile = [item.get("file", ""), f"{item.get('dauer', 0.0):.2f}s"]
    tonart = item.get("tonart")
    if kat in ("MELODY", "VOICE") and tonart and tonart != "None":
        teile.append(str(tonart))
    return f"{kopf} " + " | ".join(teile)


def passend(text, font, max_w):
    """Kürzt text am Ende mit '...', bis er in max_w Pixel passt."""
    if font.size(text)[0] <= max_w:
        return text
    while text and font.size(text + "...")[0] > max_w:
        text = text[:-1]
    return text + "..."


def spiele_audio_vorhoeren(pfad, autoplay_aktiv=True):
    if not autoplay_aktiv:
        return
    try:
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
            pygame.mixer.music.load(pfad)
            pygame.mixer.music.play()
    except Exception as ex:
        print(f"Vorhör-Fehler: {ex}")


def stoppe_audio_vorhoeren():
    try:
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
    except Exception:
        pass


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def job_freigeben(quelle, kat, meldung):
    logik.freigeben_in_pool(quelle, kat)
    melde(meldung)


def job_loeschen(kat, name):
    logik.loesche_aus_pool(kat, name)
    melde(f"Sample '{name}' gelöscht!")


# ============ Farben (Palette laut Vorgabe) ============
BG = (26, 26, 26)
PANEL = (43, 43, 43)
TEXT_LIGHT = (224, 224, 224)
TEXT_DARK = (26, 26, 26)
TEXT_MUTED = (138, 138, 138)
ACCENT_ORANGE = (230, 74, 25)
ACCENT_MINT = (0, 191, 165)
ACCENT_RED = (211, 47, 47)
ACCENT_YELLOW = (253, 216, 53)


def ui_main():
    global pygame
    import pygame as _pygame
    pygame = _pygame
    pygame.init()
    try:
        pygame.mixer.init(frequency=44100, size=-16, channels=2)
    except Exception as ex:
        print(f"Mixer Init Warnung: {ex}")

    screen = pygame.display.set_mode((0, 0))
    W, H = screen.get_size()
    if W == 0 or H == 0:
        W, H = 480, 800
        screen = pygame.display.set_mode((W, H))

    k = W / 480.0
    def S(v):
        return int(v * k)

    pygame.display.set_caption("OHRICUT v4")
    font = pygame.font.Font(None, S(30))
    small = pygame.font.Font(None, S(20))
    title_font = pygame.font.Font(None, S(36))
    clock = pygame.time.Clock()

    pad = S(10)
    gap = S(6)
    tab_h = S(40)
    zeile_h = S(34)
    sb_w = S(24)
    bericht_h = S(120)

    app_state = {
        "aktiver_reiter": "CUT",
        "autoplay": True,
        # CUT State
        "cut_dir": SCRIPT_DIR,
        "cut_scroll": 0,
        "cut_slice_scroll": 0,
        "gewaehlte_wav": None,
        "letzter_verarbeiteter_ordner": None,
        "gewaehlter_detail_slice": None,
        "cut_bericht": "Wähle eine WAV-Datei aus und drücke auf 'Verarbeiten'.",
        "verarbeitung_laeuft": False,
        # POOL State
        "pool_ansicht": "BESTAND",  # BESTAND / GENERATOR_POOL
        "pool_kat_filter": "MELODY",
        "pool_move": False,
        "pool_bestand_scroll": 0,
        "gewaehltes_pool_sample": None,
        "pool_generator_scroll": 0,
        "gewaehltes_generator_sample": None,
        # GENERATE State
        "gen_stimmung": "Entspannt",
        "gen_bpm": 125,
        "gen_takte": 32,
        "gen_scroll": 0,
        "gen_gewichte": {"motiv": 50, "phrase": 50, "trans": 30},
        "einstellungen": logik.lade_einstellungen()
    }

    zonen = {}
    sbgeo = {}
    drag_sb = {"key": None, "y0": 0}

    def btn(r, label, active=False, disabled=False, gefahr=False, sonder=None):
        """Aktiv: mint, dunkle Schrift. Inaktiv: grau, helle Schrift. Löschen: kirschrot.
        sonder: Farbe für den aktiven Zustand (nur MOVE, gelb)."""
        if gefahr:
            fill, text_col = ACCENT_RED, TEXT_LIGHT
        elif active and sonder:
            fill, text_col = sonder, TEXT_DARK
        elif active:
            fill, text_col = ACCENT_MINT, TEXT_DARK
        else:
            fill, text_col = PANEL, TEXT_LIGHT
        pygame.draw.rect(screen, fill, r, border_radius=S(6))
        if not (active or gefahr):
            pygame.draw.rect(screen, TEXT_LIGHT, r, max(1, S(2)), border_radius=S(6))
        t = small.render(label, True, text_col)
        screen.blit(t, t.get_rect(center=r.center))

    def row(y, count, h):
        bw = (W - 2 * pad - gap * (count - 1)) // count
        return [pygame.Rect(pad + i * (bw + gap), y, bw, h) for i in range(count)]

    def row_eq(y, count, h):
        """Wie row, aber Außenrand = Abstand zwischen den Knöpfen."""
        bw = (W - 2 * pad - gap * (count + 1)) // count
        return [pygame.Rect(pad + gap + i * (bw + gap), y, bw, h) for i in range(count)]

    def kat_zeilen(y, kats, h, pro_zeile=4):
        """Kategorie-Knöpfe in Zeilen zu je pro_zeile. Gibt (Liste aus (Rect, kat)) und Gesamthöhe zurück."""
        bw = (W - 2 * pad - gap * (pro_zeile + 1)) // pro_zeile
        out = []
        for idx, kat in enumerate(kats):
            z, sp = divmod(idx, pro_zeile)
            out.append((pygame.Rect(pad + gap + sp * (bw + gap), y + z * (h + gap), bw, h), kat))
        zeilen = -(-len(kats) // pro_zeile)
        return out, zeilen * h + (zeilen - 1) * gap

    def rahmen(r):
        """Hellgrauer Rahmen um ein Listenfeld (inkl. Scrollbar)."""
        pygame.draw.rect(screen, TEXT_LIGHT, r.inflate(S(4), S(4)), max(1, S(2)), border_radius=S(6))

    def zeichne_scrollbar(list_rect, scroll_pos, visible_count, total_count, key):
        if total_count <= visible_count:
            return
        bar_rect = pygame.Rect(list_rect.right - sb_w, list_rect.y, sb_w, list_rect.h)
        thumb_h = max(S(28), int(bar_rect.h * visible_count / total_count))
        max_scroll = max(1, total_count - visible_count)
        thumb_y = bar_rect.y + int((bar_rect.h - thumb_h) * scroll_pos / max_scroll)
        thumb_rect = pygame.Rect(bar_rect.x + S(2), thumb_y, bar_rect.w - S(4), thumb_h)

        pygame.draw.rect(screen, BG, bar_rect, border_radius=S(4))
        pygame.draw.rect(screen, ACCENT_YELLOW, thumb_rect, border_radius=S(4))
        sbgeo[key] = (bar_rect, thumb_rect, visible_count, total_count)

    def zeichne_bericht(zeilen):
        """Festes Berichtsfeld unten, auf allen Seiten gleich."""
        r = pygame.Rect(pad, H - bericht_h - pad, W - 2 * pad, bericht_h)
        pygame.draw.rect(screen, PANEL, r, border_radius=S(8))
        screen.blit(small.render("BERICHT", True, ACCENT_YELLOW), (r.x + S(8), r.y + S(6)))
        by = r.y + S(28)
        for zeile in zeilen:
            screen.blit(small.render(kuerzen(zeile, 56), True, TEXT_LIGHT), (r.x + S(8), by))
            by += S(16)

    def speichere_mode():
        logik.speichere_einstellungen(app_state["einstellungen"])

    leere_results()  # CUT ist immer der leere Anfang
    starte_auftrag(logik.sync_pool_cache)

    # Mausrad im CUT-Reiter: kleinerer Wert = langsamer (0.5 = zwei Rasterschritte pro Zeile)
    WHEEL_FAKTOR = 0.25
    wheel_rest = {"cut_scroll": 0.0, "cut_slice_scroll": 0.0}
    list_rect = detail_list_rect = pygame.Rect(0, 0, 0, 0)

    def wheel_zeilen(key, dy):
        wheel_rest[key] += dy * WHEEL_FAKTOR
        schritte = int(wheel_rest[key])
        wheel_rest[key] -= schritte
        return schritte

    running = True
    while running:
        screen.fill(BG)
        zonen.clear()
        sbgeo.clear()

        # Update aus dem Hintergrundauftrag
        if STATUS.get("ergebnis"):
            res = STATUS["ergebnis"]
            if isinstance(res, dict) and "ordner" in res:
                z = res.get("zusammenfassung", {}).get("kategorien", {})
                ordner_basename = os.path.basename(res['ordner'])
                try:
                    logik.setze_ziel_aus_tonart(logik.ziel_tonart(logik.sync_pool_cache()))
                except Exception as ex:
                    print(f"Tonart-Messung fehlgeschlagen: {ex}")
                app_state["letzter_verarbeiteter_ordner"] = ordner_basename
                app_state["verarbeitung_laeuft"] = False
                app_state["cut_bericht"] = (
                    f"Fertig! Ordner: {ordner_basename}\n"
                    f"Tempo: {res['bpm']} BPM | Versatz: {res['versatz_ms']} ms\n"
                    f"Slices: {res['slices']} | Leer/Stille: {res['leer']}\n"
                    f"Slices je Kat: M:{z.get('MELODY',0)} P:{z.get('PERCUSSION',0)} V:{z.get('VOICE',0)}"
                )
                if "bpm" in res and res["bpm"]:
                    app_state["gen_bpm"] = int(round(res["bpm"]))
                melde(f"Fertig: {res['slices']} Slices in RESULTS/{ordner_basename}")
            elif isinstance(res, str) and res.endswith(".wav"):
                melde(f"Fertig: Track erzeugt in {os.path.basename(res)}")
            STATUS["ergebnis"] = None

        # Verarbeitung ist ohne Ergebnis beendet: Fehler steht in der Statuszeile
        if app_state["verarbeitung_laeuft"] and not STATUS["busy"]:
            app_state["verarbeitung_laeuft"] = False
            app_state["cut_bericht"] = "Verarbeitung abgebrochen. Details siehe Status."

        # 1. Kopfzeile mit App-Titel & Autoplay Toggle
        screen.blit(title_font.render("OHRICUT v5", True, ACCENT_ORANGE), (pad, pad))
        r_autoplay = pygame.Rect(W - pad - S(130), pad, S(130), S(28))
        zonen["autoplay_toggle"] = r_autoplay
        btn(r_autoplay, f"Autoplay: {'AN' if app_state['autoplay'] else 'AUS'}", active=app_state["autoplay"])

        # 2. Reiter-Leiste
        y_tabs = pad + S(36)
        tab_rects = row(y_tabs, len(REITER_NAMEN), tab_h)
        for r, name in zip(tab_rects, REITER_NAMEN):
            zonen[("tab", name)] = r
            btn(r, name, active=(app_state["aktiver_reiter"] == name))

        # 3. Hauptbereich: zwischen Reitern und festem Berichtsfeld
        y_content = y_tabs + tab_h + pad
        bericht_y = H - bericht_h - pad
        content_rect = pygame.Rect(pad, y_content, W - 2 * pad, bericht_y - gap - y_content)
        pygame.draw.rect(screen, PANEL, content_rect, border_radius=S(8))

        akt_reiter = app_state["aktiver_reiter"]

        # ==================== REITER 1: CUT ====================
        if akt_reiter == "CUT":
            cy = content_rect.y + pad

            ort_rects = row_eq(cy, len(START_ORTE), S(28))
            for r, (label, pfad) in zip(ort_rects, START_ORTE):
                zonen[("cut_ort", pfad)] = r
                btn(r, label, active=(app_state["cut_dir"] == pfad))
            cy += S(28) + gap

            pfad_text = small.render(kuerzen(app_state["cut_dir"], 45), True, TEXT_MUTED)
            screen.blit(pfad_text, (content_rect.x + pad, cy))
            cy += S(18)

            # Oberer Dateibrowser
            ordner, wavs = ordner_inhalt(app_state["cut_dir"])
            eintraege = []
            if os.path.dirname(app_state["cut_dir"]) != app_state["cut_dir"]:
                eintraege.append(("hoch", None, ".."))
            eintraege += [("dir", os.path.join(app_state["cut_dir"], n), n + "/") for n in ordner]
            eintraege += [("wav", os.path.join(app_state["cut_dir"], n), n) for n in wavs]

            vis_count = 4
            list_h = vis_count * zeile_h
            list_rect = pygame.Rect(content_rect.x + pad, cy, content_rect.w - 2 * pad, list_h)

            max_scroll = max(0, len(eintraege) - vis_count)
            app_state["cut_scroll"] = clamp(app_state["cut_scroll"], 0, max_scroll)

            pygame.draw.rect(screen, BG, list_rect, border_radius=S(4))
            item_w = list_rect.w - (sb_w if max_scroll > 0 else 0)

            for i, (typ, ziel, name) in enumerate(eintraege[app_state["cut_scroll"]:app_state["cut_scroll"] + vis_count]):
                r = pygame.Rect(list_rect.x, list_rect.y + i * zeile_h, item_w, zeile_h - S(2))
                zonen[("cut_eintrag", app_state["cut_scroll"] + i)] = r
                ist_gewaehlt = (typ == "wav" and ziel == app_state["gewaehlte_wav"])
                pygame.draw.rect(screen, ACCENT_ORANGE if ist_gewaehlt else PANEL, r, border_radius=S(4))
                txt_col = TEXT_DARK if ist_gewaehlt else (ACCENT_MINT if typ == "dir" else TEXT_LIGHT)
                screen.blit(small.render(kuerzen(name, 38), True, txt_col), (r.x + S(8), r.y + S(6)))

            zeichne_scrollbar(list_rect, app_state["cut_scroll"], vis_count, len(eintraege), "cut_browser")
            rahmen(list_rect)
            cy += list_h + gap

            # Kandidaten aus RESULTS (nur Kategorie-Ordner, ohne DUBLETTEN/LEER)
            akt_ordner = app_state["letzter_verarbeiteter_ordner"]
            kandidaten = lade_kandidaten(akt_ordner)

            # Verarbeiten-Button: gesperrt, solange Slices in der Liste liegen oder ein Auftrag läuft
            r_verarbeiten = pygame.Rect(content_rect.x + pad, cy, content_rect.w - 2 * pad, S(36))
            wav_aktiv = app_state["gewaehlte_wav"] is not None and not STATUS["busy"] and not kandidaten
            if wav_aktiv:
                zonen["cut_verarbeiten"] = r_verarbeiten
            btn(r_verarbeiten, "VERARBEITEN", active=wav_aktiv, disabled=not wav_aktiv)
            cy += S(36) + gap

            screen.blit(small.render(f"Kandidaten ({akt_ordner or 'noch nichts verarbeitet'} - {len(kandidaten)} Stück):", True, ACCENT_YELLOW), (content_rect.x + pad, cy))
            cy += S(18)

            move_h = S(36)
            _, move_total = kat_zeilen(0, kern.POOL_KATS, move_h)
            detail_h = content_rect.bottom - cy - pad - move_total - gap
            detail_list_rect = pygame.Rect(content_rect.x + pad, cy, content_rect.w - 2 * pad, max(S(60), detail_h))
            vis_details = max(1, detail_list_rect.h // zeile_h)

            max_slice_scroll = max(0, len(kandidaten) - vis_details)
            app_state["cut_slice_scroll"] = clamp(app_state["cut_slice_scroll"], 0, max_slice_scroll)

            pygame.draw.rect(screen, BG, detail_list_rect, border_radius=S(4))
            detail_item_w = detail_list_rect.w - (sb_w if max_slice_scroll > 0 else 0)

            if not kandidaten:
                hinweis = "Keine Kandidaten. Verarbeite zuerst eine WAV-Datei." if not akt_ordner else "Keine Kandidaten in diesem Ordner."
                screen.blit(small.render(hinweis, True, TEXT_MUTED), (detail_list_rect.x + S(8), detail_list_rect.y + S(12)))
            else:
                for i, (kat, f_name, f_full) in enumerate(kandidaten[app_state["cut_slice_scroll"]:app_state["cut_slice_scroll"] + vis_details]):
                    r = pygame.Rect(detail_list_rect.x, detail_list_rect.y + i * zeile_h, detail_item_w, zeile_h - S(2))
                    zonen[("cut_select_detail_slice", f_full)] = r
                    ist_gewaehlt = (app_state["gewaehlter_detail_slice"] == f_full)
                    pygame.draw.rect(screen, ACCENT_ORANGE if ist_gewaehlt else PANEL, r, border_radius=S(4))
                    screen.blit(small.render(kuerzen(f"{kat}/{f_name}", 40), True, TEXT_DARK if ist_gewaehlt else TEXT_LIGHT), (r.x + S(6), r.y + S(6)))

            zeichne_scrollbar(detail_list_rect, app_state["cut_slice_scroll"], vis_details, len(kandidaten), "cut_slice_details")
            rahmen(detail_list_rect)

            # Verschieben-Knöpfe unter der Kandidatenliste (orange, wenn ein Kandidat gewählt ist)
            cy = detail_list_rect.bottom + gap
            verschiebe_rects, _ = kat_zeilen(cy, kern.POOL_KATS + [None, "LEEREN"], move_h)
            kandidat_gewaehlt = app_state["gewaehlter_detail_slice"] is not None
            for r, kat in verschiebe_rects:
                if kat is None:
                    continue
                if kat == "LEEREN":
                    leeren_aktiv = akt_ordner is not None and not STATUS["busy"]
                    if leeren_aktiv:
                        zonen["cut_leeren"] = r
                    btn(r, "Liste leeren", gefahr=leeren_aktiv)
                    continue
                zonen[("cut_verschiebe", kat)] = r
                btn(r, f"{kat_anzeige(kat)}", active=kandidat_gewaehlt)

        # ==================== REITER 2: POOL ====================
        elif akt_reiter == "POOL":
            cy = content_rect.y + pad

            ansicht_rects = row_eq(cy, 2, S(30))
            zonen[("pool_ansicht", "BESTAND")] = ansicht_rects[0]
            zonen[("pool_ansicht", "GENERATOR_POOL")] = ansicht_rects[1]
            btn(ansicht_rects[0], "1. Pool-Bestand (LIBRARY)", active=(app_state["pool_ansicht"] == "BESTAND"))
            btn(ansicht_rects[1], "2. Generator Pool", active=(app_state["pool_ansicht"] == "GENERATOR_POOL"))
            cy += S(30) + pad

            if app_state["pool_ansicht"] == "BESTAND":
                kat_rects, kat_h = kat_zeilen(cy, kern.POOL_KATS + ["MOVE"], S(30))
                for r, kat in kat_rects:
                    if kat == "MOVE":
                        zonen["pool_move"] = r
                        btn(r, "MOVE", active=app_state["pool_move"], sonder=ACCENT_YELLOW)
                        continue
                    zonen[("pool_kat_filter", kat)] = r
                    btn(r, kat_anzeige(kat), active=(app_state["pool_kat_filter"] == kat))
                    if app_state["pool_move"]:
                        pygame.draw.rect(screen, ACCENT_YELLOW, r, max(2, S(3)), border_radius=S(6))
                cy += kat_h + pad

                pool_dateien = lade_pool_dateien_fuer_kategorie(app_state["pool_kat_filter"])
                screen.blit(small.render(f"Pool-Inhalt in '{kat_anzeige(app_state['pool_kat_filter'])}' ({len(pool_dateien)} Dateien):", True, TEXT_MUTED), (content_rect.x + pad, cy))
                cy += S(18)

                vis_bestand = 7
                bestand_h = vis_bestand * zeile_h
                bestand_list_rect = pygame.Rect(content_rect.x + pad, cy, content_rect.w - 2 * pad, bestand_h)
                max_scroll_bestand = max(0, len(pool_dateien) - vis_bestand)
                app_state["pool_bestand_scroll"] = clamp(app_state["pool_bestand_scroll"], 0, max_scroll_bestand)

                pygame.draw.rect(screen, BG, bestand_list_rect, border_radius=S(4))
                bestand_item_w = bestand_list_rect.w - (sb_w if max_scroll_bestand > 0 else 0)

                for i, (f_name, f_full) in enumerate(pool_dateien[app_state["pool_bestand_scroll"]:app_state["pool_bestand_scroll"] + vis_bestand]):
                    r = pygame.Rect(bestand_list_rect.x, bestand_list_rect.y + i * zeile_h, bestand_item_w, zeile_h - S(2))
                    zonen[("pool_select_bestand_sample", f_name, f_full)] = r
                    ist_gewaehlt = (app_state["gewaehltes_pool_sample"] and app_state["gewaehltes_pool_sample"][1] == f_full)
                    pygame.draw.rect(screen, ACCENT_ORANGE if ist_gewaehlt else PANEL, r, border_radius=S(4))
                    screen.blit(small.render(kuerzen(f_name, 38), True, TEXT_DARK if ist_gewaehlt else TEXT_LIGHT), (r.x + S(8), r.y + S(6)))

                zeichne_scrollbar(bestand_list_rect, app_state["pool_bestand_scroll"], vis_bestand, len(pool_dateien), "pool_bestand")
                rahmen(bestand_list_rect)
                cy += bestand_h + pad

                sample_gewaehlt = app_state["gewaehltes_pool_sample"] is not None
                r_auswahl = pygame.Rect(content_rect.x + pad, cy, content_rect.w - 2 * pad, S(38))
                zonen["pool_zur_auswahl"] = r_auswahl
                btn(r_auswahl, "Zur Auswahl (Generator)", active=sample_gewaehlt)
                cy += S(38) + gap
                r_loeschen = pygame.Rect(content_rect.x + pad, cy, content_rect.w - 2 * pad, S(38))
                zonen["pool_sample_loeschen"] = r_loeschen
                btn(r_loeschen, "Aus Pool entfernen / löschen", disabled=not sample_gewaehlt, gefahr=True)

            else:
                # GENERATOR POOL: Auswahl für den Generator
                gen_samples = lade_aktive_generator_pool_details()
                n_belegt = sum(1 for g in gen_samples if g.get("full_path"))
                screen.blit(small.render(f"Aktive Generator Pool-Samples ({n_belegt} Stück):", True, ACCENT_YELLOW), (content_rect.x + pad, cy))
                cy += S(20)

                gen_h = content_rect.bottom - cy - pad - S(38) - gap
                gen_list_rect = pygame.Rect(content_rect.x + pad, cy, content_rect.w - 2 * pad, max(S(60), gen_h))
                vis_gen = max(1, gen_list_rect.h // zeile_h)

                max_scroll_gen = max(0, len(gen_samples) - vis_gen)
                app_state["pool_generator_scroll"] = clamp(app_state["pool_generator_scroll"], 0, max_scroll_gen)

                pygame.draw.rect(screen, BG, gen_list_rect, border_radius=S(4))
                gen_item_w = gen_list_rect.w - (sb_w if max_scroll_gen > 0 else 0)

                if gen_samples:
                    for i, g_item in enumerate(gen_samples[app_state["pool_generator_scroll"]:app_state["pool_generator_scroll"] + vis_gen]):
                        r = pygame.Rect(gen_list_rect.x, gen_list_rect.y + i * zeile_h, gen_item_w, zeile_h - S(2))
                        if not g_item.get("full_path"):
                            pygame.draw.rect(screen, PANEL, r, border_radius=S(4))
                            screen.blit(small.render(passend(format_generator_zeile(g_item), small, r.w - S(12)), True, TEXT_MUTED), (r.x + S(6), r.y + S(6)))
                            continue
                        zonen[("pool_select_generator_sample", g_item.get("full_path"))] = r
                        ist_gewaehlt = (app_state["gewaehltes_generator_sample"] == g_item.get("full_path"))
                        pygame.draw.rect(screen, ACCENT_ORANGE if ist_gewaehlt else PANEL, r, border_radius=S(4))
                        fmt_text = passend(format_generator_zeile(g_item), small, r.w - S(12))
                        screen.blit(small.render(fmt_text, True, TEXT_DARK if ist_gewaehlt else TEXT_LIGHT), (r.x + S(6), r.y + S(6)))

                zeichne_scrollbar(gen_list_rect, app_state["pool_generator_scroll"], vis_gen, len(gen_samples), "pool_generator")
                rahmen(gen_list_rect)
                r_entf = pygame.Rect(content_rect.x + pad, gen_list_rect.bottom + gap, content_rect.w - 2 * pad, S(38))
                zonen["gen_aus_auswahl"] = r_entf
                btn(r_entf, "Aus Auswahl entfernen", disabled=app_state["gewaehltes_generator_sample"] is None, gefahr=True)

        # ==================== REITER 3: GENERATE ====================
        elif akt_reiter == "GENERATE":
            e = app_state["einstellungen"]
            screen.set_clip(content_rect)
            cy = content_rect.y + pad - app_state["gen_scroll"]

            screen.blit(font.render("GENERATE: Erzeugung", True, ACCENT_YELLOW), (content_rect.x + pad, cy))
            cy += S(30)

            # Einstellungen (früher MODE-Reiter), unter dem Generate-Knopf
            screen.blit(small.render("Drum-Modus:", True, ACCENT_YELLOW), (content_rect.x + pad, cy))
            cy += S(22)
            dm_rects = row(cy, 3, S(32))
            for r, dm in zip(dm_rects, ["straight", "break", "shuffle"]):
                zonen[("mode_val", "drum_modus", dm)] = r
                btn(r, dm, active=(e.get("drum_modus") == dm))
            cy += S(38)


            screen.blit(small.render("Stimmung:", True, ACCENT_YELLOW), (content_rect.x + pad, cy))
            cy += S(20)
            stimmungen = ["Energetisch", "Entspannt", "Minimal"]
            for r, st in zip(row(cy, 3, S(32)), stimmungen):
                zonen[("gen_stimmung", st)] = r
                btn(r, st, active=(app_state["gen_stimmung"] == st))
            cy += S(38)

            screen.blit(small.render(f"BPM ({app_state['gen_bpm']}) & Takte ({app_state['gen_takte']}):", True, ACCENT_YELLOW), (content_rect.x + pad, cy))
            cy += S(20)

            bpm_rects = row(cy, 5, S(32))
            bpm_labels = ["-10", "-1", f"{app_state['gen_bpm']}", "+1", "+10"]
            bpm_cmds = [-10, -1, 0, 1, 10]
            for r, lab, cmd in zip(bpm_rects, bpm_labels, bpm_cmds):
                if cmd != 0:
                    zonen[("gen_bpm_change", cmd)] = r
                    btn(r, lab)
                else:
                    pygame.draw.rect(screen, PANEL, r, border_radius=S(6))
                    t = small.render(lab, True, TEXT_LIGHT)
                    screen.blit(t, t.get_rect(center=r.center))
            cy += S(38)

            takt_rects = row(cy, 3, S(32))
            for r, t_val in zip(takt_rects, [16, 32, 64]):
                zonen[("gen_takte", t_val)] = r
                btn(r, f"{t_val} Takte", active=(app_state["gen_takte"] == t_val))
            cy += S(42)

            cy += S(8)

            screen.blit(small.render("Sidechain Ducking:", True, ACCENT_YELLOW), (content_rect.x + pad, cy))
            cy += S(22)
            sc_rects = row(cy, 3, S(32))
            for r, sc in zip(sc_rects, ["soft", "mid", "hard"]):
                zonen[("mode_val", "sidechain", sc)] = r
                btn(r, f"{sc} ({logik.SIDECHAIN_DB[sc]}dB)", active=(e.get("sidechain") == sc))
            cy += S(38)

            screen.blit(small.render("Bass Synthesizer & Samples:", True, ACCENT_YELLOW), (content_rect.x + pad, cy))
            cy += S(22)
            r_bsynth = pygame.Rect(content_rect.x + pad, cy, S(180), S(32))
            zonen[("mode_bool", "bass_synth")] = r_bsynth
            btn(r_bsynth, f"Bass Synth: {'AN' if e.get('bass_synth', True) else 'AUS'}", active=e.get('bass_synth', True))
            r_grund = pygame.Rect(content_rect.x + pad + S(190), cy, S(120), S(32))
            r_modus = pygame.Rect(content_rect.x + pad + S(320), cy, S(120), S(32))
            zonen[("ziel", "grundton")] = r_grund
            zonen[("ziel", "modus")] = r_modus
            btn(r_grund, f"Grundton: {kern.TONART_NAMEN[logik.ZIEL['grund']]}", active=True)
            btn(r_modus, f"Modus: {logik.ZIEL['modus']}", active=True)
            cy += S(38)

            screen.blit(small.render("Bass Synth Klangart:", True, TEXT_MUTED), (content_rect.x + pad, cy))
            cy += S(18)
            klangarten = ["saegeszahn", "saettigung", "slap", "flaechig"]
            ka_rects = row_eq(cy, 4, S(32))
            for r, ka in zip(ka_rects, klangarten):
                zonen[("mode_val", "bass_synth_klangart", ka)] = r
                btn(r, ka[:8], active=(e.get("bass_synth_klangart") == ka))
            cy += S(38)

            screen.blit(small.render("Übergänge & Fills:", True, ACCENT_YELLOW), (content_rect.x + pad, cy))
            cy += S(22)
            r_umel = pygame.Rect(content_rect.x + pad, cy, S(180), S(32))
            r_udrum = pygame.Rect(content_rect.x + pad + S(190), cy, S(180), S(32))
            zonen[("mode_bool", "uebergang_melodie")] = r_umel
            zonen[("mode_bool", "uebergang_drums")] = r_udrum
            btn(r_umel, f"Üb. Melodie: {'AN' if e.get('uebergang_melodie', True) else 'AUS'}", active=e.get('uebergang_melodie', True))
            btn(r_udrum, f"Üb. Drums: {'AN' if e.get('uebergang_drums', True) else 'AUS'}", active=e.get('uebergang_drums', True))
            cy += S(38)

            screen.blit(small.render("Variations-Regler (0 bis 5):", True, ACCENT_YELLOW), (content_rect.x + pad, cy))
            cy += S(22)

            for var_key, var_label in [("voice_variation", "Voice Variation"), ("melodie_variation", "Melodie Variation")]:
                val = e.get(var_key, 0)
                screen.blit(small.render(f"{var_label}: {val}", True, TEXT_LIGHT), (content_rect.x + pad, cy + S(6)))
                for idx_v in range(6):
                    r_shifted = pygame.Rect(content_rect.x + S(160) + idx_v * S(42), cy, S(36), S(28))
                    zonen[("mode_val", var_key, idx_v)] = r_shifted
                    btn(r_shifted, str(idx_v), active=(val == idx_v))
                cy += S(34)

            cy += S(10)
            r_generate = pygame.Rect(content_rect.x + pad, cy, content_rect.w - 2 * pad, S(48))
            zonen["gen_start"] = r_generate
            gen_bereit = not STATUS["busy"]
            btn(r_generate, "BEAT GENERIEREN (aus POOL/)", active=gen_bereit, disabled=not gen_bereit)
            cy += S(48) + gap

            screen.set_clip(None)
            gen_hoehe = cy + app_state["gen_scroll"] - (content_rect.y + pad)
            app_state["gen_scroll"] = clamp(app_state["gen_scroll"], 0, max(0, gen_hoehe - content_rect.h + pad))
            zeichne_scrollbar(content_rect, app_state["gen_scroll"], content_rect.h, gen_hoehe + pad, "gen")

        # 4. Festes Berichtsfeld unten (Status + Ergebnisse, auf jeder Seite gleich)
        zeichne_bericht([STATUS["text"]] + app_state["cut_bericht"].split("\n"))

        pygame.display.flip()

        # Input Events
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                stoppe_audio_vorhoeren()
                running = False

            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                pos = ev.pos

                sb_hit = [key for key, geo in sbgeo.items() if geo[0].collidepoint(pos)]
                if sb_hit:
                    drag_sb["key"] = sb_hit[0]
                    drag_sb["y0"] = pos[1]
                    continue

                hit = [key for key, r in zonen.items() if r.collidepoint(pos) and (
                    key == "autoplay_toggle" or (isinstance(key, tuple) and key[0] == "tab")
                    or content_rect.collidepoint(pos))]
                if hit:
                    key = hit[0]
                    if key == "autoplay_toggle":
                        app_state["autoplay"] = not app_state["autoplay"]
                        if not app_state["autoplay"]:
                            stoppe_audio_vorhoeren()

                    elif isinstance(key, tuple) and key[0] == "tab":
                        app_state["aktiver_reiter"] = key[1]
                        stoppe_audio_vorhoeren()

                    # CUT Actions
                    elif isinstance(key, tuple) and key[0] == "cut_ort":
                        app_state["cut_dir"] = key[1]
                        app_state["cut_scroll"] = 0

                    elif isinstance(key, tuple) and key[0] == "cut_eintrag":
                        ordner, wavs = ordner_inhalt(app_state["cut_dir"])
                        eintr = ([("hoch", None)] if os.path.dirname(app_state["cut_dir"]) != app_state["cut_dir"] else [])
                        eintr += [("dir", os.path.join(app_state["cut_dir"], n)) for n in ordner]
                        eintr += [("wav", os.path.join(app_state["cut_dir"], n)) for n in wavs]

                        idx = key[1]
                        if idx < len(eintr):
                            typ, ziel = eintr[idx]
                            if typ == "hoch":
                                app_state["cut_dir"] = os.path.dirname(app_state["cut_dir"])
                                app_state["cut_scroll"] = 0
                                stoppe_audio_vorhoeren()
                            elif typ == "dir":
                                app_state["cut_dir"] = ziel
                                app_state["cut_scroll"] = 0
                                stoppe_audio_vorhoeren()
                            else:
                                app_state["gewaehlte_wav"] = ziel
                                app_state["cut_bericht"] = f"Gewählt: {os.path.basename(ziel)}\nMit 'Verarbeiten' starten."
                                spiele_audio_vorhoeren(ziel, autoplay_aktiv=app_state["autoplay"])

                    elif isinstance(key, tuple) and key[0] == "cut_select_detail_slice":
                        app_state["gewaehlter_detail_slice"] = key[1]
                        spiele_audio_vorhoeren(key[1], autoplay_aktiv=app_state["autoplay"])

                    elif isinstance(key, tuple) and key[0] == "cut_verschiebe":
                        kat = key[1]
                        gew = app_state["gewaehlter_detail_slice"]
                        if gew:
                            stoppe_audio_vorhoeren()
                            if starte_auftrag(job_freigeben, gew, kat, f"Kandidat nach POOL/{kat}/ verschoben!"):
                                app_state["gewaehlter_detail_slice"] = None

                    elif key == "cut_leeren":
                        stoppe_audio_vorhoeren()
                        leere_results()
                        app_state["letzter_verarbeiteter_ordner"] = None
                        app_state["gewaehlter_detail_slice"] = None
                        app_state["cut_slice_scroll"] = 0
                        app_state["cut_bericht"] = "Liste geleert. Wähle eine WAV-Datei und drücke auf 'Verarbeiten'."
                        melde("Liste geleert")

                    elif key == "cut_verarbeiten":
                        wav = app_state["gewaehlte_wav"]
                        if wav and not os.path.abspath(wav).startswith(os.path.abspath(RESULTS_DIR) + os.sep):
                            stoppe_audio_vorhoeren()
                            app_state["letzter_verarbeiteter_ordner"] = None
                            app_state["gewaehlter_detail_slice"] = None
                            melde("Verarbeitung gestartet...")
                            app_state["verarbeitung_laeuft"] = True
                            app_state["cut_bericht"] = f"Läuft: {os.path.basename(wav)}\nBitte warten ..."
                            starte_auftrag(
                                lambda w, m: kern.verarbeite(w, m, results_dir=RESULTS_DIR),
                                wav, melde
                            )

                    # POOL Actions
                    elif isinstance(key, tuple) and key[0] == "pool_ansicht":
                        app_state["pool_ansicht"] = key[1]
                        app_state["pool_move"] = False
                        if key[1] == "GENERATOR_POOL":
                            starte_auftrag(logik.sync_pool_cache)
                        stoppe_audio_vorhoeren()

                    elif key == "pool_move":
                        if app_state["pool_move"]:
                            app_state["pool_move"] = False
                            melde("Verschieben abgebrochen")
                        elif app_state["gewaehltes_pool_sample"] is None:
                            melde("Erst einen Slice markieren")
                        else:
                            app_state["pool_move"] = True
                            melde("Ziel-Kategorie antippen")

                    elif isinstance(key, tuple) and key[0] == "pool_kat_filter" and app_state["pool_move"]:
                        sample = app_state["gewaehltes_pool_sample"]
                        rel = f"{app_state['pool_kat_filter']}/{sample[0]}"
                        try:
                            logik.verschiebe_in_pool(rel, key[1])
                            melde(f"Verschoben nach {key[1]}")
                            app_state["pool_move"] = False
                            app_state["gewaehltes_pool_sample"] = None
                            stoppe_audio_vorhoeren()
                        except ValueError as ex:
                            melde(str(ex))

                    elif isinstance(key, tuple) and key[0] == "pool_kat_filter":
                        app_state["pool_kat_filter"] = key[1]
                        app_state["pool_bestand_scroll"] = 0
                        app_state["gewaehltes_pool_sample"] = None
                        stoppe_audio_vorhoeren()

                    elif isinstance(key, tuple) and key[0] == "pool_select_bestand_sample":
                        app_state["gewaehltes_pool_sample"] = (key[1], key[2])
                        spiele_audio_vorhoeren(key[2], autoplay_aktiv=app_state["autoplay"])

                    elif isinstance(key, tuple) and key[0] == "pool_select_generator_sample":
                        app_state["gewaehltes_generator_sample"] = key[1]
                        spiele_audio_vorhoeren(key[1], autoplay_aktiv=app_state["autoplay"])

                    elif key == "pool_sample_loeschen":
                        sample = app_state["gewaehltes_pool_sample"]
                        if sample:
                            stoppe_audio_vorhoeren()
                            if starte_auftrag(job_loeschen, app_state["pool_kat_filter"], sample[0]):
                                app_state["gewaehltes_pool_sample"] = None

                    elif key == "pool_zur_auswahl":
                        sample = app_state["gewaehltes_pool_sample"]
                        if sample:
                            try:
                                logik.auswahl_hinzufuegen(f"{app_state['pool_kat_filter']}/{sample[0]}")
                                melde(f"'{sample[0]}' zur Auswahl hinzugefügt")
                            except ValueError as ex:
                                melde(str(ex))

                    elif key == "gen_aus_auswahl":
                        voll = app_state["gewaehltes_generator_sample"]
                        if voll:
                            try:
                                logik.auswahl_entfernen(os.path.relpath(voll, POOL_DIR).replace(os.sep, "/"))
                                melde("Aus der Auswahl entfernt")
                                app_state["gewaehltes_generator_sample"] = None
                            except ValueError as ex:
                                melde(str(ex))

                    # GENERATE Actions
                    elif isinstance(key, tuple) and key[0] == "gen_stimmung":
                        app_state["gen_stimmung"] = key[1]

                    elif isinstance(key, tuple) and key[0] == "gen_bpm_change":
                        app_state["gen_bpm"] = clamp(app_state["gen_bpm"] + key[1], 40, 240)

                    elif isinstance(key, tuple) and key[0] == "gen_takte":
                        app_state["gen_takte"] = key[1]

                    elif key == "gen_start":
                        stoppe_audio_vorhoeren()
                        melde("Generierung gestartet...")
                        starte_auftrag(
                            logik.generiere_track,
                            app_state["gen_bpm"],
                            app_state["gen_takte"],
                            app_state["gen_stimmung"],
                        )

                    # Einstellungen (unter GENERATE)
                    elif key == ("ziel", "grundton"):
                        logik.setze_ziel(grund=logik.ZIEL["grund"] + 1)
                    elif key == ("ziel", "modus"):
                        logik.setze_ziel(modus="Moll" if logik.ZIEL["modus"] == "Dur" else "Dur")

                    elif isinstance(key, tuple) and key[0] == "mode_bool":
                        var = key[1]
                        app_state["einstellungen"][var] = not app_state["einstellungen"].get(var, True)
                        speichere_mode()

                    elif isinstance(key, tuple) and key[0] == "mode_val":
                        var = key[1]
                        val = key[2]
                        app_state["einstellungen"][var] = val
                        speichere_mode()

            elif ev.type == pygame.MOUSEMOTION and drag_sb["key"]:
                sb_key = drag_sb["key"]
                if sb_key in sbgeo:
                    bar_r, _, vis, tot = sbgeo[sb_key]
                    f = clamp((ev.pos[1] - bar_r.y) / max(1, bar_r.h), 0, 1)
                    max_sc = max(0, tot - vis)

                    if sb_key == "cut_browser":
                        app_state["cut_scroll"] = int(round(f * max_sc))
                    elif sb_key == "cut_slice_details":
                        app_state["cut_slice_scroll"] = int(round(f * max_sc))
                    elif sb_key == "pool_bestand":
                        app_state["pool_bestand_scroll"] = int(round(f * max_sc))
                    elif sb_key == "pool_generator":
                        app_state["pool_generator_scroll"] = int(round(f * max_sc))
                    elif sb_key == "gen":
                        app_state["gen_scroll"] = int(round(f * max_sc))

            elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                drag_sb["key"] = None

            elif ev.type == pygame.MOUSEWHEEL:
                if app_state["aktiver_reiter"] == "GENERATE":
                    app_state["gen_scroll"] = max(0, app_state["gen_scroll"] - ev.y * S(40))
                elif app_state["aktiver_reiter"] == "CUT":
                    maus = pygame.mouse.get_pos()
                    if list_rect.collidepoint(maus):
                        app_state["cut_scroll"] -= wheel_zeilen("cut_scroll", ev.y)
                    elif detail_list_rect.collidepoint(maus):
                        app_state["cut_slice_scroll"] -= wheel_zeilen("cut_slice_scroll", ev.y)
                elif app_state["aktiver_reiter"] == "POOL":
                    if app_state["pool_ansicht"] == "BESTAND":
                        app_state["pool_bestand_scroll"] -= ev.y
                    else:
                        app_state["pool_generator_scroll"] -= ev.y

        clock.tick(20)

    pygame.quit()

if __name__ == "__main__":
    args = sys.argv[1:]

    if not args:
        ui_main()
    elif args[0] in ("hilfe", "--help", "-h", "help", "/?"):
        zeige_hilfe()
    elif args[0] == "verarbeite":
        if len(args) < 2:
            print("Fehler: Bitte eine WAV-Datei angeben.")
            sys.exit(1)
        wav_pfad = args[1]
        if not os.path.isfile(wav_pfad):
            print(f"Fehler: Datei '{wav_pfad}' nicht gefunden.")
            sys.exit(1)

        def meldung(text):
            print(f"[*] {text}")

        try:
            res = kern.verarbeite(wav_pfad, meldung, results_dir=RESULTS_DIR)
            print("\nProcessing erfolgreich abgeschlossen:")
            print(f"  Ordner:     {res['ordner']}")
            print(f"  BPM:        {res['bpm']}")
            print(f"  Versatz:    {res['versatz_ms']} ms")
            print(f"  Slices:     {res['slices']}")
            print(f"  Leer:       {res['leer']}")
        except Exception as ex:
            print(f"Fehler bei der Verarbeitung: {ex}")
            traceback.print_exc()
            sys.exit(1)

    elif args[0] == "generiere":
        # args[1] (Modus) wird nicht mehr ausgewertet, der Generator kennt keine Modi mehr.
        try:
            takte = int(args[2]) if len(args) > 2 else 32
            bpm = int(args[3]) if len(args) > 3 else 125
        except ValueError:
            print("Fehler: Takte und BPM müssen ganze Zahlen sein, z. B.: generiere Dynamik 32 125")
            sys.exit(1)
        stimmung = args[4] if len(args) > 4 else "Energetisch"

        print(f"[*] Generiere Track ({takte} Takte, {bpm} BPM, Stimmung: {stimmung})...")
        try:
            pfad = logik.generiere_track(bpm=bpm, takte=takte, stimmung=stimmung)
        except ValueError as ex:
            print(f"Ungültige Eingabe: {ex}")
            sys.exit(1)
        except Exception as ex:
            print(f"Fehler bei der Generierung: {ex}")
            traceback.print_exc()
            sys.exit(1)
        print(f"[+] Track erfolgreich generiert: {pfad}")
    else:
        print(f"Unbekannter Befehl: {args[0]}")
        zeige_hilfe()
        sys.exit(1)
