#!/usr/bin/env python3
"""
Textgenerierung für die FoxRadio-Blöcke: feste Rubriken, enge Prompts,
zwei Sprecher. Aus den Meldungen (feeds.json) und dem Wetter entsteht pro
Sendeplatz ein Dialogskript im foxtts-Format plus Artikel für die App.

Backends (writer.json, "backend"):
    claude-cli   Claude Code headless: `claude -p` (Standard, nutzt dein Abo)
    api          Anthropic-SDK (pip install anthropic, ANTHROPIC_API_KEY)
    fake         kanned Antworten zum Testen der Pipeline

    python writer.py plan  --feeds work/feeds.json            zeigt die Zuteilung der Meldungen
    python writer.py write --feeds work/feeds.json --weather work/weather.json --out work/scripts
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import date as _date

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "writer.json")

DEFAULTS = {
    "backend": "claude-cli",
    "claude_cli": "claude",
    "claude_cli_model": "opus",
    "api_model": "claude-opus-5",
    "slots": ["07:00", "08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00"],
    "morning_lines": [30, 45],
    "hour_lines": [8, 14],
    "closing_lines": [6, 10],
    # Feste Rollen je Rubrik. Kein Wechselgespraech: jede Stimme spricht ihre
    # Rubrik am Stueck, die andere hoechstens mit einer kurzen Uebergabe.
    "speaker_a": ("Mann, sachlich. Begrüßt, nennt Uhrzeit und Datum, macht die Entwickler- und KI-Themen, "
                  "die Anthropic-Neuigkeiten und stellt das Indie-Spiel vor. Beendet den Block."),
    "speaker_b": ("Frau, lockerer, mit eigener Meinung, ohne Floskeln. Macht in der Morning Show das Wetter "
                  "als Drei-Tage-Übersicht und in jedem Block alle Gaming-News am Stück, sonst nichts."),
}

WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember"]

SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"speaker": {"type": "string", "enum": ["A", "B"]}, "text": {"type": "string"}},
                "required": ["speaker", "text"],
                "additionalProperties": False,
            },
        },
        "articles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string"},
                    "title": {"type": "string"},
                    "teaser": {"type": "string"},
                    "body": {"type": "string"},
                    "line_start": {"type": "integer"},
                    "line_end": {"type": "integer"},
                },
                "required": ["item_id", "title", "teaser", "body", "line_start", "line_end"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["lines", "articles"],
    "additionalProperties": False,
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
# Zuteilung der Meldungen auf die Sendeplätze
# ----------------------------------------------------------------------------

def plan_blocks(items, slots):
    """Verteilt Meldungen ohne Wiederholung. Morning Show bekommt die meisten."""
    pools = {r: [i for i in items if i["rubric"] == r] for r in ("gaming", "dev", "anthropic", "indie")}

    def take(rubric, n):
        got = pools[rubric][:n]
        pools[rubric] = pools[rubric][n:]
        return got

    blocks = []
    for idx, slot in enumerate(slots):
        kind = "morning" if idx == 0 else ("closing" if idx == len(slots) - 1 else "hour")
        if kind == "morning":
            picked = take("gaming", 3) + take("dev", 2) + take("anthropic", 3) + take("indie", 2)
        elif kind == "closing":
            picked = take("gaming", 1) + take("indie", 1)
        else:
            picked = take("gaming", 2 if idx % 2 else 1)
            picked += take("dev", 1) if idx % 2 else take("anthropic", 1) or take("dev", 1)
            if idx % 3 == 0:
                picked += take("indie", 1)
        blocks.append({"slot": slot, "kind": kind, "items": picked})
    return blocks


# ----------------------------------------------------------------------------
# Prompt
# ----------------------------------------------------------------------------

def german_date(d):
    return f"{WEEKDAYS[d.weekday()]}, der {d.day}. {MONTHS[d.month - 1]}"


def build_prompt(cfg, block, weather, day):
    lo, hi = cfg["morning_lines"] if block["kind"] == "morning" else (
        cfg["closing_lines"] if block["kind"] == "closing" else cfg["hour_lines"])
    hour = int(block["slot"][:2])
    # Wetter nur als Drei-Tage-Uebersicht in der Morning Show (B). Das Stundenwetter
    # waere um sieben schon Stunden alt, das sagt das Handy live an (Weather.kt).
    w = ""
    if weather and weather.get("days") and block["kind"] == "morning":
        w = "Wetter " + weather["place"] + " für die Übersicht: " + " ".join(
            f"{t['name'].capitalize()} ({t['weekday']}): {t['tmin']} bis {t['tmax']} Grad, {t['tendenz']}, {t['text']}."
            for t in weather["days"][:3])
    news = "\n".join(
        f"- [{it['id']}] ({it['rubric']}, {it['source']}) {it['title']}\n  {it.get('summary') or ''}".rstrip()
        for it in block["items"]
    ) or "- (keine Meldungen, nur Uhrzeit und Wetter)"

    if block["kind"] == "morning":
        struktur = ("1. A: Begrüßung, Datum, Uhrzeit, kurz was heute ansteht, Übergabe an B (2 bis 4 Zeilen)\n"
                    "2. B: Wetter als Drei-Tage-Übersicht in zwei bis drei Zeilen, Muster: heute zwölf bis 25 Grad, "
                    "überwiegend trocken, morgen sonnig, 16 bis 22 Grad, übermorgen Regen (nur wenn Wetterdaten da sind)\n"
                    "3. B: alle Gaming-News am Stück, die größte Meldung ausführlicher (je Meldung 3 bis 5 Zeilen), "
                    "am Ende Übergabe zurück an A\n"
                    "4. A: Entwickler- und KI-Themen (je 2 bis 4 Zeilen)\n"
                    "5. A: Anthropic-Neuigkeiten, falls vorhanden (je 2 bis 3 Zeilen)\n"
                    "6. A: Indie-Spiel vorstellen (je 3 bis 4 Zeilen)\n"
                    "7. A: Verabschiedung, Hinweis auf den nächsten Block um acht (1 bis 2 Zeilen)")
    elif block["kind"] == "closing":
        struktur = ("1. A: Uhrzeit, kurzer Tagesabschluss (2 Zeilen)\n"
                    "2. Gaming-Meldung durch B, alles andere durch A (je 2 bis 3 Zeilen)\n"
                    "3. A: Verabschiedung bis morgen (1 bis 2 Zeilen)")
    else:
        struktur = ("1. A: Uhrzeit, was in diesem Block kommt (1 Zeile)\n"
                    "2. B: die Gaming-Meldungen am Stück (je 2 bis 4 Zeilen), falls welche dabei sind\n"
                    "3. A: Entwickler-, KI-, Anthropic- oder Indie-Meldungen (je 2 bis 4 Zeilen)\n"
                    "4. A: kurzer Abschluss mit Hinweis auf den nächsten Block (1 Zeile)")

    return f"""Du schreibst ein kurzes Radioskript für FoxRadio, ein persönliches Programm für einen einzigen Hörer (Marco, Zerspanungsmechaniker, arbeitet meist in der Montage in einer Halle in Ellwangen und entwickelt nebenbei ein Rollenspiel mit Unreal Engine). Zwei Sprecher:
A: {cfg['speaker_a']}
B: {cfg['speaker_b']}

Datum: {german_date(day)}. Sendeplatz: {hour} Uhr. {w}

Meldungen (nur diese Fakten verwenden, nichts dazuerfinden, keine Zahlen raten):
{news}

Struktur, genau in dieser Reihenfolge:
{struktur}

Regeln:
- {lo} bis {hi} Zeilen insgesamt. A beginnt und beendet.
- Kein Wechselgespräch: Sprecher wechseln nur an Rubrikgrenzen. Innerhalb einer Rubrik spricht die zuständige Stimme alle Zeilen am Stück. Beim Rubrikwechsel höchstens eine kurze Übergabe (ein Satz), keine Rückfragen, kein Hin und Her.
- Deutsch, gesprochene Sprache, kurze Sätze. Der Text wird von einer Sprachsynthese vorgelesen: keine URLs, keine Abkürzungen, keine Sonderzeichen, keine Klammern, keine Gedankenstriche, Zahlen bis zwölf als Wort.
- Wenn eine Meldung unklar ist, lieber weglassen als raten. Nur genannte Fakten, keine Zahlen erfinden.
- Kein Schreib-Slop: keine Kontraste der Art "nicht X, sondern Y"; keine Anläufe wie "Was viele nicht wissen", "Das Beste daran", "Ganz ehrlich"; kein Bedeutungsgetue wie "Meilenstein", "unterstreicht", "wegweisend", "zeigt einmal mehr"; keine unbenannten Quellen wie "Experten sind sich einig"; keine Fazit-Sätze am Ende ("Alles in allem", "Man darf gespannt sein"); keine tiefsinnigen Schlusspointen; kein Rotieren von Begriffen für dasselbe Ding; keine leeren Adverbien wie "absolut", "wirklich", "tatsächlich", "spannend". Fakten sagen, Wertung nur mit Begründung.

Antworte nur mit JSON in dieser Form:
{{"lines": [{{"speaker": "A", "text": "..."}}, ...],
 "articles": [{{"item_id": "n01", "title": "Titel für die App", "teaser": "ein Satz", "body": "drei bis sechs Sätze Zusammenfassung, nur aus den gegebenen Fakten", "line_start": 5, "line_end": 8}}, ...]}}
line_start und line_end sind Indizes in lines (nullbasiert, inklusive) der Zeilen, die zu dieser Meldung gehören. Für jede verwendete Meldung genau einen Artikel."""


# ----------------------------------------------------------------------------
# Backends
# ----------------------------------------------------------------------------

def extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("keine JSON-Antwort")
    return json.loads(text[start:end + 1])


def call_claude_cli(cfg, prompt):
    cmd = [cfg["claude_cli"], "-p", "--output-format", "json", "--model", cfg["claude_cli_model"]]
    res = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                         timeout=600, shell=(os.name == "nt"))
    if res.returncode != 0:
        raise RuntimeError(f"claude -p Exit {res.returncode}: {res.stderr[:500]}")
    data = json.loads(res.stdout)
    text = data.get("result") if isinstance(data, dict) else None
    if not text:
        raise RuntimeError(f"claude -p ohne result: {res.stdout[:300]}")
    return extract_json(text)


def call_api(cfg, prompt):
    import anthropic
    client = anthropic.Anthropic()
    with client.messages.stream(
        model=cfg["api_model"],
        max_tokens=16000,
        messages=[{"role": "user", "content": prompt}],
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
    ) as stream:
        response = stream.get_final_message()
    if response.stop_reason == "refusal":
        raise RuntimeError("API hat abgelehnt")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def call_fake(cfg, prompt, block):
    lines = [{"speaker": "A", "text": f"Es ist {int(block['slot'][:2])} Uhr, hier ist FoxRadio."},
             {"speaker": "B", "text": "Und ich bin auch da."}]
    articles = []
    for it in block["items"]:
        start = len(lines)
        lines.append({"speaker": "A", "text": f"{it['title']}."})
        lines.append({"speaker": "B", "text": "Das schauen wir uns an."})
        articles.append({"item_id": it["id"], "title": it["title"], "teaser": it["title"],
                         "body": it.get("summary") or it["title"], "line_start": start, "line_end": len(lines) - 1})
    lines.append({"speaker": "A", "text": "Bis zum nächsten Block."})
    return {"lines": lines, "articles": articles}


def generate(cfg, block, prompt):
    b = cfg["backend"]
    if b == "claude-cli":
        return call_claude_cli(cfg, prompt)
    if b == "api":
        return call_api(cfg, prompt)
    if b == "fake":
        return call_fake(cfg, prompt, block)
    raise ValueError(f"unbekanntes Backend {b}")


def validate(data, block):
    lines = data.get("lines") or []
    if len(lines) < 2:
        raise ValueError("zu wenig Zeilen")
    for l in lines:
        if l.get("speaker") not in ("A", "B") or not (l.get("text") or "").strip():
            raise ValueError(f"kaputte Zeile: {l}")
    ids = {it["id"] for it in block["items"]}
    arts = []
    for a in data.get("articles") or []:
        if a.get("item_id") not in ids:
            continue
        s, e = int(a.get("line_start", 0)), int(a.get("line_end", 0))
        s = max(0, min(s, len(lines) - 1))
        e = max(s, min(e, len(lines) - 1))
        a["line_start"], a["line_end"] = s, e
        arts.append(a)
    data["articles"] = arts
    return data


# ----------------------------------------------------------------------------
# Schreiben
# ----------------------------------------------------------------------------

def write_block(cfg, block, weather, day, out_dir):
    prompt = build_prompt(cfg, block, weather, day)
    t0 = time.time()
    data = validate(generate(cfg, block, prompt), block)
    name = block["slot"].replace(":", "")
    os.makedirs(out_dir, exist_ok=True)
    script_path = os.path.join(out_dir, f"{name}.txt")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(f"# FoxRadio {day.isoformat()} {block['slot']} ({block['kind']})\n")
        for l in data["lines"]:
            f.write(f"{l['speaker']}: {l['text'].strip()}\n")
    by_id = {it["id"]: it for it in block["items"]}
    articles = []
    for a in data["articles"]:
        it = by_id[a["item_id"]]
        articles.append({
            "id": f"{name}-{a['item_id']}", "slot": block["slot"], "rubric": it["rubric"],
            "title": a["title"], "teaser": a["teaser"], "body": a["body"],
            "source_name": it["source"], "source_url": it["link"], "image_url": it.get("image"),
            "line_start": a["line_start"], "line_end": a["line_end"],
        })
    meta = {"slot": block["slot"], "kind": block["kind"], "script": os.path.basename(script_path),
            "lines": len(data["lines"]), "articles": articles, "seconds": round(time.time() - t0, 1)}
    with open(os.path.join(out_dir, f"{name}.articles.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    log(f"{block['slot']}: {len(data['lines'])} Zeilen, {len(articles)} Artikel, {meta['seconds']}s")
    return meta


def main(argv=None):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("plan")
    sp.add_argument("--feeds", required=True)
    sw = sub.add_parser("write")
    sw.add_argument("--feeds", required=True)
    sw.add_argument("--weather")
    sw.add_argument("--out", required=True)
    sw.add_argument("--date")
    sw.add_argument("--only", help="nur diesen Slot, z. B. 07:00")
    sw.add_argument("--backend")
    args = p.parse_args(argv)
    cfg = load_config()
    if getattr(args, "backend", None):
        cfg["backend"] = args.backend
    with open(args.feeds, encoding="utf-8") as f:
        items = json.load(f)["items"]
    blocks = plan_blocks(items, cfg["slots"])
    if args.cmd == "plan":
        for b in blocks:
            print(f"{b['slot']} {b['kind']:8s} " + ", ".join(f"{it['id']}:{it['rubric']}" for it in b["items"]))
        return 0
    weather = None
    if args.weather and os.path.exists(args.weather):
        with open(args.weather, encoding="utf-8") as f:
            weather = json.load(f)
    day = _date.fromisoformat(args.date) if args.date else _date.today()
    failed = 0
    for b in blocks:
        if args.only and b["slot"] != args.only:
            continue
        try:
            write_block(cfg, b, weather, day, args.out)
        except Exception as e:
            failed += 1
            log(f"FEHLER {b['slot']}: {type(e).__name__}: {e}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
