#!/usr/bin/env python3
"""Sondersendung: eine lange Sendung zu einem Termin, ausserhalb des Tagesplans.

    python sondershow.py --thema "The Lantern of the Laughless Saint" --steam 3849000 \
        --slot 21:00 --minuten 20 --feeds work/feeds_v2.json --out work/sonder

Baut das Skript in mehreren Zuegen (Claude schreibt sonst zu kurz), rendert es
mit foxtts und legt Skript, MP3 und Artikel im Zielordner ab. Mit --upload
kommt der Block in die Playlist des Tages auf dem Webspace.

Die Teile stehen in TEILE und lassen sich ueber --teile auswaehlen.
"""

import argparse
import json
import os
import sys
import time
from datetime import date as _date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import feeds      # noqa: E402
import writer     # noqa: E402
import foxtts     # noqa: E402


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


TEILE = {
    "heute": {
        "titel": "Was heute war",
        "anteil": 0.14,
        "auftrag": ("Die Meldungen von heute, laenger und mit mehr Meinung als tagsueber. B nimmt die "
                    "Gaming-Meldungen am Stueck, A danach Spieleentwicklung und KI. Nur Meldungen, die "
                    "wirklich etwas hergeben, der Rest faellt weg."),
    },
    "woche": {
        "titel": "Die letzten Tage",
        "anteil": 0.16,
        "auftrag": ("Ein Rueckblick auf die Meldungen der letzten Tage. Keine Aufzaehlung, sondern zwei "
                    "bis drei Straenge, die sich durchziehen. Sag ehrlich 'die letzten Tage', nicht 'die "
                    "ganze Woche', wenn das Archiv nur wenige Tage umfasst."),
    },
    "spiel": {
        "titel": "Das Spiel: Welt und Systeme",
        "anteil": 0.24,
        "auftrag": ("Erste Haelfte des Hauptstuecks. Zwei Schwerpunkte: erstens worum es geht, also Welt, "
                    "Insel, Turm, Geschichte und Ton; zweitens die Systeme, also Kampf und Waffen, "
                    "Zauber, Alchemie, Quests mit mehreren Loesungen, Koop und das Amphitheater. "
                    "A fuehrt, B kommentiert je Schwerpunkt zwei bis vier Mal mit Substanz. "
                    "Entwicklung, Presse und Tipps kommen im naechsten Abschnitt, hier nicht vorwegnehmen."),
    },
    "spiel2": {
        "titel": "Das Spiel: Entwicklung und Einordnung",
        "anteil": 0.22,
        "auftrag": ("Zweite Haelfte des Hauptstuecks. Drei Schwerpunkte: erstens das Studio und das Tempo "
                    "der Entwicklung, also was seit dem Start in den Updates dazugekommen ist, mit "
                    "konkreten Beispielen aus den Updates; zweitens wie Presse und Rezensionen es sehen, "
                    "mit den Zahlen; drittens Tipps fuer den Einstieg und fuer wen das Spiel taugt, "
                    "gerade fuer jemanden, der selbst ein Rollenspiel baut. A fuehrt, B kommentiert."),
    },
    "rotation": {
        "titel": "Kurz vorgestellt",
        "anteil": 0.20,
        "auftrag": ("Zehn kleine Spiele der letzten Tage, jedes in zwei bis drei Zeilen, wie ein "
                    "Sammelartikel. Abwechselnd A und B, je Spiel bleibt eine Stimme. Sind weniger als "
                    "zehn brauchbare dabei, nimm nur die brauchbaren und sag die Zahl nicht."),
    },
}


def zeilen_fuer(minuten, anteil):
    """Eine gesprochene Zeile dauert rund sechs Sekunden."""
    n = int(minuten * 60 * anteil / 6.0)
    return max(4, n - 2), n + 3


def sammle_woche(cfg, tag, tage=7):
    out, seen = [], set()
    for back in range(0, tage + 1):
        p = os.path.join(cfg["work_dir"], (tag - timedelta(days=back)).isoformat(), "feeds.json")
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            for it in json.load(f).get("items", []):
                key = it["link"].split("?")[0]
                if key not in seen:
                    seen.add(key)
                    it = dict(it)
                    it["day"] = (tag - timedelta(days=back)).isoformat()
                    out.append(it)
    return out


def melde(items, rubriken=None, n=40):
    aus = [i for i in items if not rubriken or i["rubric"] in rubriken][:n]
    return "\n".join(f"- ({i.get('day', 'heute')}, {i['rubric']}, {i['source']}) {i['title']}\n  "
                     f"{(i.get('summary') or '')[:300]}".rstrip() for i in aus) or "- (nichts vorhanden)"


def recherche_spiel(cfg, name, appid):
    """Steam-Store, Rezensionszahlen und die letzten Updates als Quellentext."""
    quellen = []
    if appid:
        st = writer.steam_details(appid)
        if st:
            quellen.append({"name": f"Steam-Store: {st['name']}", "url": st["url"], "text": st["text"]})
        try:
            d = json.loads(feeds.fetch(f"https://store.steampowered.com/appreviews/{appid}"
                                       "?json=1&language=all&purchase_type=all&num_per_page=0", timeout=20))
            q = d["query_summary"]
            quellen.append({"name": "Steam-Rezensionen", "url": st["url"] if st else "",
                            "text": (f"Insgesamt {q.get('total_reviews')} Rezensionen, davon "
                                     f"{q.get('total_positive')} positiv und {q.get('total_negative')} negativ. "
                                     f"Steam nennt das {q.get('review_score_desc')}.")})
        except Exception as e:
            log(f"Rezensionen nicht geholt: {e}")
        try:
            news = feeds.parse_feed(feeds.fetch(f"https://store.steampowered.com/feeds/news/app/{appid}/"),
                                    {"name": "Steam", "rubric": "gaming"})
            text = "\n\n".join(f"{str(i['published'])[:10]} {i['title']}\n{feeds.strip_html(i['summary'], limit=700)}"
                               for i in news[:8])
            quellen.append({"name": f"Updates des Entwicklers ({len(news)} zuletzt)", "url": "", "text": text})
        except Exception as e:
            log(f"Updates nicht geholt: {e}")
    return quellen


def bau_prompt(cfg, teil, name, tag, minuten, quellen, items, woche, thema_name, vorher):
    lo, hi = zeilen_fuer(minuten, TEILE[teil]["anteil"])
    if teil == "heute":
        stoff = melde(items, n=30)
    elif teil == "woche":
        stoff = melde(woche, n=45)
    elif teil == "rotation":
        stoff = melde(woche + items, rubriken=("indie", "mods"), n=30)
    else:
        stoff = "\n\n".join(f"### {q['name']}\n{q['url']}\n{q['text']}" for q in quellen)
    lauf = ("Bereits gesendete Abschnitte dieser Sendung (nicht wiederholen):\n"
            + "\n".join(f"- {t}" for t in vorher)) if vorher else ""
    return f"""Du schreibst einen Abschnitt einer Sondersendung von FoxRadio, einem persoenlichen Radioprogramm fuer einen einzigen Hoerer (Zerspanungsmechaniker, meist in der Montage, entwickelt nebenbei ein Rollenspiel mit Unreal Engine 4.27; mag Two Worlds, Kingdom Come, Elden Ring, Skyblivion, Survival- und Open-World-Rollenspiele; mag keine rundenbasierten Spiele, kein Anime, keinen japanischen Content, keine Film- und Serienmeldungen). Der Hoerer wird nicht mit Namen angesprochen.

Zwei Sprecher:
A: {cfg['speaker_a']}
B: {cfg['speaker_b']}

Es ist Samstagabend, {writer.german_date(tag)}, 21 Uhr. Das ist eine lange Abendsendung, ruhiger und ausfuehrlicher als tagsueber, mit deutlich mehr Meinung von B.
Thema der Sendung im Mittelpunkt: {thema_name}.

Dieser Abschnitt: {TEILE[teil]['titel']}.
{TEILE[teil]['auftrag']}

{lauf}

Stoff (nur diese Fakten verwenden, nichts dazuerfinden, keine Zahlen raten, keine Wertungen erfinden, die nicht belegt sind):
{stoff}

Regeln:
- {lo} bis {hi} Zeilen. {"Beginne mit einer Begruessung, nenne Datum und Uhrzeit und sag in zwei Saetzen, was in dieser Sendung kommt." if teil == "heute" else "Steige ohne Begruessung ein, die Sendung laeuft schon."}
- {"Beende diesen Abschnitt mit einer Ueberleitung zum naechsten." if teil != "rotation" else "Beende die ganze Sendung mit einer kurzen Verabschiedung und dem Hinweis, dass es Montag frueh um sieben normal weitergeht."}
- Kein Wechselgespraech: Sprecher wechseln nur an Themengrenzen. Innerhalb eines Themas spricht eine Stimme am Stueck.
- Deutsch, gesprochene Sprache, kurze Saetze. Der Text wird von einer Sprachsynthese vorgelesen: keine URLs, keine Abkuerzungen, keine Sonderzeichen, keine Klammern, keine Gedankenstriche, Zahlen bis zwoelf als Wort, Spielnamen wie geschrieben.
- Kein Schreib-Slop: keine Kontraste der Art "nicht X, sondern Y"; keine Anlaeufe wie "Was viele nicht wissen", "Das Beste daran"; kein Bedeutungsgetue wie "Meilenstein", "wegweisend", "zeigt einmal mehr"; keine unbenannten Quellen; keine Fazit-Floskeln; keine tiefsinnigen Schlusspointen; keine leeren Adverbien wie "absolut", "wirklich", "spannend". Fakten sagen, Wertung nur mit Begruendung.
{'- Genau eine Zeile mit speaker "J" und Text "news" direkt vor der ersten Gaming-Meldung.' if teil == "heute" else '- Keine Jingles in diesem Abschnitt.'}

Antworte nur mit JSON:
{{"titel": "kurzer Titel des Abschnitts", "zusammenfassung": "drei bis fuenf Saetze fuer die App",
 "lines": [{{"speaker": "A", "text": "..."}}, ...]}}"""


def schreibe_teil(cfg, *args):
    prompt = bau_prompt(cfg, *args)
    for versuch in range(3):
        try:
            data = writer.generate(cfg, {"sonder": True}, prompt)
            lines = data.get("lines") or []
            if len(lines) < 4:
                raise ValueError(f"nur {len(lines)} Zeilen")
            for l in lines:
                if l.get("speaker") not in ("A", "B", "J") or not (l.get("text") or "").strip():
                    raise ValueError(f"kaputte Zeile: {l}")
            return data
        except Exception as e:
            log(f"  Versuch {versuch + 1} fehlgeschlagen: {e}")
    raise RuntimeError("Abschnitt konnte nicht geschrieben werden")


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--thema", required=True)
    p.add_argument("--steam", type=int)
    p.add_argument("--slot", default="21:00")
    p.add_argument("--minuten", type=int, default=20)
    p.add_argument("--feeds", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--date")
    p.add_argument("--teile", default="heute,woche,spiel,spiel2,rotation")
    p.add_argument("--backend")
    p.add_argument("--no-render", action="store_true")
    args = p.parse_args(argv)

    cfg = writer.load_config()
    if args.backend:
        cfg["backend"] = args.backend
    tag = _date.fromisoformat(args.date) if args.date else _date.today()
    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)
    with open(args.feeds, encoding="utf-8") as f:
        items = writer.filtered_items(cfg, json.load(f)["items"])
    woche = writer.filtered_items(cfg, sammle_woche(cfg, tag))
    log(f"{len(items)} Meldungen von heute, {len(woche)} aus dem Archiv")

    quellen = recherche_spiel(cfg, args.thema, args.steam)
    log(f"Recherche: {len(quellen)} Quellen, {sum(len(q['text']) for q in quellen)} Zeichen")

    lines, abschnitte, vorher = [], [], []
    for teil in args.teile.split(","):
        teil = teil.strip()
        if teil not in TEILE:
            sys.exit(f"unbekannter Teil: {teil}")
        t0 = time.time()
        data = schreibe_teil(cfg, teil, teil, tag, args.minuten, quellen, items, woche, args.thema, vorher)
        start = len(lines)
        lines += data["lines"]
        abschnitte.append({"teil": teil, "titel": data.get("titel") or TEILE[teil]["titel"],
                           "zusammenfassung": data.get("zusammenfassung", ""),
                           "line_start": start, "line_end": len(lines) - 1})
        vorher.append(f"{data.get('titel')}: {data.get('zusammenfassung', '')[:200]}")
        log(f"{teil}: {len(data['lines'])} Zeilen, {round(time.time() - t0)}s")

    name = args.slot.replace(":", "")
    script_path = os.path.join(out_dir, f"{name}.txt")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(f"# FoxRadio Sondersendung {tag.isoformat()} {args.slot}: {args.thema}\n")
        for l in lines:
            f.write(f"{l['speaker']}: {l['text'].strip()}\n")
    with open(os.path.join(out_dir, f"{name}.abschnitte.json"), "w", encoding="utf-8") as f:
        json.dump({"slot": args.slot, "thema": args.thema, "date": tag.isoformat(),
                   "lines": len(lines), "abschnitte": abschnitte}, f, ensure_ascii=False, indent=2)
    log(f"Skript: {script_path}, {len(lines)} Zeilen, geschaetzt {len(lines) * 6 / 60:.0f} Minuten")

    if args.no_render:
        return 0
    tcfg = foxtts.load_config()
    foxtts.ensure_running(tcfg)
    summary = foxtts.render_block(tcfg, script_path, os.path.join(out_dir, f"{name}.mp3"))
    log(f"Fertig: {summary['audio_s'] / 60:.1f} Minuten Audio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
