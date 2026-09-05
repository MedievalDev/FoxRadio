#!/usr/bin/env python3
"""
Textgenerierung für die FoxRadio-Blöcke: feste Rubriken, enge Prompts,
zwei Sprecher mit festen Rollen. Aus den Meldungen (feeds.json) und dem
Wetter entsteht pro Sendeplatz ein Dialogskript im foxtts-Format plus
Artikel für die App.

Sendeschema (writer.json, "slots"): Morning Show um 07:00, danach ein
Tagesthema in sieben Teilen bis 10:00 (volle Stunde nach den News, halbe
Stunde nur Thema), dann Stundenblöcke; 08:55 und 11:55 enden vor den
Pausen, 14:00 mit Tipp des Tages, 15:00 Abschluss mit Rezept des Tages.

Tagesthema nach Wochentag ("theme_by_weekday"): Montag Indie-Spiel, Dienstag
Mod-Projekt, Mittwoch Engine-Technik, Donnerstag Spielreihe, Freitag
Kickstarter oder Devlog, Wochenende Wochenzusammenfassung mit Sondersendung
oder Indie-Rotation. Die Quellen dazu (Artikeltext, Steam-Store) holt
research() vorher, damit Claude nichts erfinden muss.

Backends (writer.json, "backend"):
    claude-cli   Claude Code headless: `claude -p` (Standard, nutzt dein Abo)
    api          Anthropic-SDK (pip install anthropic, ANTHROPIC_API_KEY)
    fake         kanned Antworten zum Testen der Pipeline

    python writer.py plan  --feeds work/feeds.json                  Zuteilung und Themenwahl zeigen
    python writer.py write --feeds work/feeds.json --weather work/weather.json --out work/scripts [--only 08:30]
"""

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from datetime import date as _date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "writer.json")
sys.path.insert(0, HERE)
import feeds  # noqa: E402  (fetch, strip_html)

DEFAULTS = {
    "backend": "claude-cli",
    "claude_cli": "claude",
    "claude_cli_model": "opus",
    "api_model": "claude-opus-5",
    "work_dir": os.path.join(HERE, "work"),
    # Sendeplätze. kind: morning | hour | short (endet vor der Pause) | theme (nur Thema) | closing
    # theme_part: Teil des Tagesthemas in diesem Block. extra: tip | recipe
    "slots": [
        {"slot": "07:00", "kind": "morning", "theme_part": 1},
        {"slot": "07:30", "kind": "theme", "theme_part": 2},
        {"slot": "08:00", "kind": "hour", "theme_part": 3},
        {"slot": "08:30", "kind": "theme", "theme_part": 4},
        {"slot": "08:55", "kind": "short", "theme_part": 5},
        {"slot": "09:30", "kind": "theme", "theme_part": 6},
        {"slot": "10:00", "kind": "hour", "theme_part": 7},
        {"slot": "11:00", "kind": "hour"},
        {"slot": "11:55", "kind": "short"},
        {"slot": "13:00", "kind": "hour"},
        {"slot": "14:00", "kind": "hour", "extra": "tip"},
        {"slot": "15:00", "kind": "closing", "extra": "recipe"},
    ],
    # Montag .. Sonntag
    "theme_by_weekday": ["indie", "mod", "engine", "series", "kickstarter", "weekly", "weekly"],
    # Reihen und Studios, die Marco interessieren (Donnerstag und Vorzug in den Gaming-News)
    "series": ["Two Worlds", "Kingdom Come", "Warhorse", "Elden Ring", "Nightreign", "FromSoftware", "Dark Souls",
               "Witcher", "Cyberpunk", "CD Projekt", "Enshrouded", "Sons of the Forest", "The Forest", "Wreckfest",
               "Skyrim", "Skyblivion", "Skywind", "Elder Scrolls", "Gothic", "Reality Pump"],
    # Was nicht ins Programm soll: rundenbasiert, Anime und japanischer Content, Film und Serie
    "avoid": r"rundenbasiert|turn-based|turn based|\bAnime\b|\bJRPG\b|\bJapan|\bManga\b|Pok[eé]mon|Final Fantasy|"
             r"\bPersona\b|Octopath|Dragon Quest|\bZelda\b|Nintendo|Switch 2|\bFilm\b|\bSerie\b|Netflix|\bKino\b|"
             r"\bLego\b|Star Trek|Harry Potter|Marvel|Podcast",
    # Zeilen je Teil. Eine Zeile sind rund acht Sekunden gesprochen.
    "lines": {"morning": [10, 14], "hour": [6, 9], "short": [4, 6], "closing": [4, 6],
              "theme_full": [16, 22], "theme_half": [10, 14], "tip": [5, 8], "recipe": [7, 10]},
    # Feste Rollen je Rubrik. Kein Wechselgespräch: jede Stimme spricht ihre
    # Rubrik am Stück, die andere höchstens mit einer kurzen Übergabe.
    "speaker_a": ("Mann, sachlich, präzise. Begrüßt, nennt Uhrzeit und Datum, macht Spieleentwicklung und KI, "
                  "führt das Tagesthema und den Tipp des Tages. Beendet jeden Block."),
    "speaker_b": ("Frau, mit klarer eigener Meinung, wertet und stichelt auch mal, ohne Floskeln. Macht in der "
                  "Morning Show das Wetter als Drei-Tage-Übersicht, in jedem Block alle Gaming-News am Stück, "
                  "das Rezept des Tages und kurze Kommentare zum Tagesthema."),
    "history_file": os.path.join(HERE, "work", "verlauf.json"),
    "theme_repeat_days": 14,
}

WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember"]

THEME_NAMES = {
    "indie": "Neues Indie-Spiel", "mod": "Mod-Projekt", "engine": "Engine und Technik",
    "series": "Spielreihe", "kickstarter": "Kickstarter und Devlogs", "weekly": "Die Woche",
}
THEME_RULES = {
    "indie": {"rubrics": ["indie"],
              "prefer": r"RPG|Rollenspiel|Survival|Open World|Crafting|Action|Souls|Aufbau|Strategie|Early Access|Demo"},
    "mod": {"rubrics": ["mods", "gaming"],
            "require": r"\bMod\b|\bMods\b|Modding|Skyblivion|Skywind|Beyond Skyrim|Remake|Overhaul|Total Conversion|ModDB|Nexus",
            "prefer": r"Skyblivion|Skywind|Beyond Skyrim|Kingdom Come|Elden Ring|Gothic|Two Worlds|Overhaul"},
    "engine": {"rubrics": ["gamedev"],
               "prefer": r"Unreal|UE5|UE4|Blender|Godot|Nanite|Lumen|Shader|Material|Blueprint|Optimi|Performance|"
                         r"Tool|Workflow|Tutorial|Breakdown|Lighting|Animation"},
    "series": {"rubrics": ["gaming", "mods", "indie"], "require": "SERIES", "prefer": "SERIES"},
    "kickstarter": {"rubrics": ["indie"],
                    "prefer": r"Kickstarter|Devlog|Dev Log|GitHub|Early Access|Demo|Prototyp|Sterne|open-source|Open Source"},
}
THEME_FALLBACK = ["indie", "series", "kickstarter", "engine", "mod"]

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
            eigen = json.load(f)
        if isinstance(eigen.get("lines"), dict):
            eigen["lines"] = {**DEFAULTS["lines"], **eigen["lines"]}
        cfg.update(eigen)
    return cfg


def german_date(d):
    return f"{WEEKDAYS[d.weekday()]}, der {d.day}. {MONTHS[d.month - 1]}"


def spoken_time(slot):
    h, m = slot.split(":")
    h, m = int(h), int(m)
    if m == 0:
        return f"{h} Uhr"
    if m == 30:
        return f"halb {h + 1}"
    return f"{h} Uhr {m}"


def series_regex(cfg):
    return "|".join(re.escape(s) for s in cfg["series"])


# ----------------------------------------------------------------------------
# Verlauf: was schon lief, damit sich Tipps, Rezepte und Themen nicht wiederholen
# ----------------------------------------------------------------------------

def load_history(cfg):
    p = cfg["history_file"]
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {"tips": [], "recipes": [], "themes": []}


def save_history(cfg, hist):
    p = cfg["history_file"]
    os.makedirs(os.path.dirname(p), exist_ok=True)
    hist["tips"] = hist["tips"][-60:]
    hist["recipes"] = hist["recipes"][-60:]
    hist["themes"] = hist["themes"][-60:]
    with open(p, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)


# ----------------------------------------------------------------------------
# Zuteilung der Meldungen auf die Sendeplätze
# ----------------------------------------------------------------------------

def filtered_items(cfg, items):
    """Was nicht ins Programm soll, fliegt vor der Zuteilung raus."""
    avoid = re.compile(cfg["avoid"], re.I)
    return [i for i in items if not avoid.search(i["title"] + " " + (i.get("summary") or "")[:200])]


def plan_blocks(cfg, items, theme=None):
    """Verteilt Meldungen ohne Wiederholung auf die Blöcke mit News. Die
    Morning Show bekommt die meisten, 08:55 und 11:55 wenig (kurz vor der
    Pause), reine Themenblöcke nichts."""
    items = filtered_items(cfg, items)
    used = {theme["item"]["link"]} if theme and theme.get("item") else set()
    prefer = re.compile(series_regex(cfg) + "|RPG|Rollenspiel|Survival|Open World|Mod\\b", re.I)
    pools = {}
    for it in items:
        if it["link"] in used:
            continue
        pools.setdefault(it["rubric"], []).append(it)
    for r in pools:   # Reihen und Rollenspiele zuerst
        pools[r].sort(key=lambda i: 0 if prefer.search(i["title"]) else 1)

    def take(rubric, n):
        got = pools.get(rubric, [])[:n]
        pools[rubric] = pools.get(rubric, [])[n:]
        return got

    def take_any(rubrics, n):
        got = []
        for r in rubrics:
            if len(got) >= n:
                break
            got += take(r, n - len(got))
        return got

    blocks = []
    hour_idx = 0
    for s in cfg["slots"]:
        kind = s["kind"]
        if kind == "morning":
            picked = take("gaming", 3) + take_any(["gamedev", "ki"], 2) + take("ki", 1) + take("indie", 1)
        elif kind == "theme":
            picked = []
        elif kind == "short":
            picked = take("gaming", 1) + take_any(["gamedev", "ki", "indie", "mods"], 1)
        elif kind == "closing":
            picked = take("gaming", 1) + take_any(["indie", "mods"], 1)
        else:
            hour_idx += 1
            picked = take("gaming", 2 if hour_idx % 2 else 1)
            picked += take_any(["gamedev", "ki"] if hour_idx % 2 else ["ki", "gamedev"], 1)
            if hour_idx % 3 == 0:
                picked += take_any(["indie", "mods"], 1)
        blocks.append({**s, "items": picked})
    return blocks


# ----------------------------------------------------------------------------
# Tagesthema: Auswahl, Recherche, Dossier in sieben Teilen
# ----------------------------------------------------------------------------

def theme_category(cfg, day):
    return cfg["theme_by_weekday"][day.weekday()]


def theme_candidates(cfg, items, category, hist, day):
    rule = THEME_RULES[category]
    req = rule.get("require")
    pref = rule.get("prefer")
    sr = series_regex(cfg)
    req_re = re.compile(sr if req == "SERIES" else req, re.I) if req else None
    pref_re = re.compile(sr if pref == "SERIES" else pref, re.I) if pref else None
    recent = {t["link"] for t in hist.get("themes", [])
              if t.get("date") and (day - _date.fromisoformat(t["date"])).days < cfg["theme_repeat_days"]}
    out = []
    for it in filtered_items(cfg, items):
        if it["rubric"] not in rule["rubrics"] or it["link"] in recent:
            continue
        text = it["title"] + " " + (it.get("summary") or "")
        if req_re and not req_re.search(text):
            continue
        score = 0
        if pref_re and pref_re.search(text):
            score += 3
        if it.get("summary"):
            score += 1
        if it.get("image"):
            score += 1
        if it["source"].startswith("Steam "):
            score += 1   # Reihen-Feeds sind Primärquellen
        out.append((score, it))
    out.sort(key=lambda x: x[0], reverse=True)
    return [it for _, it in out]


def pick_theme(cfg, items, day, hist):
    category = theme_category(cfg, day)
    if category == "weekly":
        return {"category": "weekly", "item": None, "sources": []}
    for cat in [category] + [c for c in THEME_FALLBACK if c != category]:
        cands = theme_candidates(cfg, items, cat, hist, day)
        if cands:
            if cat != category:
                log(f"Thema: für {THEME_NAMES[category]} nichts gefunden, nehme {THEME_NAMES[cat]}")
            return {"category": cat, "item": cands[0], "alternatives": cands[1:4], "sources": []}
    return {"category": "weekly", "item": None, "sources": []}


def page_text(url, limit=6000):
    try:
        raw = feeds.fetch(url, timeout=20, max_bytes=1_500_000).decode("utf-8", "replace")
    except Exception:
        return ""
    # Navigation und Fußzeilen grob abschneiden: Hauptteil bevorzugen
    m = re.search(r"<(?:article|main)[^>]*>(.*?)</(?:article|main)>", raw, flags=re.S | re.I)
    body = m.group(1) if m else raw
    return feeds.strip_html(body, limit=limit)


def steam_appid_from_link(link):
    m = re.search(r"store\.steampowered\.com/(?:app|news/app)/(\d+)", link or "")
    return int(m.group(1)) if m else None


def steam_details(appid):
    try:
        d = json.loads(feeds.fetch(f"https://store.steampowered.com/api/appdetails?appids={appid}&l=german&cc=de", timeout=20))
        a = d[str(appid)]["data"]
    except Exception:
        return None
    teile = [
        f"Name: {a.get('name')}",
        f"Entwickler: {', '.join(a.get('developers') or [])}",
        f"Publisher: {', '.join(a.get('publishers') or [])}",
        f"Release: {(a.get('release_date') or {}).get('date')}",
        f"Genres: {', '.join(g['description'] for g in a.get('genres') or [])}",
        f"Preis: {(a.get('price_overview') or {}).get('final_formatted') or 'unbekannt'}",
        f"Kurzbeschreibung: {feeds.strip_html(a.get('short_description') or '', limit=400)}",
        f"Beschreibung: {feeds.strip_html(a.get('detailed_description') or '', limit=2500)}",
    ]
    if a.get("metacritic"):
        teile.append(f"Metacritic: {a['metacritic'].get('score')}")
    return {"name": a.get("name"), "text": "\n".join(teile), "url": f"https://store.steampowered.com/app/{appid}/"}


def steam_search(name):
    try:
        q = urllib.parse.urlencode({"term": name, "cc": "de", "l": "german"})
        d = json.loads(feeds.fetch("https://store.steampowered.com/api/storesearch/?" + q, timeout=20))
    except Exception:
        return None
    for it in d.get("items", [])[:3]:
        if difflib.SequenceMatcher(None, it["name"].lower(), name.lower()).ratio() >= 0.6:
            return it["id"]
    return None


def game_name_from_item(cfg, item):
    """Fragt kurz nach dem Spielnamen, damit der Steam-Store gezielt gesucht werden kann."""
    prompt = (f"Meldung: {item['title']}\n{item.get('summary') or ''}\n\n"
              "Um welches einzelne Spiel oder Mod-Projekt geht es hauptsächlich? Antworte nur mit JSON: "
              '{"name": "Spielname" oder "", "is_game": true oder false}')
    try:
        data = generate(cfg, None, prompt)
        return (data.get("name") or "").strip() if data.get("is_game") else ""
    except Exception as e:
        log(f"Spielname nicht ermittelt: {e}")
        return ""


def research(cfg, theme):
    """Sammelt Quellentexte zum Thema: Artikelseite, Steam-Store, Alternativen."""
    it = theme.get("item")
    if not it:
        return theme
    sources = []
    txt = page_text(it["link"])
    if txt:
        sources.append({"name": f"{it['source']}: {it['title']}", "url": it["link"], "text": txt})
    if theme["category"] in ("indie", "series", "kickstarter", "mod"):
        appid = steam_appid_from_link(it["link"])
        if not appid and cfg["backend"] != "fake":
            name = game_name_from_item(cfg, it)
            if name:
                appid = steam_search(name)
        if appid:
            st = steam_details(appid)
            if st:
                sources.append({"name": f"Steam-Store: {st['name']}", "url": st["url"], "text": st["text"]})
                theme["game"] = st["name"]
    for alt in theme.get("alternatives", [])[:2]:
        sources.append({"name": f"Weitere Meldung ({alt['source']}): {alt['title']}", "url": alt["link"],
                        "text": (alt.get("summary") or "")[:600]})
    theme["sources"] = sources
    log(f"Thema: {THEME_NAMES[theme['category']]}, {len(sources)} Quellen, {sum(len(s['text']) for s in sources)} Zeichen")
    return theme


def week_items(cfg, day):
    """Meldungen der letzten sieben Nächte aus work/<datum>/feeds.json."""
    out, seen = [], set()
    for back in range(1, 8):
        d = day - timedelta(days=back)
        p = os.path.join(cfg["work_dir"], d.isoformat(), "feeds.json")
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            for it in json.load(f).get("items", []):
                key = it["link"].split("?")[0]
                if key not in seen:
                    seen.add(key)
                    it = dict(it)
                    it["day"] = d.isoformat()
                    out.append(it)
    return filtered_items(cfg, out)


def theme_slots(cfg):
    return [s for s in cfg["slots"] if s.get("theme_part")]


def theme_plan_text(cfg):
    lo_f, hi_f = cfg["lines"]["theme_full"]
    lo_h, hi_h = cfg["lines"]["theme_half"]
    zeilen = []
    slots = theme_slots(cfg)
    for i, s in enumerate(slots):
        voll = s["kind"] != "theme"
        naechste = slots[i + 1]["slot"] if i + 1 < len(slots) else None
        zeilen.append(f"Teil {s['theme_part']}: um {spoken_time(s['slot'])}, "
                      + (f"{lo_f} bis {hi_f} Zeilen, kommt nach den News" if voll else f"{lo_h} bis {hi_h} Zeilen, eigener kurzer Block")
                      + (f", endet mit Hinweis auf Teil {s['theme_part'] + 1} um {spoken_time(naechste)}" if naechste
                         else ", ist der Abschluss des Themas"))
    return "\n".join(zeilen)


def build_theme_prompt(cfg, theme, day, week=None):
    cat = theme["category"]
    n_parts = len(theme_slots(cfg))
    if cat == "weekly":
        week = week or []
        by_r = {}
        for it in week:
            by_r.setdefault(it["rubric"], []).append(it)
        liste = []
        for r, lst in by_r.items():
            liste.append(f"[{r}]")
            for it in lst[:25]:
                liste.append(f"- ({it.get('day', '')}, {it['source']}) {it['title']} | {(it.get('summary') or '')[:160]}")
        quellen = "\n".join(liste) or "- (keine Meldungen der Woche gefunden)"
        auftrag = ("Es ist Wochenende. Mach aus den Meldungen der Woche eine Wochenzusammenfassung. Gab es ein großes "
                   "Ereignis (Messe wie Gamescom, ein Showcase, ein Studio-Event, ein großer Release), wird daraus eine "
                   "Sondersendung mit diesem Ereignis im Mittelpunkt. Gab es nichts dergleichen, wird es eine "
                   "Indie-Rotation: zehn kleine Spiele aus den Indie-Meldungen der Woche, jedes kurz vorgestellt wie in "
                   "einem Sammelartikel, über die Teile verteilt.")
    else:
        quellen = "\n\n".join(f"### {s['name']}\n{s['url']}\n{s['text']}" for s in theme["sources"]) or "(keine Quellen)"
        it = theme["item"]
        auftrag = (f"Tagesthema der Kategorie {THEME_NAMES[cat]}: {it['title']}\n"
                   f"Quelle: {it['source']}, {it['link']}\n"
                   + (f"Spiel laut Steam: {theme['game']}\n" if theme.get("game") else "")
                   + "Stell dieses Thema in Teilen vor, jeder Teil hat einen eigenen Schwerpunkt, zum Beispiel: "
                     "worum es geht; Welt und Geschichte; Spielsysteme und Mechaniken; Technik, Studio, Entstehung; "
                     "Stand, Preis, Plattformen, Community; Vergleich mit bekannten Spielen und für wen es taugt; "
                     "Fazit und Ausblick. Passe die Schwerpunkte an das an, was die Quellen hergeben.")
    return f"""Du schreibst das Tagesthema für FoxRadio, ein persönliches Radioprogramm für einen einzigen Hörer (Zerspanungsmechaniker in der Montage, entwickelt nebenbei ein Rollenspiel mit Unreal Engine 4.27; mag Two Worlds, Kingdom Come, Elden Ring, Skyblivion, Survival-Spiele; mag keine rundenbasierten Spiele, kein Anime, keinen japanischen Content). Der Hörer wird nicht mit Namen angesprochen.
Zwei Sprecher:
A: {cfg['speaker_a']} A führt das Tagesthema.
B: {cfg['speaker_b']} B bringt je Teil ein bis drei Zeilen Meinung oder Nachfrage, nicht mehr.

Datum: {german_date(day)}.

{auftrag}

Quellen (nur diese Fakten verwenden, nichts dazuerfinden, keine Zahlen raten; reichen die Quellen für einen Teil nicht, wird der Teil kürzer, nie erfunden):
{quellen}

Das Thema läuft in {n_parts} Teilen über den Vormittag:
{theme_plan_text(cfg)}

Regeln:
- Jeder Teil beginnt mit einer Zeile von A, die Teil und Thema nennt (bei Teil 1 als Einstieg ins Thema, danach als Wiedereinstieg für Hörer, die gerade dazukommen, ein Satz), und endet mit dem Hinweis auf den nächsten Teil und seine Uhrzeit, beim letzten Teil mit einem Fazit ohne Pathos.
- Deutsch, gesprochene Sprache, kurze Sätze. Der Text wird von einer Sprachsynthese vorgelesen: keine URLs, keine Abkürzungen, keine Sonderzeichen, keine Klammern, keine Gedankenstriche, Zahlen bis zwölf als Wort, Spielnamen wie geschrieben.
- Kein Schreib-Slop: keine Kontraste der Art "nicht X, sondern Y"; keine Anläufe wie "Was viele nicht wissen", "Das Beste daran"; kein Bedeutungsgetue wie "Meilenstein", "wegweisend", "zeigt einmal mehr"; keine unbenannten Quellen; keine tiefsinnigen Schlusspointen; keine leeren Adverbien wie "absolut", "wirklich", "spannend". Fakten sagen, Wertung nur mit Begründung.
- Keine Wiederholung derselben Fakten in mehreren Teilen, außer dem einen Wiedereinstiegssatz.

Antworte nur mit JSON in dieser Form:
{{"title": "Titel des Themas für die App", "teaser": "ein Satz", "summary": "vier bis acht Sätze Zusammenfassung des ganzen Themas, nur aus den Quellen",
 "parts": [{{"n": 1, "title": "Schwerpunkt des Teils", "summary": "zwei bis vier Sätze", "lines": [{{"speaker": "A", "text": "..."}}, ...]}}, ... genau {n_parts} Teile]}}"""


def validate_theme(cfg, data):
    parts = data.get("parts") or []
    n = len(theme_slots(cfg))
    if len(parts) < n:
        raise ValueError(f"nur {len(parts)} Teile statt {n}")
    for p in parts[:n]:
        lines = p.get("lines") or []
        if len(lines) < 3:
            raise ValueError(f"Teil {p.get('n')} hat nur {len(lines)} Zeilen")
        for l in lines:
            if l.get("speaker") not in ("A", "B") or not (l.get("text") or "").strip():
                raise ValueError(f"kaputte Zeile in Teil {p.get('n')}: {l}")
    data["parts"] = parts[:n]
    for i, p in enumerate(data["parts"], 1):
        p["n"] = i
    if not data.get("title"):
        raise ValueError("Thema ohne Titel")
    return data


def build_theme(cfg, items, day, out_dir):
    """Wählt das Tagesthema, recherchiert und schreibt das Dossier. Liegt
    für den Tag schon eines in out_dir/thema.json, wird es wiederverwendet."""
    cache = os.path.join(out_dir, "thema.json")
    if os.path.exists(cache):
        with open(cache, encoding="utf-8") as f:
            theme = json.load(f)
        log(f"Thema aus {cache}: {theme.get('title')}")
        return theme
    hist = load_history(cfg)
    theme = pick_theme(cfg, items, day, hist)
    week = week_items(cfg, day) if theme["category"] == "weekly" else None
    if theme["category"] != "weekly":
        # Rundenbasiert, Anime und Co. stehen oft erst im Steam-Text: nach der
        # Recherche pruefen und notfalls die naechste Meldung nehmen.
        avoid = re.compile(cfg["avoid"], re.I)
        kandidaten = [theme["item"]] + list(theme.get("alternatives", []))
        for k, it in enumerate(kandidaten):
            theme["item"] = it
            theme["alternatives"] = [a for a in kandidaten if a is not it][:3]
            theme = research(cfg, theme)
            treffer = [m.group(0) for src in theme["sources"][:2] for m in [avoid.search(src["text"])] if m]
            if not treffer:
                break
            log(f"Thema verworfen ({', '.join(treffer)}): {it['title'][:60]}")
            theme.pop("game", None)
        else:
            log("Thema: alle Kandidaten fallen unter die Ausschlussliste, Wochenrueckblick stattdessen")
            theme = {"category": "weekly", "item": None, "sources": []}
            week = week_items(cfg, day)
    prompt = build_theme_prompt(cfg, theme, day, week)
    t0 = time.time()
    data = None
    for versuch in range(3):
        try:
            data = validate_theme(cfg, generate(cfg, {"theme": theme}, prompt))
            break
        except Exception as e:
            log(f"Thema, Versuch {versuch + 1}: {e}")
    if data is None:
        raise RuntimeError("Tagesthema konnte nicht geschrieben werden")
    theme.update({k: data[k] for k in ("title", "teaser", "summary", "parts")})
    theme["seconds"] = round(time.time() - t0, 1)
    theme["date"] = day.isoformat()
    os.makedirs(out_dir, exist_ok=True)
    with open(cache, "w", encoding="utf-8") as f:
        json.dump(theme, f, ensure_ascii=False, indent=2)
    if theme.get("item"):
        hist["themes"].append({"date": day.isoformat(), "title": theme["title"], "link": theme["item"]["link"]})
        save_history(cfg, hist)
    log(f"Thema: {theme['title']} ({THEME_NAMES[theme['category']]}), {len(theme['parts'])} Teile, "
        f"{sum(len(p['lines']) for p in theme['parts'])} Zeilen, {theme['seconds']}s")
    return theme


# ----------------------------------------------------------------------------
# Prompt für die News-Blöcke
# ----------------------------------------------------------------------------

def next_slot_after(cfg, slot):
    slots = [s["slot"] for s in cfg["slots"]]
    i = slots.index(slot) if slot in slots else -1
    return slots[i + 1] if 0 <= i < len(slots) - 1 else None


def build_prompt(cfg, block, weather, day, theme=None, hist=None):
    kind = block["kind"]
    lo, hi = cfg["lines"][kind]
    hist = hist or {"tips": [], "recipes": []}
    w = ""
    if weather and weather.get("days") and kind == "morning":
        w = "Wetter " + weather["place"] + " für die Übersicht: " + " ".join(
            f"{t['name'].capitalize()} ({t['weekday']}): {t['tmin']} bis {t['tmax']} Grad, {t['tendenz']}, {t['text']}."
            for t in weather["days"][:3])
    news = "\n".join(
        f"- [{it['id']}] ({it['rubric']}, {it['source']}) {it['title']}\n  {it.get('summary') or ''}".rstrip()
        for it in block["items"]
    ) or "- (keine Meldungen für diesen Block)"

    part = block.get("theme_part")
    thema = ""
    if theme and part:
        thema = (f"Nach den News folgt Teil {part} des Tagesthemas \"{theme['title']}\" (schon geschrieben, nicht "
                 f"vorwegnehmen). Die letzte Zeile dieses Blocks ist eine kurze Übergabe von A zum Tagesthema, "
                 f"kein Hinweis auf den nächsten Block.")
    naechster = next_slot_after(cfg, block["slot"])
    abschluss = (f"Die letzte Zeile nennt den nächsten Block um {spoken_time(naechster)}." if naechster and not thema
                 else ("Die letzte Zeile ist die Verabschiedung bis morgen früh um sieben." if not naechster and not thema else ""))

    extra = ""
    if block.get("extra") == "tip":
        lo_t, hi_t = cfg["lines"]["tip"]
        extra = (f"\nZusätzlich nach den Meldungen: Tipp des Tages für Indie-Entwickler, gesprochen von A, {lo_t} bis {hi_t} Zeilen. "
                 "Abwechselnd konkret für Unreal Engine 4.27 (Blueprint, Materialien, Performance, Packaging, Lighting, "
                 "Landscape, Animation) oder allgemein Indie-Dev (Scope, Playtests, Steam-Seite, Marketing, Motivation). "
                 "Ein Tipp, den man am selben Abend umsetzen kann, mit dem Warum. Keine Wiederholung dieser schon "
                 "gesendeten Tipps: " + (", ".join(hist["tips"][-30:]) or "keine") + ".\n"
                 'Dazu im JSON: "tip": {"title": "kurzer Titel", "body": "der Tipp als Fließtext für die App, drei bis '
                 'sechs Sätze", "line_start": Index, "line_end": Index}')
    elif block.get("extra") == "recipe":
        lo_r, hi_r = cfg["lines"]["recipe"]
        extra = (f"\nZusätzlich vor der Verabschiedung: Rezept des Tages, gesprochen von B, {lo_r} bis {hi_r} Zeilen. "
                 "Abwechselnd ein schnelles Abendessen nach der Schicht (20 bis 30 Minuten, Alltagszutaten) oder ein "
                 "mittelalterlich oder alchemistisch angehauchtes Gericht (Eintopf, Brot, Kräuter, Met, Pasteten, "
                 "was ein Alchemist kochen würde, mit einem Satz Herkunft). Name, Zutaten für zwei Personen, die "
                 "Schritte in Reihenfolge, gesprochen so, dass man mitkochen kann. Keine Wiederholung dieser schon "
                 "gesendeten Rezepte: " + (", ".join(hist["recipes"][-30:]) or "keine") + ".\n"
                 'Dazu im JSON: "recipe": {"title": "Name des Gerichts", "ingredients": ["..."], "steps": ["..."], '
                 '"body": "Kurzbeschreibung, zwei Sätze", "line_start": Index, "line_end": Index}')

    if kind == "morning":
        struktur = ("1. A: Begrüßung, Datum, Uhrzeit, kurz was heute ansteht (auch das Tagesthema nennen), Übergabe an B (2 bis 3 Zeilen)\n"
                    "2. B: Wetter als Drei-Tage-Übersicht in zwei bis drei Zeilen, Muster: heute zwölf bis 25 Grad, "
                    "überwiegend trocken, morgen sonnig, 16 bis 22 Grad, übermorgen Regen (nur wenn Wetterdaten da sind)\n"
                    "3. B: alle Gaming-News am Stück, die größte Meldung zuerst und etwas ausführlicher (je Meldung 2 bis 4 Zeilen), "
                    "am Ende Übergabe zurück an A\n"
                    "4. A: Spieleentwicklung und KI (je 2 bis 3 Zeilen), dann die Indie-Meldung, falls da\n"
                    "5. A: Übergabe zum Tagesthema")
    elif kind == "closing":
        struktur = ("1. A: Uhrzeit, kurzer Tagesabschluss (1 bis 2 Zeilen)\n"
                    "2. Gaming-Meldung durch B, alles andere durch A (je 2 bis 3 Zeilen)\n"
                    "3. B: Rezept des Tages\n"
                    "4. A: Verabschiedung bis morgen früh (1 Zeile)")
    elif kind == "short":
        struktur = ("1. A: Uhrzeit, Hinweis, dass es kurz vor der Pause nur kurz wird (1 Zeile)\n"
                    "2. B: die Gaming-Meldung (2 Zeilen), falls dabei\n"
                    "3. A: die andere Meldung (2 Zeilen)\n"
                    "4. A: " + ("Übergabe zum Tagesthema" if thema else "kurzer Abschluss mit dem nächsten Block"))
    else:
        struktur = ("1. A: Uhrzeit, was in diesem Block kommt (1 Zeile)\n"
                    "2. B: die Gaming-Meldungen am Stück (je 2 bis 4 Zeilen), falls welche dabei sind\n"
                    "3. A: Spieleentwicklung, KI, Indie oder Mods (je 2 bis 4 Zeilen)\n"
                    + ("4. A: Tipp des Tages\n5. A: kurzer Abschluss mit dem nächsten Block" if block.get("extra") == "tip"
                       else "4. A: " + ("Übergabe zum Tagesthema" if thema else "kurzer Abschluss mit dem nächsten Block")))

    return f"""Du schreibst ein kurzes Radioskript für FoxRadio, ein persönliches Programm für einen einzigen Hörer (Zerspanungsmechaniker, meist in der Montage in einer Halle in Ellwangen, entwickelt nebenbei ein Rollenspiel mit Unreal Engine 4.27; mag Two Worlds, Kingdom Come, Elden Ring, Skyblivion, Survival-Spiele; mag keine rundenbasierten Spiele, kein Anime, keinen japanischen Content). Der Hörer wird nicht mit Namen angesprochen.
Zwei Sprecher:
A: {cfg['speaker_a']}
B: {cfg['speaker_b']}

Datum: {german_date(day)}. Sendeplatz: {spoken_time(block['slot'])}. {w}
{thema}
{abschluss}

Meldungen (nur diese Fakten verwenden, nichts dazuerfinden, keine Zahlen raten):
{news}

Struktur, genau in dieser Reihenfolge:
{struktur}
{extra}

Regeln:
- {lo} bis {hi} Zeilen für die News (Tipp und Rezept kommen dazu). A beginnt und beendet.
- Kein Wechselgespräch: Sprecher wechseln nur an Rubrikgrenzen. Innerhalb einer Rubrik spricht die zuständige Stimme alle Zeilen am Stück. Beim Rubrikwechsel höchstens eine kurze Übergabe (ein Satz), keine Rückfragen, kein Hin und Her.
- Genau ein Jingle je Block: eine einzige Zeile mit speaker "J" und Text "news", direkt vor der ersten Gaming-Meldung. In der Morning Show steht sie damit zwischen dem Wetter und den News. Sonst keine Jingles. Die Zeile zählt bei line_start und line_end mit.
- Deutsch, gesprochene Sprache, kurze Sätze. Der Text wird von einer Sprachsynthese vorgelesen: keine URLs, keine Abkürzungen, keine Sonderzeichen, keine Klammern, keine Gedankenstriche, Zahlen bis zwölf als Wort.
- Wenn eine Meldung unklar ist, lieber weglassen als raten. Nur genannte Fakten, keine Zahlen erfinden.
- Kein Schreib-Slop: keine Kontraste der Art "nicht X, sondern Y"; keine Anläufe wie "Was viele nicht wissen", "Das Beste daran", "Ganz ehrlich"; kein Bedeutungsgetue wie "Meilenstein", "unterstreicht", "wegweisend", "zeigt einmal mehr"; keine unbenannten Quellen wie "Experten sind sich einig"; keine Fazit-Sätze am Ende ("Alles in allem", "Man darf gespannt sein"); keine tiefsinnigen Schlusspointen; kein Rotieren von Begriffen für dasselbe Ding; keine leeren Adverbien wie "absolut", "wirklich", "tatsächlich", "spannend". Fakten sagen, Wertung nur mit Begründung.

Antworte nur mit JSON in dieser Form:
{{"lines": [{{"speaker": "A", "text": "..."}}, {{"speaker": "J", "text": "news"}}, ...],
 "articles": [{{"item_id": "n01", "title": "Titel für die App", "teaser": "ein Satz", "body": "drei bis sechs Sätze Zusammenfassung, nur aus den gegebenen Fakten", "line_start": 5, "line_end": 8}}, ...]{', "tip": {...}' if block.get('extra') == 'tip' else ''}{', "recipe": {...}' if block.get('extra') == 'recipe' else ''}}}
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
                         timeout=900, shell=(os.name == "nt"))
    if res.returncode != 0:
        raise RuntimeError(f"claude -p Exit {res.returncode}: {(res.stderr or res.stdout)[:500]}")
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
    ) as stream:
        response = stream.get_final_message()
    if response.stop_reason == "refusal":
        raise RuntimeError("API hat abgelehnt")
    text = next(b.text for b in response.content if b.type == "text")
    return extract_json(text)


def call_fake(cfg, block, prompt):
    if block and block.get("theme"):
        n = len(theme_slots(cfg))
        parts = []
        for i in range(1, n + 1):
            parts.append({"n": i, "title": f"Teil {i}", "summary": f"Zusammenfassung Teil {i}.",
                          "lines": [{"speaker": "A", "text": f"Teil {i} des Tagesthemas."},
                                    {"speaker": "A", "text": "Hier steht der Inhalt aus den Quellen."},
                                    {"speaker": "B", "text": "Klingt brauchbar."},
                                    {"speaker": "A", "text": "Weiter im nächsten Teil." if i < n else "Das war das Thema."}]})
        return {"title": "Testthema", "teaser": "Ein Testthema.", "summary": "Zusammenfassung des Testthemas.", "parts": parts}
    if block is None:
        return {"name": "", "is_game": False}
    lines = [{"speaker": "A", "text": f"Es ist {spoken_time(block['slot'])}, hier ist FoxRadio."},
             {"speaker": "J", "text": "news"}]   # genau einer je Block
    articles = []
    for it in block["items"]:
        start = len(lines)
        sp = "B" if it["rubric"] == "gaming" else "A"
        lines.append({"speaker": sp, "text": f"{it['title']}."})
        lines.append({"speaker": sp, "text": "Das schauen wir uns an."})
        articles.append({"item_id": it["id"], "title": it["title"], "teaser": it["title"],
                         "body": it.get("summary") or it["title"], "line_start": start, "line_end": len(lines) - 1})
    out = {"lines": lines, "articles": articles}
    if block.get("extra") == "tip":
        s = len(lines)
        lines += [{"speaker": "A", "text": "Tipp des Tages: Packaging vor dem Feierabend starten."},
                  {"speaker": "A", "text": "Dann läuft der Build, während du isst."}]
        out["tip"] = {"title": "Packaging abends starten", "body": "Build laufen lassen.", "line_start": s, "line_end": len(lines) - 1}
    if block.get("extra") == "recipe":
        s = len(lines)
        lines += [{"speaker": "B", "text": "Rezept des Tages: Linseneintopf."},
                  {"speaker": "B", "text": "Linsen, Karotten, Zwiebel, Brühe, dreißig Minuten."}]
        out["recipe"] = {"title": "Linseneintopf", "ingredients": ["Linsen", "Karotten"], "steps": ["Kochen."],
                         "body": "Ein Eintopf.", "line_start": s, "line_end": len(lines) - 1}
    lines.append({"speaker": "A", "text": "Bis zum nächsten Block."})
    return out


def generate(cfg, block, prompt):
    b = cfg["backend"]
    if b == "claude-cli":
        return call_claude_cli(cfg, prompt)
    if b == "api":
        return call_api(cfg, prompt)
    if b == "fake":
        return call_fake(cfg, block, prompt)
    raise ValueError(f"unbekanntes Backend {b}")


# Nur ein Jingle im Programm, und der laeuft einmal je Block vor den News.
JINGLES = ("news",)


def validate(data, block):
    lines = data.get("lines") or []
    if len(lines) < 2:
        raise ValueError("zu wenig Zeilen")
    gesehen = 0
    behalten = []
    for l in lines:
        if l.get("speaker") == "J":
            l["text"] = (l.get("text") or "").strip().lower()
            # Unbekannte Marker und jeder weitere fliegen raus statt den Block zu
            # kippen. Gezaehlt wird nur, was auch bleibt.
            if l["text"] not in JINGLES or gesehen >= 1:
                continue
            gesehen += 1
            behalten.append(l)
            continue
        if l.get("speaker") not in ("A", "B") or not (l.get("text") or "").strip():
            raise ValueError(f"kaputte Zeile: {l}")
        behalten.append(l)
    data["lines"] = lines = behalten

    def clamp(a):
        s, e = int(a.get("line_start", 0)), int(a.get("line_end", 0))
        s = max(0, min(s, len(lines) - 1))
        e = max(s, min(e, len(lines) - 1))
        a["line_start"], a["line_end"] = s, e

    ids = {it["id"] for it in block["items"]}
    arts = []
    for a in data.get("articles") or []:
        if a.get("item_id") not in ids:
            continue
        clamp(a)
        arts.append(a)
    data["articles"] = arts
    for key in ("tip", "recipe"):
        if block.get("extra") == key:
            if not isinstance(data.get(key), dict) or not data[key].get("title"):
                raise ValueError(f"{key} fehlt in der Antwort")
            clamp(data[key])
    return data


# ----------------------------------------------------------------------------
# Schreiben
# ----------------------------------------------------------------------------

def write_block(cfg, block, weather, day, out_dir, theme=None):
    t0 = time.time()
    hist = load_history(cfg)
    name = block["slot"].replace(":", "")
    os.makedirs(out_dir, exist_ok=True)
    part = None
    if theme and block.get("theme_part"):
        part = next((p for p in theme["parts"] if p["n"] == block["theme_part"]), None)

    lines, articles = [], []
    if block["kind"] == "theme":
        if not part:
            raise ValueError(f"kein Themen-Teil {block.get('theme_part')} vorhanden")
        data = {"lines": [], "articles": []}
    else:
        prompt = build_prompt(cfg, block, weather, day, theme if part else None, hist)
        data = validate(generate(cfg, block, prompt), block)
        lines = list(data["lines"])
        by_id = {it["id"]: it for it in block["items"]}
        for a in data["articles"]:
            it = by_id[a["item_id"]]
            articles.append({
                "id": f"{name}-{a['item_id']}", "slot": block["slot"], "rubric": it["rubric"],
                "title": a["title"], "teaser": a["teaser"], "body": a["body"],
                "source_name": it["source"], "source_url": it["link"], "image_url": it.get("image"),
                "line_start": a["line_start"], "line_end": a["line_end"],
            })
        if data.get("tip"):
            t = data["tip"]
            articles.append({"id": f"{name}-tipp", "slot": block["slot"], "rubric": "tipp", "title": t["title"],
                             "teaser": "Tipp des Tages für Indie-Entwickler", "body": t["body"],
                             "source_name": "FoxRadio", "source_url": "", "image_url": None,
                             "line_start": t["line_start"], "line_end": t["line_end"]})
            hist["tips"].append(t["title"])
        if data.get("recipe"):
            r = data["recipe"]
            body = (r.get("body") or "") + "\n\nZutaten für zwei:\n" + "\n".join(f"- {z}" for z in r.get("ingredients") or []) \
                   + "\n\nSo geht es:\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(r.get("steps") or [], 1))
            articles.append({"id": f"{name}-rezept", "slot": block["slot"], "rubric": "rezept", "title": r["title"],
                             "teaser": "Rezept des Tages", "body": body.strip(),
                             "source_name": "FoxRadio", "source_url": "", "image_url": None,
                             "line_start": r["line_start"], "line_end": r["line_end"]})
            hist["recipes"].append(r["title"])

    if part:
        start = len(lines)
        lines += part["lines"]
        it = theme.get("item") or {}
        articles.append({
            "id": f"{name}-thema", "slot": block["slot"], "rubric": "thema",
            "title": f"{theme['title']}, Teil {part['n']}: {part.get('title') or ''}".rstrip(": "),
            "teaser": theme.get("teaser") or "", "body": part.get("summary") or theme.get("summary") or "",
            "source_name": it.get("source") or "FoxRadio", "source_url": it.get("link") or "",
            "image_url": it.get("image"), "line_start": start, "line_end": len(lines) - 1,
        })

    script_path = os.path.join(out_dir, f"{name}.txt")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(f"# FoxRadio {day.isoformat()} {block['slot']} ({block['kind']}"
                + (f", Thema Teil {part['n']}" if part else "") + ")\n")
        for l in lines:
            f.write(f"{l['speaker']}: {l['text'].strip()}\n")
    meta = {"slot": block["slot"], "kind": block["kind"], "script": os.path.basename(script_path),
            "lines": len(lines), "articles": articles, "seconds": round(time.time() - t0, 1),
            "theme_part": part["n"] if part else None,
            "title": (f"{theme['title']}, Teil {part['n']}" if part and block["kind"] == "theme"
                      else f"{spoken_time(block['slot'])}: " + {"morning": "Morning Show", "closing": "Tagesabschluss",
                                                                  "short": "Kurz vor der Pause"}.get(block["kind"], "News"))}
    with open(os.path.join(out_dir, f"{name}.articles.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    save_history(cfg, hist)
    log(f"{block['slot']}: {len(lines)} Zeilen, {len(articles)} Artikel, {meta['seconds']}s")
    return meta


def main(argv=None):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("plan")
    sp.add_argument("--feeds", required=True)
    sp.add_argument("--date")
    sw = sub.add_parser("write")
    sw.add_argument("--feeds", required=True)
    sw.add_argument("--weather")
    sw.add_argument("--out", required=True)
    sw.add_argument("--date")
    sw.add_argument("--only", help="nur diesen Slot, z. B. 08:30")
    sw.add_argument("--backend")
    sw.add_argument("--no-theme", action="store_true", help="ohne Tagesthema")
    args = p.parse_args(argv)
    cfg = load_config()
    if getattr(args, "backend", None):
        cfg["backend"] = args.backend
    with open(args.feeds, encoding="utf-8") as f:
        items = json.load(f)["items"]
    day = _date.fromisoformat(args.date) if args.date else _date.today()
    if args.cmd == "plan":
        hist = load_history(cfg)
        theme = pick_theme(cfg, items, day, hist)
        it = theme.get("item")
        print(f"Thema ({THEME_NAMES[theme['category']]}): " + (f"{it['title']} [{it['source']}]" if it else "Wochenrückblick"))
        for alt in theme.get("alternatives", []):
            print(f"   alternativ: {alt['title']} [{alt['source']}]")
        for b in plan_blocks(cfg, items, theme):
            print(f"{b['slot']} {b['kind']:8s} " + (f"Thema {b['theme_part']} " if b.get('theme_part') else "")
                  + (f"{b['extra']} " if b.get('extra') else "")
                  + ", ".join(f"{it['id']}:{it['rubric']}" for it in b["items"]))
        return 0
    weather = None
    if args.weather and os.path.exists(args.weather):
        with open(args.weather, encoding="utf-8") as f:
            weather = json.load(f)
    theme = None if args.no_theme else build_theme(cfg, items, day, args.out)
    blocks = plan_blocks(cfg, items, theme)
    failed = 0
    for b in blocks:
        if args.only and b["slot"] != args.only:
            continue
        try:
            write_block(cfg, b, weather, day, args.out, theme)
        except Exception as e:
            failed += 1
            log(f"FEHLER {b['slot']}: {type(e).__name__}: {e}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
