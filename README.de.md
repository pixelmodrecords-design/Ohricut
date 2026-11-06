# OHRICUT

[English](README.md) | **Deutsch**

OHRICUT ist ein Python-Werkzeug zum Erstellen von Beats und Loops aus eigenem WAV-Audiomaterial. Die Anwendung verbindet eine Sample-Aufbereitungs-Pipeline mit einer manuellen Sample-Bibliothek und einem regelbasierten Beat-Generator.

Die Anwendung gliedert sich in folgende Module und Komponenten:

- `ohricut_app.py` – grafische Benutzeroberfläche (Pygame) und Kommandozeile (CLI) im Stammverzeichnis
- `src/ohricut_kern.py` – WAV-I/O, Audioanalyse, Slice-Erstellung und Signalverarbeitung
- `src/ohricut_logik.py` – Sample-Pool, Auswahl, Cache, Einstellungen und Musikgenerierung
- `src/ohricut_i18n.py` – Zentrale Sprachverwaltung (Internationalisierung / I18n)
- `src/de.json` & `src/en.json` – Sprachdateien für Deutsch und Englisch

## Zweisprachigkeit (Deutsch / Englisch)

OHRICUT ist vollständig zweisprachig:
- **Standardsprache:** Englisch (`en`) bei Erststart bzw. Neuinstallation.
- **Sprachumschalter:** Direkt in der GUI-Kopfzeile (`Language: EN` / `Sprache: DE`) mit sofortiger Umschaltung zur Laufzeit.
- **Persistierung:** Die gewählte Sprache wird dauerhaft in `ohricut_einstellungen.json` gespeichert.
- **CLI & Stimmungen:** Die Kommandozeile spricht primär Englisch (`process`, `generate`, `help`) und unterstützt weiterhin alle deutschen Alias-Befehle (`verarbeite`, `generiere`, `hilfe`) sowie deutsche und englische Stimmungsbezeichnungen (`Energetic` / `Energetisch`, `Relaxed` / `Entspannt`, `Minimal`).

## Funktionen

### CUT – Audiomaterial vorbereiten

- WAV-Dateien aus dem Dateisystem auswählen
- Audiomaterial auf Tempo und Versatz untersuchen
- Stille Bereiche erkennen und beim Aufteilen berücksichtigen
- Material in einzelne Slices zerlegen und analysieren
- Kandidaten nach Kategorien sortieren und Dubletten bzw. leere oder problematische Slices kennzeichnen

### POOL – Sample-Bibliothek verwalten

- Geeignete Slices manuell in die Sample-Bibliothek übernehmen
- Samples nach Kategorien organisieren: `KICK`, `HIHAT`, `PERC`, `SNARE_CLAP`, `MELODY` und `VOICE`
- Samples vorhören und bei Bedarf zwischen Kategorien verschieben oder löschen
- Den Bestand unabhängig von der aktiven Generator-Auswahl verwalten

Die automatische Kategorisierung liefert Vorschläge. Die Entscheidung, welche Samples tatsächlich in die Bibliothek bzw. in die Generator-Auswahl gelangen, bleibt beim Nutzer.

### GENERATE – Beats erzeugen

- Tracks aus den ausdrücklich ausgewählten Pool-Samples generieren
- Drum-Modi, Sidechain, Bass-Synthese, Variationen und Übergänge konfigurieren
- Stimmung, Tempo und Tracklänge festlegen
- Das Ergebnis als WAV-Datei ausgeben

Die Generator-Auswahl wird in `auswahl_generator.json` gespeichert. Die Einstellungen liegen in `ohricut_einstellungen.json`; der Sample-Analyse-Cache liegt unter `POOL/pool_cache.json`.

## Voraussetzungen

- Python 3
- NumPy
- Pygame für die grafische Oberfläche

Die Audioverarbeitung verwendet ansonsten Python-Standardbibliotheken. Pygame wird verzögert importiert: Die CLI-Befehle für Hilfe, Verarbeitung und Generierung benötigen die grafische Oberfläche nicht.

## Installation

Repository herunterladen oder klonen:

```bash
git clone https://github.com/pixelmodrecords-design/Ohricut.git
cd Ohricut
```

Abhängigkeiten installieren:

```bash
python -m pip install -r requirements.txt
```

## Start

### Grafische Oberfläche

```bash
python ohricut_app.py
```

Die Oberfläche enthält die drei Bereiche CUT, POOL und GENERATE.

### Hilfe anzeigen

```bash
python ohricut_app.py help
```

Alternativ:

```bash
python ohricut_app.py hilfe
# oder: python ohricut_app.py --help
```

## Kommandozeile

### WAV-Datei verarbeiten

```bash
python ohricut_app.py process /pfad/zur/datei.wav
```
*(Alternativ: `python ohricut_app.py verarbeite /pfad/zur/datei.wav`)*

Die Verarbeitung legt die erkannten Slices und Analyseergebnisse im Ordner `RESULTS/` ab.

### Track generieren

```bash
python ohricut_app.py generate Dynamic 32 125 Energetic
```
*(Alternativ: `python ohricut_app.py generiere Dynamik 32 125 Energetisch`)*

Argumente:

| Argument | Bedeutung | Standard |
|---|---|---|
| `Modus` / `Mode` | Historischer Platzhalter; wird vom aktuellen Generator nicht ausgewertet | – |
| `takte` / `bars` | Anzahl der Takte (8 bis 256) | `32` |
| `bpm` | Tempo (40 bis 240 BPM) | `125` |
| `stimmung` / `mood` | Generator-Stimmung (`Energetic`/`Energetisch`, `Relaxed`/`Entspannt`, `Minimal`) | `Energetic` / `Energetisch` |

Die Generierung verwendet die gespeicherte Generator-Auswahl und die vorhandenen Einstellungen. Mindestens ein verwendbares Drum-Sample muss ausgewählt sein. Die erzeugte WAV-Datei wird in `GENERATED_MUSIC/` gespeichert.

> Hinweis: Die CLI-Generierung verwendet die bestehende Pool-Auswahl. Das bloße Ablegen von WAV-Dateien im Pool bedeutet nicht automatisch, dass diese Samples für den Generator ausgewählt sind.

## Daten- und Arbeitsordner

Die Anwendung legt benötigte Arbeitsordner bei Bedarf selbst an:

| Pfad | Zweck |
|---|---|
| `RESULTS/` | Ergebnisse der CUT-Verarbeitung |
| `POOL/` | Kategorisierte Sample-Bibliothek |
| `POOL/pool_cache.json` | Analyse-Cache für Pool-Samples |
| `auswahl_generator.json` | Aktive Sample-Auswahl für den Generator |
| `ohricut_einstellungen.json` | Gespeicherte Generator-Einstellungen |
| `GENERATED_MUSIC/` | Generierte WAV-Tracks |

Diese Arbeitsdaten werden nicht automatisch mit dem Repository synchronisiert. Sichere deine eigenen Samples, die Pool-Ordner und die JSON-Auswahl-/Einstellungsdateien separat, wenn du sie auf ein anderes Gerät übertragen möchtest.

## Unterstützte Audiodateien

Der aktuelle Import- und Verarbeitungsworkflow ist auf WAV-Dateien ausgelegt. Andere Audioformate müssen vor dem Import extern in WAV umgewandelt werden.

## Hinweise zur Plattform

OHRICUT verwendet Pygame für die grafische Oberfläche und NumPy für die Audioverarbeitung. Die Verfügbarkeit passender Pygame- und NumPy-Pakete hängt von Betriebssystem und Python-Version ab. Auf Android kann die Installation insbesondere von Pygame je nach Python-Umgebung zusätzliche Einschränkungen haben.

## Projektstatus

Dieses Repository enthält den aktuellen Python-Quellcode und das Sample-Archiv. Die Dokumentation beschreibt die Funktionen, die sich aus dem derzeitigen Code ergeben; sie ist keine Aussage über Tests auf jeder Plattform oder Python-Version.
