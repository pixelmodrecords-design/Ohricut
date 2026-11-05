"""
OHRICUT Kern-Modul: Signal-Verarbeitung, Audio-I/O, Analyse und Pipeline.
"""
import os
import re
import math
import wave
import json
import shutil
import tempfile
import uuid
import hashlib
import numpy as np

# ============ Konstanten & Schwellwerte ============
SR = 44100

KATS = ["PERCUSSION", "MELODY", "VOICE"]

# Analyse-Kategorien (wie bisher, Ordner in RESULTS/<n>/)
# Pool-Kategorien: feste Ablage, vom Nutzer per Verschieben festgelegt (Step 1)
POOL_KATS = ["KICK", "HIHAT", "PERC", "SNARE_CLAP", "MELODY", "VOICE"]

DUP_THRESHOLD = 0.97      # Spektrum-Ähnlichkeit, ab der ein Slice als Dublette gilt
EMPTY_RMS = 0.003         # darunter gilt ein Slice als leer
MIN_DUR_S = 0.05          # kürzer als das -> Löschkandidat
ATTACK_RMS = 0.035        # Lautstärke der ersten 25 ms -> Anschlag
ATTACK_RATIO = 1.3        # Verhältnis Anfang zu Rest -> Anschlag
VOICE_VOICED_MIN = 0.5    # Anteil stimmhafter Frames
VOICE_PERC_MAX = 0.3      # ab dieser Stimmhaftigkeit ist Anschlag kein Drum mehr
VOICE_HARM_MAX = 0.93     # Stimmen sind etwas rauer als reine Synth-Töne
F0_MIN, F0_MAX = 100, 900 # Grundfrequenz-Bereich für Gesang

TONART_NAMEN = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

STILLE_DB = -45.0
STILLE_MIN_S = 0.3
STILLE_PUFFER_S = 0.03
PIPE_DIV = 2

LANG_VOKAL_MAX_S = 8.0
VOKAL_LUECKE_S = 0.25


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def bereinigter_ordnername(dateiname):
    """
    Bereinigt einen Dateinamen nach Abschnitt 11 des Konzepts:
    1. .wav entfernen
    2. Umlaute ersetzen (ä->ae, ö->oe, ü->ue, Ä->Ae, Ö->Oe, Ü->Ue, ß->ss)
    3. Alle Zeichen außer A-Z, a-z, 0-9 zu '_'
    4. Mehrere '_' zusammenfassen
    5. Führende und abschließende '_' entfernen
    6. Falls leer -> 'sample'
    """
    name = dateiname
    if name.lower().endswith(".wav"):
        name = name[:-4]

    ersetzungen = {
        'ä': 'ae', 'ö': 'oe', 'ü': 'ue',
        'Ä': 'Ae', 'Ö': 'Oe', 'Ü': 'Ue',
        'ß': 'ss'
    }
    for k, v in ersetzungen.items():
        name = name.replace(k, v)

    name = re.sub(r'[^A-Za-z0-9]', '_', name)
    name = re.sub(r'_+', '_', name)
    name = name.strip('_')

    if not name:
        name = "sample"

    return name


# ============ Audio I/O ============
def read_wav_mono(path):
    with wave.open(path, "rb") as wf:
        nch, sw, sr, nf = wf.getnchannels(), wf.getsampwidth(), wf.getframerate(), wf.getnframes()
        raw = wf.readframes(nf)
    if sw == 1:
        x = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128) / 128
    elif sw == 2:
        x = np.frombuffer(raw, "<i2").astype(np.float32) / 32768
    elif sw == 3:
        b = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        v[v >= 2**23] -= 2**24
        x = v.astype(np.float32) / 2**23
    elif sw == 4:
        x = np.frombuffer(raw, "<i4").astype(np.float32) / 2**31
    else:
        raise ValueError("WAV-Format nicht unterstützt")
    return x.reshape(-1, nch).mean(axis=1), sr


def write_wav(path, mono, sr=SR, chunk_size=65536):
    """Schreibt Stereo-WAV blockweise."""
    with wave.open(path, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        n = len(mono)
        for i in range(0, n, chunk_size):
            chunk = mono[i:i + chunk_size]
            stereo = np.repeat(np.clip(chunk, -1.0, 1.0)[:, None], 2, axis=1)
            pcm = (stereo * 32767).astype("<i2")
            wf.writeframes(pcm.tobytes())


def resample(x, sr_von):
    if sr_von == SR or len(x) == 0:
        return x
    n = int(len(x) * SR / sr_von)
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


def trim_leading_silence(x, sr=SR, threshold_db=-42.0,
                         max_ms=100.0, pre_roll_ms=1.5,
                         min_trim_ms=2.0):
    """Entfernt längeren leisen Vorlauf, lässt einen kurzen Sicherheitsvorlauf stehen."""
    if len(x) < 4:
        return x

    peak = float(np.max(np.abs(x)))
    if peak < 1e-6:
        return x

    block = max(1, int(sr * 0.001))
    limit = min(len(x), int(sr * max_ms / 1000))
    usable = limit // block

    if usable < 1:
        return x

    frames = x[:usable * block].reshape(-1, block)
    levels = np.sqrt(np.mean(frames ** 2, axis=1))

    threshold = max(peak * (10 ** (threshold_db / 20)), 1e-5)
    active = np.flatnonzero(levels >= threshold)

    if len(active) == 0:
        return x

    onset = int(active[0]) * block
    preroll = int(sr * pre_roll_ms / 1000)
    cut = max(0, onset - preroll)

    if cut < int(sr * min_trim_ms / 1000):
        return x

    return x[cut:].copy()


def pitch(x, halbtoene):
    if halbtoene == 0 or len(x) == 0:
        return x
    f = 2 ** (halbtoene / 12)
    n = int(len(x) / f)
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


def fade(x, ms=5):
    x = x.copy()
    f = min(int(ms * SR / 1000), len(x) // 2)
    if f > 0:
        r = np.linspace(0, 1, f, dtype=np.float32)
        x[:f] *= r
        x[-f:] *= r[::-1]
    return x


def nulldurchgang_fade(x, sr=SR, max_ms=8):
    """Minimaler Schutz gegen Knackser: 0,5 ms Einsatz, maximal 3 ms Ausklang."""
    if len(x) < 4:
        return x

    x = x.copy()
    n_in = min(int(sr * 0.0005), len(x) // 2)
    n_out = min(int(sr * min(max_ms, 3.0) / 1000), len(x) // 2)

    if n_in > 0:
        x[:n_in] *= np.linspace(0, 1, n_in, dtype=np.float32)

    if n_out > 0:
        x[-n_out:] *= np.linspace(1, 0, n_out, dtype=np.float32)

    return x


def chop(x, sekunden):
    n = int(sekunden * SR)
    return nulldurchgang_fade(x[:n], SR, max_ms=15) if len(x) > n else x


def lege_ab(mix, snd, pos, db=0.0):
    if snd is None or pos < 0 or pos >= len(mix):
        return
    g = 10 ** (db / 20)
    ende = min(len(mix), pos + len(snd))
    mix[pos:ende] += snd[:ende - pos] * g


def normiere(x, ziel=0.89):
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    if peak > 0:
        x *= (ziel / peak)
    return x


def wende_sidechain_ducking_an(mix, kick_positionen, duck_db=-3.0, ms=120):
    if not kick_positionen or len(mix) == 0:
        return mix
    duck_len = int(ms * SR / 1000)
    if duck_len <= 0:
        return mix

    linear_gain = 10 ** (duck_db / 20.0)
    duck_curve = np.ones(duck_len, dtype=np.float32)
    ramp_down = int(duck_len * 0.1)
    ramp_up = duck_len - ramp_down
    if ramp_down > 0:
        duck_curve[:ramp_down] = np.linspace(1.0, linear_gain, ramp_down, dtype=np.float32)
    duck_curve[ramp_down:] = np.linspace(linear_gain, 1.0, ramp_up, dtype=np.float32)

    mix_ducked = mix.copy()
    for pos in kick_positionen:
        if pos >= len(mix_ducked):
            continue
        ende = min(len(mix_ducked), pos + duck_len)
        chunk_len = ende - pos
        mix_ducked[pos:ende] *= duck_curve[:chunk_len]
    return mix_ducked


# ============ Feature-Analyse ============
def rms(x):
    return float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0


def _pitch_lag(ac, lo, hi):
    neg = np.nonzero(ac[1:hi] < 0)[0]
    start = max(lo, int(neg[0]) + 1) if len(neg) else lo
    kandidaten = []
    for i in range(max(start, lo + 1), min(hi, len(ac) - 1)):
        if ac[i] > ac[i - 1] and ac[i] >= ac[i + 1] and ac[i] > 0:
            kandidaten.append((i, float(ac[i])))
    if not kandidaten:
        return None, 0.0
    best = max(v for _, v in kandidaten)
    lag, val = next((i, v) for i, v in kandidaten if v >= 0.9 * best)
    return lag, val


def pitch_stats(mono, sr, frame=2048, hop=1024, max_frames=40):
    lo, hi = max(2, int(sr / F0_MAX)), int(sr / 80)
    starts = list(range(0, max(1, len(mono) - frame), hop))[:max_frames]
    considered, voiced_harm, voiced_f0 = 0, [], []
    for s in starts:
        seg = mono[s:s + frame]
        if len(seg) < frame or rms(seg) < EMPTY_RMS:
            continue
        seg = seg - seg.mean()
        ac = np.correlate(seg, seg, "full")[frame - 1:]
        if ac[0] <= 0 or hi + 1 >= len(ac):
            continue
        ac = ac / ac[0]
        considered += 1
        lag, harm = _pitch_lag(ac, lo, hi)
        if lag is not None and harm >= 0.5:
            voiced_harm.append(harm)
            voiced_f0.append(sr / lag)
    if considered == 0:
        return 0.0, 1.0, 0.0
    frac = len(voiced_harm) / considered
    harm = float(np.median(voiced_harm)) if voiced_harm else 1.0
    f0 = float(np.median(voiced_f0)) if voiced_f0 else 0.0
    return frac, harm, f0


def spectrum_info(mono, sr):
    x = mono[: int(sr * 2)]
    win = np.hanning(len(x)) if len(x) > 1 else np.ones(len(x))
    p = np.abs(np.fft.rfft(x * win)) ** 2
    freqs = np.fft.rfftfreq(len(x), 1.0 / sr)
    centroid = float((freqs * p).sum() / max(p.sum(), 1e-12))
    edges = np.geomspace(40, sr / 2, 33)
    bands = np.array([p[(freqs >= a) & (freqs < b)].sum() for a, b in zip(edges[:-1], edges[1:])])
    fp = np.log(bands + 1e-9)
    fp = fp - fp.mean()
    n = np.linalg.norm(fp)
    fp = fp / n if n > 0 else fp
    return centroid, fp


def schaetze_tonart(mono, sr):
    if len(mono) < 1024 or rms(mono) < EMPTY_RMS:
        return None, 0.0

    n_fft = 4096
    hop = 1024
    chroma = np.zeros(12, dtype=np.float32)
    win = np.hanning(n_fft)
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)

    considered = 0
    for s in range(0, len(mono) - n_fft + 1, hop):
        seg = mono[s:s + n_fft] * win
        p = np.abs(np.fft.rfft(seg)) ** 2
        for i, f in enumerate(freqs):
            if 55.0 <= f <= 1760.0:
                midi_note = int(round(69 + 12 * np.log2(f / 440.0))) % 12
                chroma[midi_note] += float(p[i])
        considered += 1

    if chroma.sum() < 1e-9 or considered == 0:
        return None, 0.0

    chroma /= chroma.sum()

    major_profile = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
    minor_profile = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 2.69, 3.34, 3.17, 3.40])
    major_profile /= major_profile.sum()
    minor_profile /= minor_profile.sum()

    scores = []
    for root in range(12):
        maj_shift = np.roll(major_profile, root)
        min_shift = np.roll(minor_profile, root)

        corr_maj = float(np.corrcoef(chroma, maj_shift)[0, 1])
        corr_min = float(np.corrcoef(chroma, min_shift)[0, 1])

        scores.append((corr_maj, f"{TONART_NAMEN[root]} Dur"))
        scores.append((corr_min, f"{TONART_NAMEN[root]} Moll"))

    scores.sort(key=lambda item: -item[0])
    best_score, best_key = scores[0]
    second_score, _ = scores[1]
    margin = best_score - second_score

    if best_score <= 0.2 or margin <= 0.0:
        konfidenz = 0.0
    else:
        raw_conf = max(0.0, (best_score - 0.2) / 0.8)
        margin_factor = max(0.0, min(1.0, margin / 0.15))
        konfidenz = max(0.0, min(100.0, round(raw_conf * margin_factor * 100.0, 1)))

    return best_key, konfidenz


def berechne_sauberkeit(mono, sr):
    if len(mono) == 0:
        return 0.0
    abs_x = np.abs(mono)
    peak = float(np.max(abs_x))
    if peak < 1e-6:
        return 0.0

    sorted_abs = np.sort(abs_x)
    quiet_sample_count = max(1, int(len(sorted_abs) * 0.05))
    noise_floor = float(np.mean(sorted_abs[:quiet_sample_count])) + 1e-6
    snr_db = round(20 * math.log10(peak / noise_floor), 1)
    return snr_db


def features(name, mono, sr):
    dur = len(mono) / sr
    r = rms(mono)
    a_end, b_end = int(0.025 * sr), int(0.15 * sr)
    r_anfang = rms(mono[:a_end])
    r_rest = rms(mono[a_end:b_end]) if len(mono) > a_end else 0.0
    transient = r_anfang > ATTACK_RMS and r_anfang / (r_rest + 1e-6) > ATTACK_RATIO
    voiced, harm, f0 = pitch_stats(mono, sr)
    centroid, fp = spectrum_info(mono, sr)

    sauberkeit = berechne_sauberkeit(mono, sr)
    tonart, tonart_sicherheit = schaetze_tonart(mono, sr) if r >= EMPTY_RMS else (None, 0.0)

    leer = r < EMPTY_RMS or dur < MIN_DUR_S or sauberkeit < 12.0
    return {"file": name, "dauer": round(dur, 3), "rms": round(r, 4), "centroid": round(centroid),
            "anschlag": bool(transient), "stimmhaft": round(voiced, 2), "harm": round(harm, 3),
            "f0": round(f0), "sr": sr, "sauberkeit_db": sauberkeit, "tonart": tonart,
            "tonart_sicherheit": tonart_sicherheit, "leer": bool(leer), "_fp": fp}


def klassifiziere(f):
    if f["leer"]:
        return None
    stimmhaft = f["stimmhaft"]
    tonhoehe_ok = F0_MIN <= f["f0"] <= F0_MAX
    if f["anschlag"] and stimmhaft < VOICE_PERC_MAX:
        return "PERCUSSION"
    if stimmhaft >= VOICE_VOICED_MIN and f["harm"] < VOICE_HARM_MAX and tonhoehe_ok:
        return "VOICE"
    return "MELODY"


STERN_PASST = {
    "PERCUSSION": lambda f: f["stimmhaft"] < VOICE_PERC_MAX,
    "VOICE": lambda f: f["stimmhaft"] >= VOICE_VOICED_MIN,
    "MELODY": lambda f: f["stimmhaft"] < VOICE_VOICED_MIN,
}


def grenzgruende(f):
    gr = []
    c, s = f["cat"], f["stimmhaft"]
    if c == "VOICE":
        if 0.5 <= s < 0.6:
            gr.append("Stimmhaftigkeit knapp")
        if 0.85 <= f["harm"] < VOICE_HARM_MAX:
            gr.append("Harmonizität knapp")
    if c == "PERCUSSION":
        if f["anschlag"] and 0.2 <= s < VOICE_PERC_MAX:
            gr.append("evtl. gesungen")
        if f["centroid"] > 4000 and s < 0.2 and f["dauer"] > 0.3:
            gr.append("evtl. Atem/Beatbox")
    return gr


def analysiere(project_dir, verschieben=True, fortschritt=None):
    namen = sorted(n for n in os.listdir(project_dir)
                   if n.lower().endswith(".wav") and os.path.isfile(os.path.join(project_dir, n)))
    feats = []
    for i, n in enumerate(namen, 1):
        try:
            mono, sr = read_wav_mono(os.path.join(project_dir, n))
            feats.append(features(n, mono, sr))
        except Exception as ex:
            feats.append({"file": n, "fehler": str(ex), "leer": True, "_fp": None})
        if fortschritt:
            fortschritt(i, len(namen))

    for f in feats:
        f["cat"] = klassifiziere(f)
        f["rolle_vorschlag"] = rolle_vorschlag(f)

    behalten = {}
    for f in sorted(feats, key=lambda x: -x.get("rms", 0)):
        f["dup_of"] = None
        f["dup_sim"] = None
        if f["cat"] is None or f["_fp"] is None:
            continue
        best, match = 0.0, None
        for k in behalten.get(f["cat"], []):
            sim = float(np.dot(f["_fp"], k["_fp"]))
            if sim > best:
                best, match = sim, k["file"]
        f["dup_sim"] = round(best, 3) if match else None
        if match and best >= DUP_THRESHOLD:
            f["dup_of"] = match
        else:
            behalten.setdefault(f["cat"], []).append(f)

    for kat in KATS:
        kandidaten = [f for f in feats if f["cat"] == kat and not f["dup_of"]
                      and STERN_PASST[kat](f)]
        if not kandidaten:
            continue
        passend = [f for f in kandidaten if 0.1 <= f["dauer"] <= 2.0] or kandidaten
        max(passend, key=lambda f: f["rms"])["stern"] = True

    for f in feats:
        f["loeschen"] = bool(f["leer"])
        f.setdefault("stern", False)
        if f["cat"] is None:
            f["pfad"] = os.path.join("LEER", f["file"])
        elif f["dup_of"]:
            f["pfad"] = os.path.join("DUBLETTEN", f["cat"], f["file"])
        else:
            f["pfad"] = os.path.join(f["cat"], f["file"])

    for f in feats:
        gr = [] if f["leer"] or f["cat"] is None else grenzgruende(f)
        if f.get("dup_sim") is not None and 0.95 <= f["dup_sim"] <= 0.99:
            gr.append("Dubletten-Ähnlichkeit knapp")
        f["grund"] = gr
        f["grenzfall"] = bool(gr)

    if verschieben:
        for f in feats:
            if "pfad" not in f:
                continue
            ziel = os.path.join(project_dir, f["pfad"])
            os.makedirs(os.path.dirname(ziel), exist_ok=True)
            shutil.move(os.path.join(project_dir, f["file"]), ziel)

    index = [{k: v for k, v in f.items() if not k.startswith("_")} for f in feats]
    with open(os.path.join(project_dir, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=1)
    return zusammenfassung(index)


def rolle_vorschlag(f):
    """Nur ein Vorschlag fuer die Pool-Ablage. Verschiebt nichts; der Nutzer entscheidet.
    Schwellen wie vereinbart: KICK = Anschlag, Schwerpunkt unter 1000 Hz;
    SNARE_CLAP = Anschlag, 1000 bis 6000 Hz; HIHAT = ueber 6000 Hz und kuerzer als 0,4 s; sonst PERC."""
    if f.get("cat") != "PERCUSSION":
        return f.get("cat")
    c = f.get("centroid", 0) or 0
    d = f.get("dauer", 0) or 0
    if f.get("anschlag") and c < 1000:
        return "KICK"
    if f.get("anschlag") and 1000 <= c <= 6000:
        return "SNARE_CLAP"
    if c > 6000 and d < 0.4:
        return "HIHAT"
    return "PERC"


def zusammenfassung(index):
    zeilen = {}
    for kat in KATS:
        zeilen[kat] = sum(1 for e in index if e.get("cat") == kat and not e.get("dup_of"))
    return {
        "kategorien": zeilen,
        "dubletten": sum(1 for e in index if e.get("dup_of")),
        "loeschen": sum(1 for e in index if e.get("loeschen")),
        "grenzfaelle": sum(1 for e in index if e.get("grenzfall")),
        "sterne": {kat: next((e["file"] for e in index if e.get("cat") == kat and e.get("stern")), None)
                   for kat in KATS},
    }


# ============ Bass-Synthese (4 Klangarten laut Konzept v4-1) ============
def synthesisiere_bass(dauer_s, freq_hz=55.0, typ="saegeszahn", sr=44100):
    """
    Synthesisiert Bass-Klänge entsprechend Abschnitt 9 des Konzepts:
    1. saegeszahn: Begrenzter Sägezahn (10 Obertöne)
    2. saettigung: Sinus mit Obertönen und sanfter Verzerrung
    3. slap: Kurzer Daumen-Schlag / Pop
    4. flaechig: Zwei verstimmte begrenzte Sägezähne, langsamer Einsatz
    """
    n = max(1, int(dauer_s * sr))
    t = np.arange(n, dtype=np.float32) / sr

    if typ == "saegeszahn":
        wave_data = np.zeros(n, dtype=np.float32)
        for h in range(1, 11):
            if h * freq_hz < sr / 2:
                wave_data += (1.0 / h) * np.sin(2 * np.pi * h * freq_hz * t)
        env = np.exp(-2.5 * t / max(0.1, dauer_s))

    elif typ == "saettigung":
        raw_sin = np.sin(2 * np.pi * freq_hz * t) + 0.3 * np.sin(4 * np.pi * freq_hz * t)
        wave_data = np.tanh(1.8 * raw_sin)
        env = np.exp(-2.0 * t / max(0.1, dauer_s))

    elif typ == "slap":
        wave_data = np.sin(2 * np.pi * freq_hz * t)
        for h in range(2, 9):
            if h * freq_hz < sr / 2:
                wave_data += (0.5 / h) * np.sin(2 * np.pi * h * freq_hz * t)
        env = np.exp(-8.0 * t / max(0.05, dauer_s))

    elif typ == "flaechig":
        f1, f2 = freq_hz, freq_hz * 1.005
        wave_data = 0.5 * np.sin(2 * np.pi * f1 * t) + 0.5 * np.sin(2 * np.pi * f2 * t)
        attack_len = min(int(0.05 * sr), n)
        env = np.ones(n, dtype=np.float32)
        if attack_len > 0:
            env[:attack_len] = np.linspace(0, 1, attack_len, dtype=np.float32)
        env *= np.exp(-1.0 * t / max(0.1, dauer_s))
    else:
        wave_data = np.sin(2 * np.pi * freq_hz * t)
        env = np.exp(-3.0 * t / max(0.1, dauer_s))

    fade_in_len = min(int(0.005 * sr), n)
    if fade_in_len > 0 and typ != "flaechig":
        env[:fade_in_len] *= np.linspace(0, 1, fade_in_len, dtype=np.float32)

    wave_data *= env
    current_rms = rms(wave_data)
    if current_rms > 1e-6:
        wave_data = wave_data * (0.14 / current_rms)

    return nulldurchgang_fade(wave_data.astype(np.float32), sr)


# ============ Tempo & Versatz ============
def frame_features(m, sr):
    frame = 2048
    hop = 512
    if len(m) < frame:
        m = np.pad(m, (0, frame - len(m)))
    n = (len(m) - frame) // hop + 1
    win = np.hanning(frame)
    flux = np.zeros(n)
    prev = None
    chunk = 1024
    for c0 in range(0, n, chunk):
        c1 = min(n, c0 + chunk)
        idx = (np.arange(c0, c1) * hop)[:, None] + np.arange(frame)[None, :]
        seg = m[idx]
        X = np.fft.rfft(seg * win, axis=1)
        M = np.abs(X)
        first = prev if prev is not None else M[0]
        prev_block = np.vstack([first[None, :], M[:-1]])
        flux[c0:c1] = np.maximum(M - prev_block, 0).sum(axis=1)
        prev = M[-1]
    return flux


def schaetze_tempo(mono, sr):
    flux_roh = frame_features(mono, sr)
    flux = flux_roh - flux_roh.mean()
    frame_s = 512 / sr
    bester = (0.0, 125.0)
    for bpm in np.arange(70.0, 190.5, 0.5):
        beat_f = 60.0 / bpm / frame_s
        score = 0.0
        for k in (1, 2, 4):
            lag = int(round(k * beat_f))
            if lag >= len(flux) - 1:
                continue
            score += float(np.mean(flux[:-lag] * flux[lag:])) / k
        score *= 1.0 if 90 <= bpm <= 170 else 0.85
        if score > bester[0]:
            bester = (score, float(bpm))
    bpm = bester[1]
    beat_s = 60.0 / bpm

    thr = flux_roh.mean() + flux_roh.std()
    on = np.nonzero((flux_roh[1:-1] >= flux_roh[:-2]) & (flux_roh[1:-1] > flux_roh[2:]) & (flux_roh[1:-1] > thr))[0] + 1
    if len(on) == 0:
        return bpm, 0.0, 0.0
    t_on = (on * 512 + 1024) / sr
    w = flux_roh[on]
    R = np.sum(w * np.exp(1j * 2 * np.pi * t_on / beat_s)) / max(np.sum(w), 1e-12)
    versatz = float((np.angle(R) / (2 * np.pi)) * beat_s % beat_s)
    return bpm, versatz, float(abs(R))


# ============ Pipeline ============
def stille_bereiche(mono, sr):
    blk = 256
    nb = len(mono) // blk
    if nb == 0:
        return []
    env = np.abs(mono[:nb * blk]).reshape(-1, blk).max(axis=1)
    still = env < 10 ** (STILLE_DB / 20)
    min_b = max(1, int(STILLE_MIN_S * sr / blk))
    puffer = int(STILLE_PUFFER_S * sr)
    cuts, i = [], 0
    while i < nb:
        if still[i]:
            j = i
            while j < nb and still[j]:
                j += 1
            if j - i >= min_b:
                a, b = i * blk + puffer, j * blk - puffer
                if b > a:
                    cuts.append((a, b))
            i = j
        else:
            i += 1
    return cuts


def _ohne_stille(s, e, cuts):
    teile = [(s, e)]
    for a, b in cuts:
        neu = []
        for x, y in teile:
            if b <= x or a >= y:
                neu.append((x, y))
                continue
            if a > x:
                neu.append((x, a))
            if b < y:
                neu.append((b, y))
        teile = neu
    return teile


def slices_auf_raster(n, sr, bpm, versatz, cuts):
    step = 60.0 / bpm / PIPE_DIV * sr
    marken = [0, n] + [int(round(v)) for v in np.arange(versatz * sr, n, step)]
    marken = sorted(set(m for m in marken if 0 <= m <= n))
    out = []
    for s, e in zip(marken[:-1], marken[1:]):
        for a, b in _ohne_stille(s, e, cuts):
            if b - a > 0.01 * sr:
                out.append((a, b))
    return out


def stimmhaft_maske(mono, sr, frame=2048, hop=1024):
    lo, hi = max(2, int(sr / F0_MAX)), int(sr / 80)
    starts = list(range(0, max(1, len(mono) - frame), hop))
    maske = np.zeros(len(starts), dtype=bool)
    nfft = 2 * frame
    for i, s in enumerate(starts):
        seg = mono[s:s + frame]
        if len(seg) < frame or rms(seg) < EMPTY_RMS:
            continue
        seg = seg - seg.mean()
        ac = np.fft.irfft(np.abs(np.fft.rfft(seg, nfft)) ** 2, nfft)[:frame]
        if ac[0] <= 0 or hi + 1 >= len(ac):
            continue
        ac = ac / ac[0]
        lag, harm = _pitch_lag(ac, lo, hi)
        if lag is None or harm < 0.5 or harm >= VOICE_HARM_MAX:
            continue
        if F0_MIN <= sr / lag <= F0_MAX:
            maske[i] = True
    return maske, hop


def vokal_bereiche(mono, sr):
    maske, hop = stimmhaft_maske(mono, sr)
    luecke = max(1, int(VOKAL_LUECKE_S * sr / hop))
    frames = np.nonzero(maske)[0]
    gruppen = []
    start = prev = None
    for f in frames:
        f = int(f)
        if start is None:
            start = prev = f
        elif f - prev > luecke:
            gruppen.append((start, prev))
            start = prev = f
        else:
            prev = f
    if start is not None:
        gruppen.append((start, prev))

    schwelle_hoch = EMPTY_RMS * 2.0
    blk = 256

    out = []
    for f_a, f_b in gruppen:
        a = f_a * hop
        b = min(len(mono), f_b * hop + 2048)
        seg = mono[a:b]

        curr_a = 0
        for i in range(0, len(seg) - blk, blk):
            sub_rms = rms(seg[i:i + blk])
            if sub_rms >= schwelle_hoch:
                curr_a = max(0, i - blk)
                break

        curr_b = len(seg)
        for i in range(len(seg) - blk, 0, -blk):
            sub_rms = rms(seg[i:i + blk])
            if sub_rms >= schwelle_hoch:
                curr_b = min(len(seg), i + 2 * blk)
                break

        if curr_b <= curr_a:
            curr_a = 0
            curr_b = len(seg)

        a_clean = a + curr_a
        b_clean = a + curr_b
        dauer = (b_clean - a_clean) / sr
        n = int(math.ceil(dauer / LANG_VOKAL_MAX_S))
        laenge = (b_clean - a_clean) / n
        for i in range(n):
            out.append((int(a_clean + i * laenge), int(a_clean + (i + 1) * laenge)))
    return out


def _datei_hash(pfad):
    h = hashlib.sha1()
    with open(pfad, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _lock_results(results_dir):
    lock_file = os.path.join(results_dir, ".results.lock")
    fh = open(lock_file, "a+")
    try:
        import fcntl
        fcntl.flock(fh, fcntl.LOCK_EX)
    except Exception:
        pass
    return fh


def _unlock_results(fh):
    try:
        import fcntl
        fcntl.flock(fh, fcntl.LOCK_UN)
    except Exception:
        pass
    try:
        fh.close()
    except Exception:
        pass


def _waehle_ergebnisordner_unlocked(results_dir, basis, quell_hash):
    n = 1
    while True:
        name = basis if n == 1 else basis + "_" + str(n)
        p = os.path.join(results_dir, name)
        q_file = os.path.join(p, "quelle.json")
        if not os.path.isdir(p):
            os.makedirs(p, exist_ok=True)
            with open(q_file, "w", encoding="utf-8") as fh:
                json.dump({"sha1": quell_hash, "reserved": True}, fh, ensure_ascii=False)
            return p
        try:
            if os.path.isfile(q_file):
                with open(q_file, encoding="utf-8") as fh:
                    if json.load(fh).get("sha1") == quell_hash:
                        return p
            elif n == 1:
                # Legacy-Ordner ohne quelle.json übernehmen/migrieren
                return p
        except Exception:
            pass
        n += 1


def _waehle_ergebnisordner(results_dir, basis, quell_hash):
    """Gleiche Quelle ersetzt ihren Ordner. Eine andere Quelle mit gleichem Namen bekommt _2, _3 usw."""
    os.makedirs(results_dir, exist_ok=True)
    lock_fh = _lock_results(results_dir)
    try:
        return _waehle_ergebnisordner_unlocked(results_dir, basis, quell_hash)
    finally:
        _unlock_results(lock_fh)


def verarbeite(pfad, melde_fn, results_dir=None):
    """
    Verarbeitet eine WAV-Datei und speichert das Ergebnis unter RESULTS/<Name>/.
    Der Ordnername wird nach Abschnitt 11 des Konzepts bereinigt.
    """
    if results_dir is None:
        results_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "RESULTS")
    x, sr = read_wav_mono(pfad)
    mono = x
    dateiname = os.path.basename(pfad)
    ordner_name = bereinigter_ordnername(dateiname)

    melde_fn("Stille suchen")
    cuts = stille_bereiche(mono, sr)
    melde_fn("Gesangsphrasen suchen")
    vokal = []
    for a, b in vokal_bereiche(mono, sr):
        vokal += _ohne_stille(a, b, cuts)

    melde_fn("Tempo schätzen")
    bpm, versatz, sicher = schaetze_tempo(mono, sr)
    melde_fn(f"{bpm:.1f} BPM, Versatz {versatz * 1000:.0f} ms. Schneide...")

    raster = [(s, e) for s, e in slices_auf_raster(len(mono), sr, bpm, versatz, cuts)
              if not any(a <= (s + e) // 2 < b for a, b in vokal)]

    os.makedirs(results_dir, exist_ok=True)
    quell_hash = _datei_hash(pfad)
    ziel_ordner = _waehle_ergebnisordner(results_dir, ordner_name, quell_hash)

    tmp = tempfile.mkdtemp(prefix=".arbeit_", dir=results_dir)
    ergebnis = tempfile.mkdtemp(prefix=".ergebnis_", dir=results_dir)
    alt = None
    vokal_dateien = set()

    try:
        k, leer = 0, 0
        for ist_vokal, (s, e) in [(True, t) for t in vokal] + [(False, t) for t in raster]:
            seg = mono[s:e]
            if rms(seg) < EMPTY_RMS or len(seg) / sr < MIN_DUR_S:
                leer += 1
                continue
            k += 1
            name = f"s{k:04d}.wav"
            pcm = (np.clip(nulldurchgang_fade(seg, sr), -1.0, 1.0) * 32767).astype("<i2")
            with wave.open(os.path.join(tmp, name), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sr)
                wf.writeframes(pcm.tobytes())

            if ist_vokal:
                vokal_dateien.add(name)

        def _fortschritt(i, n):
            if i % 5 == 0 or i == n:
                melde_fn(f"{i}/{n} Slices analysiert")

        melde_fn(f"{k} Slices werden analysiert")
        summe = analysiere(tmp, verschieben=True, fortschritt=_fortschritt)
        with open(os.path.join(tmp, "quelle.json"), "w", encoding="utf-8") as fh:
            json.dump({"datei": dateiname, "sha1": quell_hash}, fh, ensure_ascii=False)

        os.makedirs(results_dir, exist_ok=True)
        lock_fh = _lock_results(results_dir)
        try:
            if os.path.isdir(ziel_ordner) and os.path.isfile(os.path.join(ziel_ordner, "quelle.json")):
                try:
                    with open(os.path.join(ziel_ordner, "quelle.json"), encoding="utf-8") as fh:
                        current_sha1 = json.load(fh).get("sha1")
                    if current_sha1 != quell_hash:
                        ziel_ordner = _waehle_ergebnisordner_unlocked(results_dir, ordner_name, quell_hash)
                except Exception:
                    pass

            if os.path.isdir(ziel_ordner):
                alt = os.path.join(results_dir, ".alt_" + uuid.uuid4().hex)
                os.rename(ziel_ordner, alt)

            try:
                os.rename(tmp, ziel_ordner)
            except OSError:
                if alt:
                    try:
                        os.rename(alt, ziel_ordner)
                        alt = None
                    except OSError:
                        pass
                raise
        finally:
            _unlock_results(lock_fh)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(ergebnis, ignore_errors=True)
        if alt and os.path.exists(ziel_ordner):
            shutil.rmtree(alt, ignore_errors=True)

    return {
        "bpm": round(bpm, 2),
        "versatz_ms": round(versatz * 1000),
        "sicherheit": round(sicher, 3),
        "stille_schnitte": len(cuts),
        "vokal_phrasen": len(vokal_dateien),
        "slices": k,
        "leer": leer,
        "zusammenfassung": summe,
        "ordner": ziel_ordner
    }
