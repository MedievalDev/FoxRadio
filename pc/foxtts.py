#!/usr/bin/env python3
"""
FoxRadio TTS-Renderer: rendert Dialogzeilen mit Qwen3-TTS und schneidet sie
zu einem Block zusammen, mit leisem Musikbett darunter.

Zwei Backends (foxtts.json, "backend"):
    direct  Qwen3-TTS direkt aus dem ComfyUI-Ordner, in einem eigenen
            Arbeitsprozess mit der isolierten transformers-4.57-Umgebung
            (qwen_tts_env). Standard, weil der ComfyUI-Node mit dem
            transformers 5.9 von ComfyUI nicht rendert (Stand 09/2026).
    comfy   ueber die ComfyUI-API mit exportierten Workflows je Stimme.

Läuft am besten mit der eingebetteten Python von ComfyUI, weil dort PyAV
(Dekodieren von FLAC/MP3, Schreiben von MP3) und numpy schon dabei sind:

    C:\\...\\ComfyUI_windows_portable\\python_embeded\\python.exe pc\\foxtts.py block pc\\scripts\\testdialog.txt -o work\\test.mp3

Befehle:
    status                          Antwortet die ComfyUI-API?
    start                           ComfyUI über die BAT starten, falls nötig, und warten
    probe <workflow.json>           Nodes des exportierten Workflows zeigen, Text-Knoten erkennen
    line -v A -t "Text" -o out.wav  Eine Zeile rendern
    voice-design <workflow.json> -o ref_a.wav   Referenzstimme aus einer Design-Vorlage erzeugen
    block <script.txt> -o out.mp3   Dialog-Skript rendern und zusammenschneiden
    worker                          (intern) Arbeitsprozess des direct-Backends

Stimmen im direct-Backend (foxtts.json, "voices"):
    {"mode": "design", "instruct": "Beschreibung", "seed": 123}   Stimme aus Beschreibung
    {"mode": "clone", "ref_audio": "voices/a_ref.wav", "ref_text": "Transkript"}
    {"mode": "custom", "speaker": "Ryan"}                         feste englische Sprecher
Fuer eine ueber hunderte Zeilen gleichbleibende Stimme: einmal mit "design"
eine Referenz rendern (line -v A_design ...), dann "clone" mit dieser Datei.

Skriptformat (block): eine Zeile pro Sprecher, "A: Text" oder "B: Text".
Leerzeile = längere Pause. Zeilen mit # sind Kommentare.

Konfiguration: foxtts.json neben diesem Skript (siehe foxtts.example.json).
Beim comfy-Backend pro Stimme ein Workflow ("Save (API Format)"), das Skript
ersetzt darin nur den Text des TTS-Knotens.
"""

import argparse
import atexit
import copy
import glob
import json
import os
import queue
import random
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "foxtts.json")

DEFAULTS = {
    "comfy_url": "http://127.0.0.1:8188",
    "comfy_bat": r"C:\Users\marco\Desktop\ComfyUI_windows_portable\run_nvidia_gpu.bat",
    "start_timeout_s": 240,
    "render_timeout_s": 600,
    "poll_interval_s": 1.0,
    "voices": {},
    "pause_ms": 350,
    "paragraph_pause_ms": 800,
    "sample_rate": 24000,
    "mp3_bitrate": "96k",
    "work_dir": os.path.join(HERE, "work"),
    "backend": "direct",
    "direct": {
        "python": r"C:\Users\marco\Desktop\ComfyUI_windows_portable\python_embeded\python.exe",
        "root": r"C:\Users\marco\Desktop\ComfyUI_windows_portable",
        "language": "German",
        "log": "",
    },
    # Jingles: Zeilen "J: news" im Skript. Datei jingles/<name>.<mp3|wav|flac|ogg>,
    # sonst wird der Marker uebersprungen. gain_db regelt sie gegen die Stimmen.
    "jingles": {
        "enabled": True,
        "dir": os.path.join(HERE, "jingles"),
        "gain_db": -3.0,
        "pause_ms": 250,
    },
    # Leises Musikbett unter jedem Block. Dateien (mp3/wav/flac/ogg) in
    # music/, eine wird je Block zufaellig gewaehlt. Ohne Dateien kein Bett.
    "music": {
        "enabled": True,
        "dir": os.path.join(HERE, "music"),
        "gain_db": -20.0,
        "fade_s": 2.0,
        "lead_s": 0.8,
        "tail_s": 1.5,
    },
}

TEXT_INPUT_NAMES = ("text", "target_text")


# ----------------------------------------------------------------------------
# Konfiguration
# ----------------------------------------------------------------------------

def load_config():
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            eigen = json.load(f)
        for key in ("direct", "music", "jingles"):   # verschachtelte Teile ergaenzen, nicht ersetzen
            if isinstance(eigen.get(key), dict):
                eigen[key] = {**DEFAULTS[key], **eigen[key]}
        cfg.update(eigen)
    else:
        log(f"Hinweis: keine {CONFIG_PATH}, benutze Standardwerte")
    return cfg


def resolve_path(path):
    return path if os.path.isabs(path) else os.path.join(HERE, path)


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


# ----------------------------------------------------------------------------
# ComfyUI-API
# ----------------------------------------------------------------------------

class Comfy:
    def __init__(self, base_url):
        self.base = base_url.rstrip("/")
        self.client_id = str(uuid.uuid4())

    def _get(self, path, timeout=10):
        with urllib.request.urlopen(self.base + path, timeout=timeout) as r:
            return r.read()

    def _get_json(self, path, timeout=10):
        return json.loads(self._get(path, timeout).decode("utf-8"))

    def alive(self):
        try:
            self._get_json("/system_stats", timeout=5)
            return True
        except Exception:
            return False

    def queue_prompt(self, workflow):
        body = json.dumps({"prompt": workflow, "client_id": self.client_id}).encode("utf-8")
        req = urllib.request.Request(
            self.base + "/prompt", data=body, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"/prompt abgelehnt ({e.code}): {e.read().decode('utf-8', 'replace')[:800]}")
        if data.get("node_errors"):
            raise RuntimeError(f"Workflow-Fehler: {json.dumps(data['node_errors'])[:800]}")
        return data["prompt_id"]

    def wait_for(self, prompt_id, timeout_s, poll_s):
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            hist = self._get_json(f"/history/{prompt_id}")
            entry = hist.get(prompt_id)
            if entry:
                status = entry.get("status") or {}
                if status.get("status_str") == "error" or status.get("completed") is False and status.get("status_str"):
                    raise RuntimeError(f"ComfyUI meldet Fehler: {json.dumps(status)[:800]}")
                files = []
                for node_out in (entry.get("outputs") or {}).values():
                    for val in node_out.values():
                        if isinstance(val, list):
                            for item in val:
                                if isinstance(item, dict) and "filename" in item:
                                    files.append(item)
                if files or status.get("completed"):
                    return files
            time.sleep(poll_s)
        raise TimeoutError(f"Render nach {timeout_s}s nicht fertig (prompt {prompt_id})")

    def download(self, item, dest_dir):
        q = urllib.parse.urlencode({
            "filename": item["filename"],
            "subfolder": item.get("subfolder", ""),
            "type": item.get("type", "output"),
        })
        data = self._get("/view?" + q, timeout=60)
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, os.path.basename(item["filename"]))
        with open(dest, "wb") as f:
            f.write(data)
        return dest


# ----------------------------------------------------------------------------
# direct-Backend: Qwen3-TTS ohne ComfyUI-Node
# ----------------------------------------------------------------------------

ZEICHEN_JE_SEKUNDE = 15.0      # deutsche Sprache: 12 bis 17 Zeichen je Sekunde
STUECK_MAX = 120               # laengere Zeilen satzweise erzeugen


def in_saetze(text):
    """Teilt lange Zeilen an Satzenden. Kurze Eingaben sind der wirksamste
    Schutz gegen die Schleife, sehr kurze Fetzen haengen am Nachbarn."""
    text = " ".join(text.split())
    if len(text) <= STUECK_MAX:
        return [text]
    import re
    saetze = [t.strip() for t in re.split(r"(?<=[.!?])\s+", text) if t.strip()]
    stuecke = []
    for satz in saetze:
        if stuecke and (len(satz) < 20 or len(stuecke[-1]) + 1 + len(satz) <= STUECK_MAX):
            stuecke[-1] += " " + satz
        else:
            stuecke.append(satz)
    return stuecke or [text]


def worker(cfg):
    """Laeuft als eigener Prozess in der ComfyUI-Python, aber mit der
    isolierten transformers-4.57-Umgebung (qwen_tts_env) vor den
    site-packages - Qwen3-TTS vertraegt das transformers 5.9 von ComfyUI
    nicht. Liest je Zeile einen Auftrag als JSON von stdin, schreibt die
    WAV und antwortet mit einer JSON-Zeile auf stdout. Alles andere, was
    Modell und Bibliotheken reden, geht nach stderr."""
    d = cfg["direct"]
    root = d["root"]
    sys.path.insert(0, os.path.join(root, "ComfyUI", "custom_nodes", "ComfyUI-QwenTTS"))
    sys.path.insert(0, os.path.join(root, "qwen_tts_env"))
    antworten = sys.stdout
    sys.stdout = sys.stderr
    import numpy as np
    import soundfile as sf
    import torch
    import transformers
    from qwen_tts import Qwen3TTSModel
    if not transformers.__version__.startswith("4.57"):
        print(f"WARNUNG: transformers {transformers.__version__} im Pfad, erwartet 4.57", file=sys.stderr)
    models_dir = os.path.join(root, "ComfyUI", "models", "TTS", "Qwen3-TTS")
    cache = {}

    def modell(art, groesse):
        key = (art, groesse)
        if key not in cache:
            pfad = os.path.join(models_dir, f"Qwen3-TTS-12Hz-{groesse}-{art}")
            if not os.path.isdir(pfad):
                raise FileNotFoundError(f"Modell fehlt: {pfad}")
            t0 = time.time()
            cache[key] = Qwen3TTSModel.from_pretrained(pfad, device_map="cuda:0", dtype=torch.bfloat16,
                                                       attn_implementation=d.get("attention", "sdpa"))
            print(f"[worker] {os.path.basename(pfad)} geladen in {time.time() - t0:.1f}s", file=sys.stderr, flush=True)
        return cache[key]

    # Klon-Prompts je Stimme einmal bauen und fuer alle Zeilen wiederverwenden
    # (Skill qwen3-tts: das Kodieren der Referenz ist der teure Teil).
    prompts = {}

    def klon_prompt(m, job, xvec):
        key = (job["ref_audio"], job.get("ref_text") or "", xvec)
        if key not in prompts:
            prompts[key] = m.create_voice_clone_prompt(
                ref_audio=job["ref_audio"], ref_text=None if xvec else job.get("ref_text"),
                x_vector_only_mode=xvec)
        return prompts[key]

    def erzeuge(job, text, versuch):
        """Ein Stueck Text erzeugen. Liefert (audio, sr, dauer, erwartet, ok, xvec)."""
        mode = job.get("mode", "design")
        groesse = job.get("model_size", "1.7B")
        lang = job.get("language", "German")
        erwartet = len(text) / ZEICHEN_JE_SEKUNDE
        deckel = int(erwartet * 12.0 * 1.8) + 24          # 12 Token je Sekunde, ohne Deckel Schleife
        seed = job.get("seed")
        basis = int(seed) if seed is not None and int(seed) >= 0 else 20260905
        torch.manual_seed(basis + versuch)
        torch.cuda.manual_seed_all(basis + versuch)
        xvec = False
        if mode == "design":
            m = modell("VoiceDesign", "1.7B")             # Design gibt es nur als 1.7B
            wavs, sr = m.generate_voice_design(text=text, instruct=job["instruct"], language=lang,
                                               max_new_tokens=deckel)
        elif mode == "custom":
            m = modell("CustomVoice", groesse)
            extra = {"instruct": job["instruct"]} if job.get("instruct") else {}
            wavs, sr = m.generate_custom_voice(text=text, speaker=job["speaker"], language=lang,
                                               max_new_tokens=deckel, **extra)
        elif mode == "clone":
            m = modell("Base", groesse)
            # ICL (mit Referenztext) klingt lebendig, entgleist aber gelegentlich;
            # nach drei Fehlschlaegen nur noch der Sprechervektor.
            xvec = versuch >= 3 or not job.get("ref_text")
            wavs, sr = m.generate_voice_clone(text=text, language=lang,
                                              voice_clone_prompt=klon_prompt(m, job, xvec),
                                              max_new_tokens=deckel)
        else:
            raise ValueError(f"unbekannter mode {mode!r}")
        audio = np.asarray(wavs[0], dtype=np.float32).squeeze()
        dauer = len(audio) / sr
        # Plausibel: 12 bis 17 Zeichen je Sekunde; das Doppelte ist eine Schleife,
        # am Deckel kleben heisst abgeschnitten. Kurze Fetzen bekommen Luft.
        ok = (0.35 * erwartet <= dauer <= max(2.0 * erwartet, erwartet + 1.5)
              and dauer < 0.97 * deckel / 12.0)
        return audio, sr, dauer, erwartet, ok, xvec

    antworten.write(json.dumps({"ok": True, "bereit": True}) + "\n")
    antworten.flush()
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            job = json.loads(raw)
            t0 = time.time()
            teile, versuche, xvec_benutzt, warnungen = [], 0, False, []
            sr = 24000
            for stueck in in_saetze(job["text"]):
                bestes = None
                for versuch in range(5):
                    versuche += 1
                    audio, sr, dauer, erwartet, ok, xvec = erzeuge(job, stueck, versuch)
                    if bestes is None or abs(dauer - erwartet) < abs(bestes[1] - erwartet):
                        bestes = (audio, dauer, xvec)
                    if ok:
                        break
                    print(f"[worker] verworfen (Versuch {versuch + 1}): {dauer:.1f}s statt ~{erwartet:.1f}s"
                          f" fuer: {stueck[:60]}", file=sys.stderr, flush=True)
                else:
                    warnungen.append(f"unplausible Laenge nach 5 Versuchen: {stueck[:60]}")
                if teile:
                    teile.append(np.zeros(int(0.18 * sr), dtype=np.float32))
                teile.append(bestes[0])
                xvec_benutzt = xvec_benutzt or bestes[2]
            audio = np.concatenate(teile)
            sf.write(job["out"], audio, sr)
            antwort = {"ok": True, "out": job["out"], "secs": round(time.time() - t0, 2),
                       "audio_s": round(len(audio) / sr, 2), "sr": sr, "stuecke": len(teile) // 2 + 1,
                       "versuche": versuche, "xvec": xvec_benutzt, "warnungen": warnungen}
        except Exception as e:
            antwort = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        antworten.write(json.dumps(antwort, ensure_ascii=False) + "\n")
        antworten.flush()


class DirectTTS:
    """Haelt den Arbeitsprozess und reicht Zeilen durch. Das Modell bleibt
    dort geladen, nur die erste Zeile zahlt die Ladezeit."""

    def __init__(self, cfg):
        d = cfg["direct"]
        os.makedirs(cfg["work_dir"], exist_ok=True)
        self.logpath = resolve_path(d["log"]) if d.get("log") else os.path.join(cfg["work_dir"], "qwen_worker.log")
        self.logf = open(self.logpath, "a", encoding="utf-8")
        self.logf.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} Arbeitsprozess gestartet ===\n")
        self.logf.flush()
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        self.proc = subprocess.Popen(
            [d["python"], os.path.abspath(__file__), "worker"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.logf,
            text=True, encoding="utf-8", bufsize=1, cwd=HERE, env=env)
        self.language = d.get("language", "German")
        self.timeout = cfg["render_timeout_s"]
        self.n = 0
        self.zeilen = queue.Queue()
        threading.Thread(target=self._lesen, daemon=True).start()
        antwort = self._antwort(cfg["start_timeout_s"])
        if not antwort.get("bereit"):
            raise RuntimeError(f"Arbeitsprozess meldet sich nicht richtig: {antwort}")
        atexit.register(self.close)

    def _lesen(self):
        for line in self.proc.stdout:
            self.zeilen.put(line)
        self.zeilen.put(None)

    def _antwort(self, timeout):
        try:
            line = self.zeilen.get(timeout=timeout)
        except queue.Empty:
            self.proc.kill()
            raise TimeoutError(f"TTS-Arbeitsprozess antwortet nicht nach {timeout}s, siehe {self.logpath}")
        if line is None:
            raise RuntimeError(f"TTS-Arbeitsprozess ist abgebrochen, siehe {self.logpath}")
        return json.loads(line)

    def alive(self):
        return self.proc.poll() is None

    def render(self, voice, vcfg, text, dest_dir):
        if not self.alive():
            raise RuntimeError(f"TTS-Arbeitsprozess ist beendet, siehe {self.logpath}")
        self.n += 1
        os.makedirs(dest_dir, exist_ok=True)
        out = os.path.join(dest_dir, f"{voice}_{self.n:04d}_{uuid.uuid4().hex[:6]}.wav")
        job = {k: v for k, v in vcfg.items() if k != "workflow"}
        job.update(text=text, out=out)
        job.setdefault("language", self.language)
        if job.get("ref_audio"):
            job["ref_audio"] = resolve_path(job["ref_audio"])
        t0 = time.time()
        self.proc.stdin.write(json.dumps(job, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        antwort = self._antwort(self.timeout)
        if not antwort.get("ok"):
            raise RuntimeError(f"TTS ({voice}): {antwort.get('error', '?')}")
        if antwort.get("versuche", 1) > antwort.get("stuecke", 1) or antwort.get("xvec"):
            log(f"  {voice}: {antwort.get('versuche')} Versuche fuer {antwort.get('stuecke')} Stueck(e)"
                + (", Rueckfall auf Sprechervektor" if antwort.get("xvec") else ""))
        for w in antwort.get("warnungen") or []:
            log(f"  WARNUNG {voice}: {w}")
        return out, time.time() - t0

    def close(self):
        if self.proc.poll() is None:
            try:
                self.proc.stdin.close()
                self.proc.wait(timeout=30)
            except Exception:
                self.proc.kill()
        self.logf.close()


_direct = None


def ensure_running(cfg):
    global _direct
    if cfg.get("backend", "direct") == "direct":
        if _direct is None or not _direct.alive():
            log("Qwen3-TTS direkt (Arbeitsprozess starten)")
            _direct = DirectTTS(cfg)
        return _direct
    api = Comfy(cfg["comfy_url"])
    if api.alive():
        log("ComfyUI läuft")
        return api
    bat = cfg["comfy_bat"]
    if not os.path.exists(bat):
        raise FileNotFoundError(f"ComfyUI antwortet nicht und BAT fehlt: {bat}")
    log(f"ComfyUI starten: {bat}")
    if os.name == "nt":
        subprocess.Popen(
            ["cmd", "/c", "start", "", bat],
            cwd=os.path.dirname(bat),
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )
    else:
        subprocess.Popen([bat], cwd=os.path.dirname(bat))
    deadline = time.time() + cfg["start_timeout_s"]
    while time.time() < deadline:
        if api.alive():
            log("ComfyUI ist da")
            return api
        time.sleep(3)
    raise TimeoutError(f"ComfyUI nach {cfg['start_timeout_s']}s nicht erreichbar")


# ----------------------------------------------------------------------------
# Workflow
# ----------------------------------------------------------------------------

def load_workflow(path):
    with open(path, encoding="utf-8") as f:
        wf = json.load(f)
    if "nodes" in wf and "links" in wf:
        raise ValueError(
            f"{path} ist das UI-Format. In ComfyUI Dev-Modus einschalten und "
            "über 'Save (API Format)' exportieren."
        )
    return wf


def find_text_node(wf, voice_cfg):
    """Liefert (node_id, input_name) des TTS-Knotens, dessen Text ersetzt wird."""
    if voice_cfg.get("text_node"):
        nid = str(voice_cfg["text_node"])
        name = voice_cfg.get("text_input") or next(
            (n for n in TEXT_INPUT_NAMES if n in wf[nid].get("inputs", {})), "text"
        )
        return nid, name
    candidates = []
    for nid, node in wf.items():
        inputs = node.get("inputs", {})
        ctype = node.get("class_type", "").lower()
        for name in TEXT_INPUT_NAMES:
            if name in inputs and isinstance(inputs[name], str):
                score = 0
                if "qwen" in ctype:
                    score += 2
                if "tts" in ctype or "voice" in ctype:
                    score += 1
                candidates.append((score, nid, name, node.get("class_type")))
    if not candidates:
        raise ValueError("Kein Knoten mit Text-Eingang gefunden. text_node in foxtts.json setzen.")
    candidates.sort(reverse=True)
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        listing = ", ".join(f"{c[1]} ({c[3]}.{c[2]})" for c in candidates)
        raise ValueError(f"Mehrere Text-Knoten möglich: {listing}. text_node in foxtts.json setzen.")
    return candidates[0][1], candidates[0][2]


def probe(path):
    wf = load_workflow(path)
    print(f"{len(wf)} Nodes in {path}")
    for nid, node in wf.items():
        plain = {k: v for k, v in node.get("inputs", {}).items() if not isinstance(v, list)}
        print(f"  [{nid}] {node.get('class_type')}")
        for k, v in plain.items():
            s = str(v)
            print(f"        {k} = {s[:70] + ('…' if len(s) > 70 else '')}")
    try:
        nid, name = find_text_node(wf, {})
        print(f"Text-Knoten erkannt: [{nid}] {wf[nid]['class_type']}.{name}")
    except ValueError as e:
        print(f"Text-Knoten: {e}")


REFERENCE_TEXT = ("Guten Morgen, hier ist FoxRadio. Es ist sieben Uhr, draußen sind zwölf Grad, "
                  "und wir fangen mit den Nachrichten aus der Spielewelt an.")


def render_line(api, cfg, voice, text, dest_dir, vcfg=None):
    vcfg = vcfg or cfg["voices"].get(voice)
    if not vcfg:
        raise KeyError(f"Stimme '{voice}' nicht in foxtts.json (voices)")
    if isinstance(api, DirectTTS):
        return api.render(voice, vcfg, text, dest_dir)
    wf = copy.deepcopy(load_workflow(resolve_path(vcfg["workflow"])))
    nid, name = find_text_node(wf, vcfg)
    wf[nid]["inputs"][name] = text
    for key, val in (vcfg.get("overrides") or {}).items():
        onid, oname = key.split(".", 1)
        wf[onid]["inputs"][oname] = val
    t0 = time.time()
    pid = api.queue_prompt(wf)
    files = api.wait_for(pid, cfg["render_timeout_s"], cfg["poll_interval_s"])
    if not files:
        raise RuntimeError("Render fertig, aber kein Audio in der History. Fehlt ein SaveAudio-Knoten?")
    path = api.download(files[0], dest_dir)
    return path, time.time() - t0


# ----------------------------------------------------------------------------
# Audio: dekodieren, schneiden, schreiben
# ----------------------------------------------------------------------------

def decode_audio(path, sample_rate):
    """Liefert int16-Mono-Samples (numpy) bei sample_rate."""
    import numpy as np
    if path.lower().endswith(".wav"):
        with wave.open(path, "rb") as w:
            ch, sw, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
            raw = w.readframes(n)
        if sw != 2:
            raise ValueError(f"{path}: nur 16-bit WAV ohne PyAV")
        data = np.frombuffer(raw, dtype=np.int16).reshape(-1, ch).mean(axis=1).astype(np.int16)
        if sr == sample_rate:
            return data
        if not _has_av():
            raise ValueError(f"{path}: {sr} Hz, brauche {sample_rate} Hz, ohne PyAV kein Resampling")
    if not _has_av():
        raise RuntimeError("PyAV fehlt. Mit der ComfyUI-Python starten oder 'pip install av'.")
    import av
    resampler = av.AudioResampler(format="s16", layout="mono", rate=sample_rate)
    chunks = []
    with av.open(path) as container:
        stream = container.streams.audio[0]
        for frame in container.decode(stream):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):
            chunks.append(out.to_ndarray().reshape(-1))
    if not chunks:
        raise ValueError(f"{path}: kein Audio dekodiert")
    return np.concatenate(chunks).astype(np.int16)


def _has_av():
    try:
        import av  # noqa: F401
        return True
    except ImportError:
        return False


def normalize(samples, peak_db=-1.0):
    import numpy as np
    peak = int(np.abs(samples.astype(np.int32)).max()) if samples.size else 0
    if peak == 0:
        return samples
    target = 32767 * (10 ** (peak_db / 20))
    gain = target / peak
    if gain >= 1.0:
        return samples
    return (samples.astype(np.float32) * gain).astype(np.int16)


def write_audio(path, samples, sample_rate, mp3_bitrate):
    import numpy as np
    if path.lower().endswith(".mp3"):
        if not _has_av():
            raise RuntimeError("MP3 braucht PyAV. Sonst .wav als Ziel angeben.")
        import av
        with av.open(path, "w") as out:
            stream = out.add_stream("mp3", rate=sample_rate, layout="mono")
            stream.bit_rate = _bitrate_to_int(mp3_bitrate)
            frame = av.AudioFrame.from_ndarray(samples.reshape(1, -1), format="s16", layout="mono")
            frame.sample_rate = sample_rate
            frame.pts = 0
            for packet in stream.encode(frame):
                out.mux(packet)
            for packet in stream.encode(None):
                out.mux(packet)
        return
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(np.ascontiguousarray(samples).tobytes())


def _bitrate_to_int(s):
    s = str(s).lower().strip()
    return int(float(s[:-1]) * 1000) if s.endswith("k") else int(s)


def music_files(cfg):
    m = cfg.get("music") or {}
    if not m.get("enabled", True):
        return []
    d = resolve_path(m["dir"])
    files = []
    for ext in ("mp3", "wav", "flac", "ogg", "m4a"):
        files += glob.glob(os.path.join(d, "*." + ext))
    return sorted(files)


def music_bed(cfg, sr, n, files):
    """Liefert ein leises, ein- und ausgeblendetes Musikstueck mit n Samples
    (float32, -1..1) und den Dateinamen. Laengere Stuecke starten an einer
    zufaelligen Stelle, kuerzere werden wiederholt."""
    import numpy as np
    m = cfg["music"]
    f = random.choice(files)
    track = decode_audio(f, sr).astype(np.float32) / 32767.0
    if len(track) < n:
        track = np.tile(track, int(np.ceil(n / len(track))))
    start = random.randint(0, len(track) - n)
    track = track[start:start + n].copy()
    track *= 10 ** (m["gain_db"] / 20)
    fade = min(int(m["fade_s"] * sr), n // 2)
    if fade > 0:
        rampe = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        track[:fade] *= rampe
        track[-fade:] *= rampe[::-1]
    return track, os.path.basename(f)


def jingle_path(cfg, name):
    j = cfg.get("jingles") or {}
    if not j.get("enabled", True):
        return None
    d = resolve_path(j["dir"])
    for ext in ("wav", "mp3", "flac", "ogg", "m4a"):
        p = os.path.join(d, f"{name}.{ext}")
        if os.path.exists(p):
            return p
    return None


def parse_script(path):
    """Liefert Liste von ("line", voice, text), ("jingle", name) oder ("pause",)."""
    items = []
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                if items and items[-1][0] != "pause":
                    items.append(("pause",))
                continue
            if line.startswith("#"):
                continue
            if ":" not in line:
                raise ValueError(f"Zeile ohne Sprecher: {line[:60]}")
            voice, text = line.split(":", 1)
            voice, text = voice.strip(), text.strip()
            if voice == "J":
                items.append(("jingle", text.lower()))
            else:
                items.append(("line", voice, text))
    while items and items[-1][0] == "pause":
        items.pop()
    return items


def render_block(cfg, script_path, out_path):
    import numpy as np
    items = parse_script(script_path)
    lines = [i for i in items if i[0] == "line"]
    jingles = [i for i in items if i[0] == "jingle"]
    log(f"{len(lines)} Zeilen" + (f" und {len(jingles)} Jingles" if jingles else "") + f" aus {script_path}")
    api = ensure_running(cfg)
    work = os.path.join(cfg["work_dir"], os.path.splitext(os.path.basename(out_path))[0])
    os.makedirs(work, exist_ok=True)
    sr = cfg["sample_rate"]
    silence = lambda ms: np.zeros(int(sr * ms / 1000), dtype=np.int16)
    parts, stats, total = [], [], 0.0
    bett = music_files(cfg)
    if not bett and (cfg.get("music") or {}).get("enabled", True):
        log(f"Musikbett: keine Dateien in {resolve_path(cfg['music']['dir'])}, Block ohne Musik")
    if bett:
        parts.append(silence(cfg["music"]["lead_s"] * 1000))    # Musik laeuft kurz an
    n = 0
    jcfg = cfg.get("jingles") or {}
    for item in items:
        if item[0] == "pause":
            parts.append(silence(cfg["paragraph_pause_ms"]))
            continue
        if item[0] == "jingle":
            p = jingle_path(cfg, item[1])
            if not p:
                log(f"Jingle '{item[1]}' fehlt in {resolve_path(jcfg.get('dir', 'jingles'))}, uebersprungen")
                continue
            klang = decode_audio(p, sr).astype(np.float32) * (10 ** (jcfg.get("gain_db", -3.0) / 20))
            if parts:
                parts.append(silence(jcfg.get("pause_ms", 250)))
            start_s = sum(len(x) for x in parts) / sr
            parts.append(klang.astype(np.int16))
            stats.append({"n": None, "voice": "J", "jingle": item[1], "chars": 0, "render_s": 0.0,
                          "audio_s": round(len(klang) / sr, 2), "start_s": round(start_s, 2),
                          "end_s": round(start_s + len(klang) / sr, 2), "file": os.path.basename(p)})
            parts.append(silence(jcfg.get("pause_ms", 250)))
            continue
        _, voice, text = item
        n += 1
        path, secs = render_line(api, cfg, voice, text, work)
        total += secs
        audio = decode_audio(path, sr)
        if n > 1 and parts and len(parts[-1]) > int(sr * 0.02):   # Pause zwischen Zeilen, nicht nach einem Jingle
            parts.append(silence(cfg["pause_ms"]))
        start_s = sum(len(x) for x in parts) / sr
        parts.append(audio)
        stats.append({"n": n, "voice": voice, "chars": len(text), "render_s": round(secs, 2),
                      "audio_s": round(len(audio) / sr, 2), "start_s": round(start_s, 2),
                      "end_s": round(start_s + len(audio) / sr, 2), "file": os.path.basename(path)})
        log(f"[{n}/{len(lines)}] {voice}: {secs:5.1f}s Render, {len(audio)/sr:5.1f}s Audio, {len(text)} Zeichen")
    musik = None
    if bett:
        parts.append(silence(cfg["music"]["tail_s"] * 1000))    # Musik klingt aus
    block = normalize(np.concatenate(parts))
    if bett:
        unterlage, musik = music_bed(cfg, sr, len(block), bett)
        gemischt = block.astype(np.float32) / 32767.0 + unterlage
        block = normalize((np.clip(gemischt, -1.0, 1.0) * 32767.0).astype(np.int16))
        log(f"Musikbett: {musik}")
    write_audio(out_path, block, sr, cfg["mp3_bitrate"])
    dur = len(block) / sr
    summary = {"script": script_path, "out": out_path, "lines": len(lines), "audio_s": round(dur, 1),
               "render_s": round(total, 1), "realtime_factor": round(total / dur, 2) if dur else None,
               "music": musik, "per_line": stats}
    with open(os.path.splitext(out_path)[0] + ".json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    log(f"Fertig: {out_path} ({dur:.1f}s Audio, {total:.1f}s Renderzeit, Faktor {summary['realtime_factor']})")
    return summary


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(description="FoxRadio TTS-Renderer für ComfyUI")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("start")
    sp = sub.add_parser("probe")
    sp.add_argument("workflow")
    sl = sub.add_parser("line")
    sl.add_argument("-v", "--voice", required=True)
    sl.add_argument("-t", "--text", required=True)
    sl.add_argument("-o", "--out", required=True)
    sb = sub.add_parser("block")
    sb.add_argument("script")
    sb.add_argument("-o", "--out", required=True)
    sd = sub.add_parser("voice-design", help="Referenzstimme aus einer Voice-Design-Vorlage rendern")
    sd.add_argument("workflow")
    sd.add_argument("-o", "--out", required=True, help="Ziel-WAV, am besten im ComfyUI-Ordner input")
    sd.add_argument("-t", "--text", default=REFERENCE_TEXT)
    sub.add_parser("worker")
    args = p.parse_args(argv)
    cfg = load_config()

    if args.cmd == "worker":
        worker(cfg)
        return 0
    if args.cmd == "status":
        if cfg.get("backend", "direct") == "direct":
            d = cfg["direct"]
            env_da = os.path.isdir(os.path.join(d["root"], "qwen_tts_env"))
            print("Backend direct,", "qwen_tts_env da" if env_da else "qwen_tts_env FEHLT", "in", d["root"])
            return 0 if env_da else 1
        api = Comfy(cfg["comfy_url"])
        print("läuft" if api.alive() else "nicht erreichbar", cfg["comfy_url"])
        return 0 if api.alive() else 1
    if args.cmd == "start":
        ensure_running(cfg)
        return 0
    if args.cmd == "probe":
        probe(args.workflow)
        return 0
    if args.cmd == "line":
        api = ensure_running(cfg)
        path, secs = render_line(api, cfg, args.voice, args.text, cfg["work_dir"])
        audio = decode_audio(path, cfg["sample_rate"])
        write_audio(args.out, normalize(audio), cfg["sample_rate"], cfg["mp3_bitrate"])
        log(f"Fertig: {args.out} ({len(audio)/cfg['sample_rate']:.1f}s Audio, {secs:.1f}s Renderzeit)")
        return 0
    if args.cmd == "block":
        render_block(cfg, args.script, args.out)
        return 0
    if args.cmd == "voice-design":
        api = ensure_running(cfg)
        path, secs = render_line(api, cfg, "design", args.text, cfg["work_dir"], vcfg={"workflow": args.workflow})
        audio = decode_audio(path, cfg["sample_rate"])
        out = args.out if args.out.lower().endswith(".wav") else args.out + ".wav"
        write_audio(out, normalize(audio), cfg["sample_rate"], cfg["mp3_bitrate"])
        log(f"Referenz: {out} ({len(audio)/cfg['sample_rate']:.1f}s, {secs:.1f}s Renderzeit)")
        log("ref_text für die Clone-Vorlage: " + args.text)
        return 0
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"FEHLER: {e}")
        sys.exit(1)
