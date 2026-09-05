#!/usr/bin/env python3
"""
FoxRadio TTS-Renderer: rendert Dialogzeilen über die ComfyUI-API (Qwen3-TTS)
und schneidet sie zu einem Block zusammen.

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

Skriptformat (block): eine Zeile pro Sprecher, "A: Text" oder "B: Text".
Leerzeile = längere Pause. Zeilen mit # sind Kommentare.

Konfiguration: foxtts.json neben diesem Skript (siehe foxtts.example.json).
Pro Stimme ein Workflow, in ComfyUI über "Save (API Format)" exportiert.
Das Skript ersetzt darin nur den Text des TTS-Knotens.
"""

import argparse
import copy
import json
import os
import subprocess
import sys
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
}

TEXT_INPUT_NAMES = ("text", "target_text")


# ----------------------------------------------------------------------------
# Konfiguration
# ----------------------------------------------------------------------------

def load_config():
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
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


def ensure_running(cfg):
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


def parse_script(path):
    """Liefert Liste von ("line", voice, text) oder ("pause",)."""
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
            items.append(("line", voice.strip(), text.strip()))
    while items and items[-1][0] == "pause":
        items.pop()
    return items


def render_block(cfg, script_path, out_path):
    import numpy as np
    items = parse_script(script_path)
    lines = [i for i in items if i[0] == "line"]
    log(f"{len(lines)} Zeilen aus {script_path}")
    api = ensure_running(cfg)
    work = os.path.join(cfg["work_dir"], os.path.splitext(os.path.basename(out_path))[0])
    os.makedirs(work, exist_ok=True)
    sr = cfg["sample_rate"]
    silence = lambda ms: np.zeros(int(sr * ms / 1000), dtype=np.int16)
    parts, stats, total = [], [], 0.0
    n = 0
    for item in items:
        if item[0] == "pause":
            parts.append(silence(cfg["paragraph_pause_ms"]))
            continue
        _, voice, text = item
        n += 1
        path, secs = render_line(api, cfg, voice, text, work)
        total += secs
        audio = decode_audio(path, sr)
        if parts:
            parts.append(silence(cfg["pause_ms"]))
        start_s = sum(len(x) for x in parts) / sr
        parts.append(audio)
        stats.append({"n": n, "voice": voice, "chars": len(text), "render_s": round(secs, 2),
                      "audio_s": round(len(audio) / sr, 2), "start_s": round(start_s, 2),
                      "end_s": round(start_s + len(audio) / sr, 2), "file": os.path.basename(path)})
        log(f"[{n}/{len(lines)}] {voice}: {secs:5.1f}s Render, {len(audio)/sr:5.1f}s Audio, {len(text)} Zeichen")
    block = normalize(np.concatenate(parts))
    write_audio(out_path, block, sr, cfg["mp3_bitrate"])
    dur = len(block) / sr
    summary = {"script": script_path, "out": out_path, "lines": len(lines), "audio_s": round(dur, 1),
               "render_s": round(total, 1), "realtime_factor": round(total / dur, 2) if dur else None,
               "per_line": stats}
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
    args = p.parse_args(argv)
    cfg = load_config()

    if args.cmd == "status":
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
