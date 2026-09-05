#!/usr/bin/env python3
"""
Feeds und Wetter für den FoxRadio-Nachtlauf. Nur Standardbibliothek.

    python feeds.py check                 alle Quellen abrufen, Anzahl und Fehler zeigen
    python feeds.py fetch -o work/feeds.json   Meldungen seit gestern einsammeln
    python feeds.py weather               Wetter für Ellwangen (Open-Meteo, ohne Key)

Grundsatz aus dem Plan: feste Quellen, kein freies Suchen. Was hier nicht
reinkommt, wird auch nicht gesendet.
"""

import argparse
import email.utils
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "feeds.json")
UA = "Mozilla/5.0 (FoxRadio Nachtlauf; +https://alchemy-fox.de)"

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "media": "http://search.yahoo.com/mrss/",
    "dc": "http://purl.org/dc/elements/1.1/",
}


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def load_config(path=CONFIG_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def fetch(url, timeout=25, max_bytes=3_000_000):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(max_bytes)


# ----------------------------------------------------------------------------
# Feed-Parser (RSS 2.0 und Atom)
# ----------------------------------------------------------------------------

def strip_html(s, limit=700):
    if not s:
        return ""
    s = re.sub(r"<script.*?</script>|<style.*?</style>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > limit:
        s = s[:limit].rsplit(" ", 1)[0] + " …"
    return s


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        return email.utils.parsedate_to_datetime(s)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _text(el, *paths):
    for p in paths:
        found = el.find(p, NS)
        if found is not None and (found.text or "").strip():
            return found.text.strip()
    return ""


def _first_image(el):
    for p in ("media:thumbnail", "media:content"):
        for m in el.findall(p, NS):
            url = m.get("url")
            if url and (m.get("medium") in (None, "image")) and not url.endswith(".mp4"):
                return url
    enc = el.find("enclosure")
    if enc is not None and (enc.get("type") or "").startswith("image/"):
        return enc.get("url")
    for p in ("description", "content:encoded", "atom:content", "atom:summary"):
        f = el.find(p, NS)
        if f is not None and f.text:
            m = re.search(r'<img[^>]+src="([^"]+)"', f.text)
            if m:
                return m.group(1)
    return None


def parse_feed(data, source):
    root = ET.fromstring(data)
    items = []
    tag = root.tag.lower()
    if tag.endswith("feed"):  # Atom
        for e in root.findall("atom:entry", NS):
            link = ""
            for l in e.findall("atom:link", NS):
                if l.get("rel") in (None, "alternate"):
                    link = l.get("href", "")
                    break
            items.append({
                "title": html.unescape(_text(e, "atom:title")),
                "link": link,
                "summary": strip_html(_text(e, "atom:summary", "atom:content")),
                "published": parse_date(_text(e, "atom:published", "atom:updated")),
                "image": _first_image(e),
            })
    else:  # RSS 2.0 / RDF
        channel = root.find("channel")
        entries = channel.findall("item") if channel is not None else root.findall("item")
        for e in entries:
            items.append({
                "title": html.unescape(_text(e, "title")),
                "link": _text(e, "link") or (e.find("guid").text.strip() if e.find("guid") is not None and e.find("guid").text else ""),
                "summary": strip_html(_text(e, "description", "content:encoded")),
                "published": parse_date(_text(e, "pubDate", "dc:date")),
                "image": _first_image(e),
            })
    for it in items:
        it["source"] = source["name"]
        it["rubric"] = source["rubric"]
    return [it for it in items if it["title"] and it["link"]]


# ----------------------------------------------------------------------------
# anthropic.com/news (server-gerendert, keine RSS). Best effort, ungeprüft.
# ----------------------------------------------------------------------------

def parse_anthropic_news(data, source):
    text = data.decode("utf-8", "replace")
    items, seen = [], set()
    for m in re.finditer(r'<a[^>]+href="(/news/[^"#?]+)"[^>]*>(.*?)</a>', text, flags=re.S | re.I):
        path, inner = m.group(1), strip_html(m.group(2), limit=300)
        if path in seen or not inner:
            continue
        seen.add(path)
        date = None
        dm = re.search(r"([A-Z][a-z]{2,8} \d{1,2}, \d{4})", inner)
        if dm:
            for fmt in ("%b %d, %Y", "%B %d, %Y"):
                try:
                    date = datetime.strptime(dm.group(1), fmt).replace(tzinfo=timezone.utc)
                    break
                except ValueError:
                    pass
            inner = inner.replace(dm.group(1), "").strip(" ·-")
        items.append({
            "title": inner[:200],
            "link": "https://www.anthropic.com" + path,
            "summary": "",
            "published": date,
            "image": None,
            "source": source["name"],
            "rubric": source["rubric"],
        })
    return items


# ----------------------------------------------------------------------------
# Artikelbild (og:image) und Einsammeln
# ----------------------------------------------------------------------------

def og_image(url):
    try:
        page = fetch(url, timeout=15, max_bytes=400_000).decode("utf-8", "replace")
    except Exception:
        return None
    for pat in (r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"',
                r'<meta[^>]+content="([^"]+)"[^>]+property="og:image"',
                r'<meta[^>]+name="twitter:image"[^>]+content="([^"]+)"'):
        m = re.search(pat, page, flags=re.I)
        if m:
            return html.unescape(m.group(1))
    return None


def collect(cfg, since=None, with_images=True):
    since = since or datetime.now(timezone.utc) - timedelta(hours=cfg.get("since_hours", 26))
    out, errors, seen = [], [], set()
    for src in cfg["sources"]:
        try:
            data = fetch(src["url"])
            items = parse_anthropic_news(data, src) if src.get("type") == "anthropic" else parse_feed(data, src)
        except Exception as e:
            errors.append(f"{src['name']}: {type(e).__name__}: {e}")
            log(f"FEHLER {src['name']}: {e}")
            continue
        fresh = [i for i in items if i["published"] is None or i["published"] >= since]
        log(f"{src['name']}: {len(items)} Einträge, {len(fresh)} neu")
        for it in fresh:
            key = it["link"].split("?")[0].rstrip("/")
            if key in seen:
                continue
            seen.add(key)
            out.append(it)
    # pro Rubrik begrenzen, neueste zuerst
    per = cfg.get("max_per_rubric", 10)
    by_rubric = {}
    for it in sorted(out, key=lambda i: i["published"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True):
        by_rubric.setdefault(it["rubric"], [])
        if len(by_rubric[it["rubric"]]) < per:
            by_rubric[it["rubric"]].append(it)
    result = [it for lst in by_rubric.values() for it in lst]
    if with_images:
        for it in result:
            if not it.get("image"):
                it["image"] = og_image(it["link"])
    for n, it in enumerate(result, 1):
        it["id"] = f"n{n:02d}"
        it["published"] = it["published"].isoformat() if it["published"] else None
    return {"fetched_at": datetime.now(timezone.utc).isoformat(), "since": since.isoformat(),
            "errors": errors, "items": result}


# ----------------------------------------------------------------------------
# Wetter (Open-Meteo, ohne API-Key)
# ----------------------------------------------------------------------------

WEATHER_CODES = {
    0: "klar", 1: "überwiegend klar", 2: "teils bewölkt", 3: "bedeckt", 45: "Nebel", 48: "Reifnebel",
    51: "leichter Nieselregen", 53: "Nieselregen", 55: "starker Nieselregen", 61: "leichter Regen",
    63: "Regen", 65: "starker Regen", 66: "gefrierender Regen", 67: "starker gefrierender Regen",
    71: "leichter Schneefall", 73: "Schneefall", 75: "starker Schneefall", 77: "Schneegriesel",
    80: "leichte Schauer", 81: "Schauer", 82: "heftige Schauer", 85: "Schneeschauer", 86: "starke Schneeschauer",
    95: "Gewitter", 96: "Gewitter mit Hagel", 99: "schweres Gewitter mit Hagel",
}


def weather(cfg):
    w = cfg["weather"]
    q = urllib.parse.urlencode({
        "latitude": w["latitude"], "longitude": w["longitude"],
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode",
        "hourly": "temperature_2m,weathercode",
        "timezone": "Europe/Berlin", "forecast_days": 1,
    })
    data = json.loads(fetch("https://api.open-meteo.com/v1/forecast?" + q).decode("utf-8"))
    d = data["daily"]
    hourly = data.get("hourly", {})
    stunden = {}
    for t, temp, code in zip(hourly.get("time", []), hourly.get("temperature_2m", []), hourly.get("weathercode", [])):
        stunden[t[11:16]] = {"temp": round(temp), "text": WEATHER_CODES.get(code, "wechselhaft")}
    return {
        "place": w["place"], "date": d["time"][0],
        "tmax": round(d["temperature_2m_max"][0]), "tmin": round(d["temperature_2m_min"][0]),
        "rain_prob": d["precipitation_probability_max"][0],
        "text": WEATHER_CODES.get(d["weathercode"][0], "wechselhaft"),
        "hourly": stunden,
    }


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    sf = sub.add_parser("fetch")
    sf.add_argument("-o", "--out", required=True)
    sf.add_argument("--no-images", action="store_true")
    sub.add_parser("weather")
    args = p.parse_args(argv)
    cfg = load_config()
    if args.cmd == "check":
        ok = True
        for src in cfg["sources"]:
            try:
                data = fetch(src["url"])
                items = parse_anthropic_news(data, src) if src.get("type") == "anthropic" else parse_feed(data, src)
                dated = sum(1 for i in items if i["published"])
                print(f"OK   {src['name']:<22} {len(items):3d} Einträge, {dated} mit Datum")
            except Exception as e:
                ok = False
                print(f"TOT  {src['name']:<22} {type(e).__name__}: {e}")
        return 0 if ok else 1
    if args.cmd == "fetch":
        res = collect(cfg, with_images=not args.no_images)
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
        log(f"{len(res['items'])} Meldungen -> {args.out}, {len(res['errors'])} Fehler")
        return 0
    if args.cmd == "weather":
        print(json.dumps(weather(cfg), ensure_ascii=False, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
