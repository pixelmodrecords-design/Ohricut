# OHRICUT

**English** | [Deutsch](README.de.md)

OHRICUT is a Python tool for creating beats and loops from your own WAV audio material. It combines a sample preparation pipeline, a manually managed sample library, and a rule-based beat generator.

The application is organized into the following modules and components:

- `ohricut_app.py` – graphical user interface (Pygame) and command-line interface (CLI), located in the project root
- `src/ohricut_kern.py` – WAV I/O, audio analysis, slice creation, and signal processing
- `src/ohricut_logik.py` – sample pool, selection, cache, settings, and music generation
- `src/ohricut_i18n.py` – centralized language management (internationalization / i18n)
- `src/de.json` & `src/en.json` – German and English language files

## Bilingual support (English / German)

OHRICUT is fully bilingual:
- **Default language:** English (`en`) on first launch or after a fresh installation.
- **Language switch:** Available directly in the GUI header (`Language: EN` / `Sprache: DE`), allowing the language to be switched while the application is running.
- **Persistence:** The selected language is saved in `ohricut_einstellungen.json`.
- **CLI and moods:** The command line primarily uses English commands (`process`, `generate`, `help`) and continues to support all German aliases (`verarbeite`, `generiere`, `hilfe`), as well as German and English mood names (`Energetic` / `Energetisch`, `Relaxed` / `Entspannt`, `Minimal`).

## Features

### CUT – Prepare audio material

- Select WAV files from your file system
- Analyze audio material for tempo and offset
- Detect silent sections and take them into account when splitting audio
- Split material into individual slices and analyze them
- Sort candidates into categories and flag duplicates, empty slices, and potentially problematic slices

### POOL – Manage the sample library

- Manually add suitable slices to the sample library
- Organize samples into categories: `KICK`, `HIHAT`, `PERC`, `SNARE_CLAP`, `MELODY`, and `VOICE`
- Preview samples and move them between categories or delete them when needed
- Manage the library independently of the active generator selection

Automatic categorization provides suggestions. The user remains in control of which samples are added to the library and which are included in the generator selection.

### GENERATE – Create beats

- Generate tracks from the pool samples explicitly selected for use
- Configure drum modes, sidechain, bass synthesis, variations, and transitions
- Set the mood, tempo, and track length
- Export the result as a WAV file

The generator selection is saved in `auswahl_generator.json`. Settings are stored in `ohricut_einstellungen.json`, and the sample analysis cache is located at `POOL/pool_cache.json`.

## Requirements

- Python 3
- NumPy
- Pygame for the graphical user interface

Audio processing otherwise uses Python's standard libraries. Pygame is imported only when needed, so the CLI commands for help, processing, and generation do not require the graphical interface.

## Installation

Download or clone the repository:

```bash
git clone https://github.com/pixelmodrecords-design/Ohricut.git
cd Ohricut
```

Install the dependencies:

```bash
python -m pip install -r requirements.txt
```

## Launch

### Graphical user interface

```bash
python ohricut_app.py
```

The interface contains three sections: CUT, POOL, and GENERATE.

### Display help

```bash
python ohricut_app.py help
```

Alternatively:

```bash
python ohricut_app.py hilfe
# or: python ohricut_app.py --help
```

## Command line

### Process a WAV file

```bash
python ohricut_app.py process /path/to/file.wav
```
*(Alternatively: `python ohricut_app.py verarbeite /path/to/file.wav`)*

Processing saves the detected slices and analysis results in the `RESULTS/` folder.

### Generate a track

```bash
python ohricut_app.py generate Dynamic 32 125 Energetic
```
*(Alternatively: `python ohricut_app.py generiere Dynamik 32 125 Energetisch`)*

Arguments:

| Argument | Description | Default |
|---|---|---|
| `mode` | Historical placeholder; not used by the current generator | – |
| `bars` | Number of bars (8 to 256) | `32` |
| `bpm` | Tempo (40 to 240 BPM) | `125` |
| `mood` | Generator mood (`Energetic`/`Energetisch`, `Relaxed`/`Entspannt`, `Minimal`) | `Energetic` / `Energetisch` |

Generation uses the saved generator selection and the current settings. At least one usable drum sample must be selected. The generated WAV file is saved in `GENERATED_MUSIC/`.

> Note: CLI generation uses the existing pool selection. Simply placing WAV files in the pool does not automatically make those samples available to the generator.

## Data and working folders

The application creates the required working folders automatically when needed:

| Path | Purpose |
|---|---|
| `RESULTS/` | Results from CUT processing |
| `POOL/` | Categorized sample library |
| `POOL/pool_cache.json` | Analysis cache for pool samples |
| `auswahl_generator.json` | Active sample selection for the generator |
| `ohricut_einstellungen.json` | Saved generator settings |
| `GENERATED_MUSIC/` | Generated WAV tracks |

These working files are not automatically synchronized with the repository. If you want to move your setup to another device, back up your own samples, the pool folders, and the JSON selection and settings files separately.

## Supported audio files

The current import and processing workflow is designed for WAV files. Other audio formats must be converted to WAV externally before import.

## Platform notes

OHRICUT uses Pygame for its graphical interface and NumPy for audio processing. The availability of compatible Pygame and NumPy packages depends on the operating system and Python version. On Android, installing Pygame may involve additional limitations depending on the Python environment.

## Project status

This repository contains the current Python source code and the sample archive. This documentation describes the features reflected in the current code; it does not claim that the application has been tested on every platform or Python version.
