#!/usr/bin/env python3
"""
FoxRadio-Nachtlauf: Feeds, Wetter, Texte, Rendern, Schnitt, Upload, Status.

    python night.py run [--date 2026-09-08] [--backend fake] [--no-upload] [--no-shutdown]
    python night.py upload-status "Text"      nur eine Statusmeldung hochladen

Konfiguration: night.json neben diesem Skript (siehe night.example.json).
Bei Fehlern wird status.json mit ok=false hochgeladen, damit die App
Bescheid weiß, und optional eine ntfy-Nachricht geschickt.
"""

import argparse
import ftplib
import io
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
import urllib.request
from datetime import date as _date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import feeds  # noqa: E402
import foxtts  # noqa: E402
import writer  # noqa: E402

CONFIG_PATH = os.path.join(HERE, "night.json")
DEFAULTS = {
    "work_dir": os.path.join(HERE, "work"),
    "upload": {"method": "none"},
    "ntfy_topic": "",
    "shutdown": False,
    "shutdown_delay_s": 120,
    "keep_days": 7,
}


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def load_config():
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    return cfg


# ----------------------------------------------------------------------------
# Upload
# ----------------------------------------------------------------------------

class Uploader:
    """method: none | dir (Kopie in einen Ordner) | ftp (FTP mit TLS wenn möglich)."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.ftp = None

    def __enter__(self):
        m = self.cfg["method"]
        if m == "ftp":
            host, user, pw = self.cfg["host"], self.cfg["user"], self.cfg["password"]
            try:
                self.ftp = ftplib.FTP_TLS(host, timeout=60)
                self.ftp.login(user, pw)
                self.ftp.prot_p()
            except Exception:
                self.ftp = ftplib.FTP(host, timeout=60)
                self.ftp.login(user, pw)
            self.ftp.cwd(self.cfg.get("remote_dir", "/"))
        return self

    def __exit__(self, *a):
        if self.ftp:
            try:
                self.ftp.quit()
            except Exception:
                pass

    def _ftp_mkdirs(self, path):
        cur = self.ftp.pwd()
        for part in path.strip("/").split("/"):
            if not part:
                continue
            try:
                self.ftp.cwd(part)
            except ftplib.error_perm:
                self.ftp.mkd(part)
                self.ftp.cwd(part)
        self.ftp.cwd(cur)

    def put(self, local, remote):
        m = self.cfg["method"]
        if m == "none":
            return
        if m == "dir":
            dest = os.path.join(self.cfg["path"], remote)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copyfile(local, dest)
            return
        if m == "ftp":
            d = os.path.dirname(remote)
            if d:
                self._ftp_mkdirs(d)
            with open(local, "rb") as f:
                self.ftp.storbinary(f"STOR {remote}", f)
            return
        raise ValueError(f"unbekannte Upload-Methode {m}")

    def put_bytes(self, data, remote):
        tmp = os.path.join(HERE, "work", ".upload.tmp")
        os.makedirs(os.path.dirname(tmp), exist_ok=True)
        with open(tmp, "wb") as f:
            f.write(data)
        self.put(tmp, remote)


def notify(cfg, title, text):
    topic = cfg.get("ntfy_topic")
    if not topic:
        return
    try:
        req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=text.encode("utf-8"),
                                     headers={"Title": title.encode("latin-1", "replace")})
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:
        log(f"ntfy fehlgeschlagen: {e}")


def write_status(cfg, day, ok, message, blocks=None, upload=True):
    status = {"ok": ok, "date": day.isoformat(), "generated_at": datetime.now(timezone.utc).isoformat(),
              "message": message, "blocks": blocks or []}
    data = json.dumps(status, ensure_ascii=False, indent=2).encode("utf-8")
    day_dir = os.path.join(cfg["work_dir"], day.isoformat())
    os.makedirs(day_dir, exist_ok=True)
    with open(os.path.join(day_dir, "status.json"), "wb") as f:
        f.write(data)
    if upload:
        try:
            with Uploader(cfg["upload"]) as up:
                up.put_bytes(data, "status.json")
        except Exception as e:
            log(f"Status-Upload fehlgeschlagen: {e}")
    return status


# ----------------------------------------------------------------------------
# Lauf
# ----------------------------------------------------------------------------

def download_image(url, dest):
    try:
        data = feeds.fetch(url, timeout=20, max_bytes=4_000_000)
    except Exception:
        return False
    try:
        from PIL import Image  # in der ComfyUI-Python vorhanden
        img = Image.open(io.BytesIO(data)).convert("RGB")
        img.thumbnail((1200, 1200))
        img.save(dest, "JPEG", quality=82)
    except Exception:
        with open(dest, "wb") as f:
            f.write(data)
    return True


def run(cfg, day, backend=None, upload=True, shutdown=None):
    t_start = time.time()
    day_dir = os.path.join(cfg["work_dir"], day.isoformat())
    os.makedirs(day_dir, exist_ok=True)
    fcfg = feeds.load_config()
    wcfg = writer.load_config()
    if backend:
        wcfg["backend"] = backend
    tcfg = foxtts.load_config()

    # 1. Feeds und Wetter
    log("Feeds")
    fres = feeds.collect(fcfg)
    with open(os.path.join(day_dir, "feeds.json"), "w", encoding="utf-8") as f:
        json.dump(fres, f, ensure_ascii=False, indent=2)
    if not fres["items"]:
        raise RuntimeError("keine Meldungen aus den Feeds, Fehler: " + "; ".join(fres["errors"]))
    weather = None
    try:
        weather = feeds.weather(fcfg)
        with open(os.path.join(day_dir, "weather.json"), "w", encoding="utf-8") as f:
            json.dump(weather, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"Wetter fehlgeschlagen, Blöcke ohne Wetter: {e}")

    # 2. Texte
    log("Texte")
    blocks = writer.plan_blocks(fres["items"], wcfg["slots"])
    metas = []
    for b in blocks:
        try:
            metas.append(writer.write_block(wcfg, b, weather, day, day_dir))
        except Exception as e:
            log(f"Block {b['slot']} ohne Text: {e}")
    if not metas:
        raise RuntimeError("kein einziger Block hat Text bekommen")

    # 3. Rendern
    log("ComfyUI")
    foxtts.ensure_running(tcfg)
    playlist, articles = [], []
    for m in metas:
        name = m["slot"].replace(":", "")
        out = os.path.join(day_dir, f"{name}.mp3")
        try:
            summary = foxtts.render_block(tcfg, os.path.join(day_dir, m["script"]), out)
        except Exception as e:
            log(f"Block {m['slot']} nicht gerendert: {e}")
            continue
        playlist.append({"slot": m["slot"], "file": os.path.basename(out), "kind": m["kind"],
                         "duration_s": summary["audio_s"], "title": f"{m['slot']} Block"})
        per_line = summary["per_line"]
        for a in m["articles"]:
            s = per_line[a["line_start"]]["start_s"] if a["line_start"] < len(per_line) else 0
            e = per_line[a["line_end"]]["end_s"] if a["line_end"] < len(per_line) else summary["audio_s"]
            a = dict(a)
            a.update({"audio_file": os.path.basename(out), "audio_start_s": s, "audio_end_s": e})
            articles.append(a)
    if not playlist:
        raise RuntimeError("kein Block gerendert")

    # 4. Bilder
    img_dir = os.path.join(day_dir, "img")
    os.makedirs(img_dir, exist_ok=True)
    for a in articles:
        a["image"] = None
        if a.get("image_url"):
            dest = os.path.join(img_dir, f"{a['id']}.jpg")
            if download_image(a["image_url"], dest):
                a["image"] = f"img/{a['id']}.jpg"

    # 5. Dateien
    pl = {"date": day.isoformat(), "generated_at": datetime.now(timezone.utc).isoformat(), "blocks": playlist}
    ar = {"date": day.isoformat(), "articles": articles}
    with open(os.path.join(day_dir, "playlist.json"), "w", encoding="utf-8") as f:
        json.dump(pl, f, ensure_ascii=False, indent=2)
    with open(os.path.join(day_dir, "articles.json"), "w", encoding="utf-8") as f:
        json.dump(ar, f, ensure_ascii=False, indent=2)

    # 6. Upload: Tagesordner plus Wurzeldateien, die die App zuerst liest
    if upload:
        log("Upload")
        with Uploader(cfg["upload"]) as up:
            for b in playlist:
                up.put(os.path.join(day_dir, b["file"]), f"{day.isoformat()}/{b['file']}")
            for a in articles:
                if a.get("image"):
                    up.put(os.path.join(day_dir, a["image"]), f"{day.isoformat()}/{a['image']}")
            up.put(os.path.join(day_dir, "playlist.json"), f"{day.isoformat()}/playlist.json")
            up.put(os.path.join(day_dir, "articles.json"), f"{day.isoformat()}/articles.json")
            up.put(os.path.join(day_dir, "playlist.json"), "playlist.json")
            up.put(os.path.join(day_dir, "articles.json"), "articles.json")

    msg = f"{len(playlist)} Blöcke, {len(articles)} Artikel, {round((time.time() - t_start) / 60)} Minuten"
    write_status(cfg, day, True, msg, [b["slot"] for b in playlist], upload=upload)
    log("Fertig: " + msg)
    cleanup(cfg)

    do_shutdown = cfg["shutdown"] if shutdown is None else shutdown
    if do_shutdown and os.name == "nt":
        log(f"Shutdown in {cfg['shutdown_delay_s']}s")
        subprocess.run(["shutdown", "/s", "/t", str(cfg["shutdown_delay_s"])])


def cleanup(cfg):
    keep = cfg.get("keep_days", 7)
    root = cfg["work_dir"]
    if not os.path.isdir(root):
        return
    days = sorted(d for d in os.listdir(root) if len(d) == 10 and d[4] == "-" and os.path.isdir(os.path.join(root, d)))
    for d in days[:-keep] if keep else []:
        shutil.rmtree(os.path.join(root, d), ignore_errors=True)


def main(argv=None):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sr = sub.add_parser("run")
    sr.add_argument("--date")
    sr.add_argument("--backend")
    sr.add_argument("--no-upload", action="store_true")
    sr.add_argument("--no-shutdown", action="store_true")
    su = sub.add_parser("upload-status")
    su.add_argument("text")
    args = p.parse_args(argv)
    cfg = load_config()
    day = _date.fromisoformat(args.date) if getattr(args, "date", None) else _date.today()
    if args.cmd == "upload-status":
        write_status(cfg, day, False, args.text)
        return 0
    try:
        run(cfg, day, backend=args.backend, upload=not args.no_upload,
            shutdown=False if args.no_shutdown else None)
        return 0
    except Exception as e:
        log("FEHLER: " + "".join(traceback.format_exception_only(type(e), e)).strip())
        traceback.print_exc()
        write_status(cfg, day, False, f"Nachtlauf fehlgeschlagen: {type(e).__name__}: {e}", upload=not args.no_upload)
        notify(cfg, "FoxRadio Nachtlauf fehlgeschlagen", str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
