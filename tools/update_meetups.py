"""Erzeugt meetups_next.json: die nächsten Termine aller Bitcoin-Meetups aus dem Einundzwanzig-Portal – winzig (wenige KB),
damit die NerdClock ihren Kalender abgleichen kann, ohne die ganze Portal-Seite (hunderte Meetups) zu laden.

Format:  {"m": [["Meetup-Name", "2026-11-21T16:00", "Ort"], ...]}      (Zeit in UTC, wie im Portal)
Aufruf:  python update_meetups.py <meetups_next.json>     (läuft täglich als GitHub-Action in NerdClock-Updates)
"""
import json
import sys
import urllib.request

SRC = "https://portal.einundzwanzig.space/api/meetups"


def main(out):
    req = urllib.request.Request(SRC, headers={"User-Agent": "NerdClock-Meetups/1.0 (+https://nerdminer.de)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    rows = []
    for m in data:
        ev = m.get("next_event") or {}
        start = (ev.get("start") or "")[:16]
        if not start or not m.get("name"):
            continue
        place = ev.get("osm_name") or m.get("city") or ""
        rows.append([m["name"].strip(), start, place.strip()])
    rows.sort(key=lambda r: r[0].lower())
    if len(rows) < 20:                                    # Portal liefert Unsinn → alte Datei behalten
        raise SystemExit(f"nur {len(rows)} Termine – abgebrochen")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"m": rows}, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(rows)} Meetup-Termine -> {out}")


if __name__ == "__main__":
    main(sys.argv[1])
