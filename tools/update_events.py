"""Aktualisiert events.json automatisch mit Bitcoin-Events in Europa von bitcoinonly.events.

- liest die Startseite (Datum, Name, Landesflagge, Stadt, Link je Event)
- übernimmt nur europäische Länder
- eigene Einträge in events.json (z. B. Zitadelle, Wild BTC) bleiben erhalten (Abgleich über den Link)
- behält vergangene Events des laufenden Jahres (werden auf der NerdClock grau), ältere fliegen raus
- höchstens 24 Einträge (so viele fasst die NerdClock)

Aufruf:  python update_events.py <events.json>     (läuft wöchentlich als GitHub-Action in NerdClock-Updates)
"""
import datetime as dt
import html
import json
import re
import sys
import urllib.request

SRC = "https://bitcoinonly.events/"
EUROPE = {"at", "be", "bg", "ch", "cy", "cz", "de", "dk", "ee", "es", "fi", "fr", "gb", "gr", "hr", "hu", "ie",
          "is", "it", "li", "lt", "lu", "lv", "mc", "me", "mt", "nl", "no", "pl", "pt", "ro", "rs", "se", "si",
          "sk", "sm", "ua", "al", "ba", "mk", "md"}
MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MAX = 24


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "NerdClock-Events/1.0 (+https://nerdminer.de)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s))).strip()


def parse(page):
    out = []
    for blk in re.findall(r'<div class="event_blk[^"]*">(.*?)Show more</a>', page, re.S):
        mon = re.search(r'class="event_month[^"]*">([^<]+)<', blk)
        day = re.search(r'class="event_day[^"]*">([^<]+)<', blk)
        yr = re.search(r'class="event_year[^"]*">(\d{4})<', blk)
        name = re.search(r'class="event_name">(.*?)</p>', blk, re.S)
        loc = re.search(r'class="event_location">.*?flags/([a-z]{2})\.png[^>]*>([^<]*)</p>', blk, re.S)
        link = re.search(r'<a href="(https://bitcoinonly\.events/[^"]+)"', blk)
        if not (mon and day and yr and name and loc and link):
            continue
        cc = loc.group(1)
        if cc not in EUROPE:
            continue
        months = [MONTHS.get(m.strip()[:3].lower()) for m in mon.group(1).split("-")]
        days = [int(d) for d in re.findall(r"\d+", day.group(1))]
        if not months[0] or not days:
            continue
        y = int(yr.group(1))
        m1, d1 = months[0], days[0]
        d2 = days[-1]
        m2 = months[-1] if len(months) > 1 and months[-1] else (m1 + 1 if d2 < d1 else m1)
        y2 = y + 1 if m2 < m1 else y
        if m2 > 12:
            m2, y2 = 1, y + 1
        title = re.sub(r"<span.*", "", name.group(1), flags=re.S)
        title = re.sub(r"\s+(19|20)\d{2}\b", "", clean(title))          # Jahreszahl im Namen weg
        out.append({
            "name": title[:47], "city": clean(loc.group(2))[:27], "cc": "UK" if cc == "gb" else cc.upper(),
            "start": y * 10000 + m1 * 100 + d1, "end": y2 * 10000 + m2 * 100 + d2, "url": link.group(1)[:99],
        })
    return out


def main(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    def key(e):                                             # gleiche Seite, aber anderes Jahr = anderes Event
        return (e.get("url") or e["name"], e.get("start", 0) // 10000)
    events = {key(e): e for e in data.get("events", [])}
    found = parse(fetch(SRC))
    new = 0
    for e in found:
        k = key(e)
        if k not in events:
            new += 1
        old = events.get(k, {})
        merged = {**old, **e}
        for f in ("name", "city"):                          # eigene Schreibweise behalten, Daten aktualisieren
            if old.get(f):
                merged[f] = old[f]
        events[k] = merged
    today = dt.date.today()
    first = today.year * 10000 + 101
    keep = [e for e in events.values() if e.get("end", e.get("start", 0)) >= first]
    keep.sort(key=lambda e: e["start"])
    now = today.year * 10000 + today.month * 100 + today.day
    while len(keep) > MAX:                                  # zu viele: älteste vergangene zuerst entfernen
        past = [e for e in keep if e.get("end", e["start"]) < now]
        keep.remove(past[0] if past else keep[-1])
    data["events"] = keep
    data["updated"] = today.isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"{len(found)} Events in Europa gefunden, {new} neu, {len(keep)} in der Liste")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "events.json")
