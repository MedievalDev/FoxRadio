#!/usr/bin/env python3
"""Einen einzelnen Block in die Playlist des Tages eintragen und hochladen.

    python einspielen.py --mp3 work/sonder/2100.mp3 --slot 21:00 \
        --titel "Sondersendung: The Lantern of the Laughless Saint" \
        --abschnitte work/sonder/2100.abschnitte.json

Fuer Sondersendungen ausserhalb des Nachtlaufs. Laedt playlist.json und
articles.json des Tages, ergaenzt den Block, sortiert nach Uhrzeit und legt
alles wieder auf dem Webspace ab. Ohne --upload wird nur lokal geschrieben.
"""

import argparse
import json
import os
import sys
import time
from datetime import date as _date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import foxtts   # noqa: E402
import night    # noqa: E402


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def lade(pfad, standard):
    if os.path.exists(pfad):
        with open(pfad, encoding="utf-8") as f:
            return json.load(f)
    return standard


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--mp3", required=True)
    p.add_argument("--slot", required=True)
    p.add_argument("--titel", required=True)
    p.add_argument("--abschnitte", help="<slot>.abschnitte.json der Sondersendung")
    p.add_argument("--kind", default="special")
    p.add_argument("--date")
    p.add_argument("--no-upload", action="store_true")
    args = p.parse_args(argv)

    cfg = night.load_config()
    tag = _date.fromisoformat(args.date) if args.date else _date.today()
    tag_s = tag.isoformat()
    day_dir = os.path.join(cfg["work_dir"], tag_s)
    os.makedirs(day_dir, exist_ok=True)

    mp3 = os.path.abspath(args.mp3)
    if not os.path.exists(mp3):
        sys.exit(f"fehlt: {mp3}")
    name = args.slot.replace(":", "") + ".mp3"
    ziel = os.path.join(day_dir, name)
    if os.path.abspath(ziel) != mp3:
        with open(mp3, "rb") as q, open(ziel, "wb") as z:
            z.write(q.read())

    tcfg = foxtts.load_config()
    dauer = len(foxtts.decode_audio(ziel, tcfg["sample_rate"])) / tcfg["sample_rate"]

    # Playlist ergaenzen
    pl_pfad = os.path.join(day_dir, "playlist.json")
    pl = lade(pl_pfad, {"date": tag_s, "blocks": []})
    pl["date"] = tag_s
    pl["blocks"] = [b for b in pl.get("blocks", []) if b.get("slot") != args.slot]
    pl["blocks"].append({"slot": args.slot, "file": name, "kind": args.kind,
                         "duration_s": round(dauer, 1), "title": args.titel, "theme_part": None})
    pl["blocks"].sort(key=lambda b: b["slot"])

    # Artikel ergaenzen: je Abschnitt einer, mit Zeitmarke zum Nachhoeren
    ar_pfad = os.path.join(day_dir, "articles.json")
    ar = lade(ar_pfad, {"date": tag_s, "articles": []})
    ar["date"] = tag_s
    ar["articles"] = [a for a in ar.get("articles", []) if a.get("slot") != args.slot]
    if args.abschnitte and os.path.exists(args.abschnitte):
        with open(args.abschnitte, encoding="utf-8") as f:
            meta = json.load(f)
        summary_pfad = os.path.splitext(mp3)[0] + ".json"
        per_line = lade(summary_pfad, {}).get("per_line", [])
        gesprochen = [l for l in per_line if l.get("voice") != "J"]
        for i, ab in enumerate(meta.get("abschnitte", []), 1):
            s = ab["line_start"]
            e = min(ab["line_end"], len(gesprochen) - 1)
            start = gesprochen[s]["start_s"] if s < len(gesprochen) else 0
            ende = gesprochen[e]["end_s"] if e >= 0 and e < len(gesprochen) else dauer
            ar["articles"].append({
                "id": f"{args.slot.replace(':', '')}-{i:02d}", "slot": args.slot, "rubric": "sondersendung",
                "title": ab.get("titel") or f"Teil {i}", "teaser": args.titel,
                "body": ab.get("zusammenfassung") or "", "source_name": "FoxRadio", "source_url": "",
                "image": None, "audio_file": name, "audio_start_s": round(start, 2), "audio_end_s": round(ende, 2),
            })
    for pfad, daten in ((pl_pfad, pl), (ar_pfad, ar)):
        with open(pfad, "w", encoding="utf-8") as f:
            json.dump(daten, f, ensure_ascii=False, indent=2)
    log(f"Playlist: {len(pl['blocks'])} Bloecke, Artikel: {len(ar['articles'])}, Block {args.slot} {dauer / 60:.1f} min")

    if args.no_upload:
        return 0
    log("Upload")
    with night.Uploader(cfg["upload"]) as up:
        up.put(ziel, f"{tag_s}/{name}")
        for pfad, remote in ((pl_pfad, "playlist.json"), (ar_pfad, "articles.json")):
            up.put(pfad, f"{tag_s}/{os.path.basename(pfad)}")
            up.put(pfad, remote)
    night.write_status(cfg, tag, True, f"{len(pl['blocks'])} Blöcke, davon Sondersendung um {args.slot}",
                       [b["slot"] for b in pl["blocks"]])
    log("Fertig, auf dem Webspace")
    return 0


if __name__ == "__main__":
    sys.exit(main())
