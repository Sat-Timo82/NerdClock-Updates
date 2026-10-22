"""NerdClock News-Dienst — eigene Bitcoin-News ohne externen News-Anbieter.

1. Sammelt Meldungen aus frei zugänglichen RSS-Feeds seriöser Bitcoin-Medien.
2. Mit API-Schlüssel (ANTHROPIC_API_KEY): Claude wählt die 10 wichtigsten, echten
   Bitcoin-Meldungen aus und schreibt sie kurz auf Deutsch zusammen.
   Ohne Schlüssel: einfacher Stichwortfilter (kostenlos, Originaltitel).
3. Schreibt news.json — die NerdClock lädt diese Datei regelmäßig.
4. Übersetzt jede Meldung in alle 6 Sprachen der Uhr (mit API-Schlüssel, nur neue Meldungen –
   gemerkt in news_cache.json) und schreibt news_de.json … news_it.json. Ohne Schlüssel: Originaltext.

Aufruf:  python tools/news/make_news.py [ausgabe.json]
Umgebung: ANTHROPIC_API_KEY (optional), NEWS_MODEL (Standard: claude-opus-5-5)
"""
import hashlib
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

FEEDS = {
    "Blocktrainer": "https://www.blocktrainer.de/feed/",
    "BTC-ECHO": "https://www.btc-echo.de/feed/",
    "Bitcoin Magazine": "https://bitcoinmagazine.com/.rss/full/",
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Cointelegraph": "https://cointelegraph.com/rss/tag/bitcoin",
    "The Block": "https://www.theblock.co/rss.xml",
    "Decrypt": "https://decrypt.co/feed",
    "Bitcoin.com News": "https://news.bitcoin.com/feed/",
    "Bitcoinist": "https://bitcoinist.com/feed/",
}
FEED_LANG = {"Blocktrainer": "de", "BTC-ECHO": "de"}      # Quellen im Original auf Deutsch, alle anderen Englisch
MAX_AGE_H = 48          # nur Meldungen der letzten 48 Stunden
MAX_ITEMS = 10          # so viele zeigt die NerdClock (2 × 5)
MODEL = os.environ.get("NEWS_MODEL", "claude-opus-5-5")

# ── Text für die Display-Schrift aufbereiten (Inter-Zeichensatz der NerdClock) ──
DISPLAY_EXTRA = set("äöüÄÖÜß€·–°…₿Ø≈")
REPL = {"„": '"', "“": '"', "”": '"', "‚": "'", "‘": "'", "’": "'", "—": "–", "−": "-",
        " ": " ", "‹": "'", "›": "'", "«": '"', "»": '"', "×": "x"}


def for_display(s, limit):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = "".join(REPL.get(c, c) for c in s)
    out = []
    for c in s:
        if 32 <= ord(c) < 127 or c in DISPLAY_EXTRA:
            out.append(c)
        else:   # Akzente vereinfachen (é → e), Unbekanntes weglassen
            base = unicodedata.normalize("NFKD", c).encode("ascii", "ignore").decode()
            out.append(base)
    s = re.sub(r"\s+", " ", "".join(out)).strip()
    if len(s) > limit:
        s = s[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:.-–") + "…"
    return s


# ── RSS einlesen ──
def fetch_feed(name, url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 NerdClock-News/1.0"})
    root = ET.fromstring(urllib.request.urlopen(req, timeout=20).read())
    items = []
    for it in root.findall(".//item"):
        title = it.findtext("title") or ""
        link = it.findtext("link") or ""
        desc = it.findtext("description") or ""
        try:
            ts = int(parsedate_to_datetime(it.findtext("pubDate")).timestamp())
        except Exception:
            ts = int(time.time())
        items.append({"id": hashlib.sha1(link.encode()).hexdigest()[:10], "source": name,
                      "title": title.strip(), "desc": desc, "url": link.strip(), "ts": ts, "lang": FEED_LANG.get(name, "en")})
    return items


def collect():
    now = time.time()
    all_items, seen = [], set()
    for name, url in FEEDS.items():
        try:
            for it in fetch_feed(name, url):
                if now - it["ts"] > MAX_AGE_H * 3600 or it["id"] in seen:
                    continue
                seen.add(it["id"])
                all_items.append(it)
        except Exception as e:
            print(f"Quelle übersprungen: {name} ({type(e).__name__})")
    all_items.sort(key=lambda x: x["ts"], reverse=True)
    return all_items


# ── Variante ohne KI: Stichwortfilter ──
BTC_WORDS = re.compile(r"bitcoin|\bbtc\b|saylor|microstrategy|\bstrategy\b|\betf|wal(e|e)?\b|whale|"
                       r"halving|miner|mining|lightning|satoshi|hashrate|el salvador|blackrock", re.I)
ALT_WORDS = re.compile(r"solana|ethereum|\bether\b|\beth\b|lido|staked|stablecoin|tether|usdt|usdc|xrp|ripple|cardano|dogecoin|memecoin|\bsui\b|"
                       r"tokeni[sz]|altcoin|nft", re.I)


def clean_summary(desc, title, source):
    """Viele Feeds beginnen die Beschreibung mit Quelle und Titel — das steht schon darüber."""
    d = re.sub(r"<[^>]+>", " ", html.unescape(desc or ""))
    d = re.sub(r"\s+", " ", d).strip()
    for pre in (source, title, source, title):
        if pre and d.lower().startswith(pre.lower()):
            d = d[len(pre):].lstrip(" :–—-|·")
    return d


def select_keywords(items):
    picked = [it for it in items if BTC_WORDS.search(it["title"]) and not ALT_WORDS.search(it["title"])]
    # dieselbe Meldung aus mehreren Quellen nur einmal (Titel teilen viele markante Wörter, z. B. "Capital B … loss")
    def words(t):
        return {w for w in re.findall(r"[a-z0-9$€]+", t.lower()) if len(w) > 3 or w[0].isdigit() or w[0] in "$€"}
    uniq = []
    for it in picked:
        w = words(it["title"])
        if any(len(w & words(u["title"])) >= max(3, min(len(w), len(words(u["title"]))) // 2) for u in uniq):
            continue
        uniq.append(it)
    picked = uniq
    return [{"id": it["id"], "title": for_display(it["title"], 95),
             "summary": for_display(clean_summary(it["desc"], it["title"], it.get("source", "")), 330)}
            for it in picked[:MAX_ITEMS]]


# ── Variante mit KI (Claude) ──
SYSTEM = """Du bist Redakteur der Bitcoin-Nachrichtenanzeige "NerdClock" von nerdminer.de.
Aus einer Liste aktueller Meldungen wählst du die bis zu 10 wichtigsten aus.

Aufnehmen: echte, relevante Bitcoin-Nachrichten — z. B. Unternehmen oder Staaten kaufen/verkaufen
Bitcoin (Strategy/MicroStrategy, ETFs, El Salvador), große Wal-Bewegungen, ETF-Zu- und Abflüsse,
Regulierung und Gesetze mit Bitcoin-Bezug, Mining/Hashrate, Lightning, Protokoll-Updates,
bedeutende Kursereignisse.
Weglassen: Altcoins, Memecoins, Tokenisierung ohne Bitcoin-Bezug, Werbung, reine Kursprognosen
und Spekulation, Gerüchte ohne Quelle, Doppelmeldungen (dasselbe Ereignis nur einmal, die
seriöseste Quelle wählen).

Für jede ausgewählte Meldung schreibst du auf Deutsch:
- title: prägnante Überschrift, höchstens 80 Zeichen
- summary: 2–3 sachliche Sätze, höchstens 320 Zeichen, nur Fakten aus der Meldung
Gib die id der Meldung unverändert zurück. Lieber weniger als 10 als unwichtige Meldungen."""

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                },
                "required": ["id", "title", "summary"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def select_with_claude(items):
    import anthropic

    client = anthropic.Anthropic()   # liest ANTHROPIC_API_KEY aus der Umgebung
    listing = "\n".join(
        f'id={it["id"]} | {it["source"]} | {time.strftime("%d.%m. %H:%M", time.gmtime(it["ts"]))} UTC | '
        f'{for_display(it["title"], 160)} | {for_display(it["desc"], 300)}'
        for it in items[:80]
    )
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",                       # bei Ablehnung automatisch auf ein anderes Modell ausweichen
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        system=SYSTEM,
        messages=[{"role": "user", "content": "Aktuelle Meldungen:\n" + listing}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"Anfrage abgelehnt: {response.stop_details}")
    text = next(b.text for b in response.content if b.type == "text")
    chosen = json.loads(text)["items"]
    print(f"KI ({response.model}): {len(chosen)} Meldungen, "
          f"{response.usage.input_tokens} Eingabe-/{response.usage.output_tokens} Ausgabe-Tokens")
    return [{"id": c["id"], "title": for_display(c["title"], 95),
             "summary": for_display(c["summary"], 330)} for c in chosen]


# ── Übersetzung in alle Sprachen der Uhr (Sprach-Knöpfe im News-Bericht) ──
LANGS = ["de", "en", "fr", "es", "nl", "it"]
TR_MODEL = os.environ.get("NEWS_TR_MODEL", "claude-sonnet-5-5")
TR_SYSTEM = """Du übersetzt Bitcoin-Nachrichten für die Anzeige "NerdClock" in die Sprachen
de (Deutsch), en (Englisch), fr (Französisch), es (Spanisch), nl (Niederländisch), it (Italienisch).
Sinngetreu, natürlich und sachlich; Fachbegriffe wie Bitcoin, Mining, Hashrate, ETF, Lightning, Satoshi,
Wallet, Halving bleiben. Namen, Zahlen und Firmen unverändert. Titel höchstens 80 Zeichen,
Zusammenfassung höchstens 320 Zeichen. Gib die id unverändert zurück."""
TR_SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {
    "type": "object",
    "properties": dict({"id": {"type": "string"}}, **{l: {"type": "object", "properties": {
        "title": {"type": "string"}, "summary": {"type": "string"}}, "required": ["title", "summary"],
        "additionalProperties": False} for l in LANGS}),
    "required": ["id"] + LANGS, "additionalProperties": False}}},
    "required": ["items"], "additionalProperties": False}


def news_id(n):
    return hashlib.sha1(n["url"].encode("utf-8")).hexdigest()[:12]


def translate(news, cache):
    """Fehlende Übersetzungen ergänzen (nur neue Meldungen) – cache: id → {sprache: {title, summary}}."""
    todo = [n for n in news if news_id(n) not in cache]
    if not todo or not os.environ.get("ANTHROPIC_API_KEY"):
        return
    import anthropic
    client = anthropic.Anthropic()
    listing = json.dumps([{"id": news_id(n), "title": n["title"], "summary": n["summary"]} for n in todo], ensure_ascii=False)
    response = client.messages.create(
        model=TR_MODEL, max_tokens=16000,
        output_config={"format": {"type": "json_schema", "schema": TR_SCHEMA}},
        system=TR_SYSTEM, messages=[{"role": "user", "content": listing}])
    text = next(b.text for b in response.content if b.type == "text")
    for it in json.loads(text)["items"]:
        cache[it["id"]] = {l: {"title": for_display(it[l]["title"], 95), "summary": for_display(it[l]["summary"], 330)} for l in LANGS}
    print(f"Übersetzt: {len(todo)} Meldungen ({response.usage.input_tokens}/{response.usage.output_tokens} Tokens)")


def to_news(picked, by_id):
    news = []
    for p in picked:
        it = by_id.get(p["id"])
        if not it:
            continue
        news.append({"title": p["title"], "summary": p["summary"], "source": it["source"],
                     "ts": it["ts"], "url": it["url"][:150], "ad": False})
    news.sort(key=lambda x: x["ts"], reverse=True)       # neueste zuerst (oben links)
    return news[:MAX_ITEMS]


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent / "news.json")
    items = collect()
    print(f"{len(items)} Meldungen aus {len(FEEDS)} Quellen gesammelt")
    by_id = {it["id"]: it for it in items}
    cache_f = out.parent / "news_cache.json"
    # Auswahl ohne KI (kostenlos): Deutsch aus den deutschen Quellen, Englisch aus den englischen (echte Texte, keine Übersetzung nötig).
    de = to_news(select_keywords([i for i in items if i["lang"] == "de"]), by_id)
    en = to_news(select_keywords([i for i in items if i["lang"] == "en"]), by_id)
    if len(de) < 3:
        de = to_news(select_keywords(items), by_id)           # Notfall: zu wenige deutsche Meldungen
    per = {"de": de, "en": en}
    # fr/es/nl/it: die englischen Meldungen übersetzen (nur neue; mit ANTHROPIC_API_KEY, sonst/bei Fehler bleibt Englisch)
    cache = json.loads(cache_f.read_text(encoding="utf-8")) if cache_f.exists() else {}
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            translate(en, cache)
        except Exception as e:
            print("Übersetzung fehlgeschlagen (Englisch bleibt):", type(e).__name__, e)
    ids = {news_id(n) for n in en}
    cache = {k: v for k, v in cache.items() if k in ids}                 # nur aktuelle Meldungen merken
    cache_f.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    for l in ("fr", "es", "nl", "it"):
        per[l] = [dict(n, **cache.get(news_id(n), {}).get(l, {})) for n in en]
    for l, lst in per.items():
        d = {"updated": int(time.time()), "mode": "stichworte", "lang": l, "items": lst}
        (out.parent / f"news_{l}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        if l == "de":
            out.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    translated = sum(1 for n in en if "fr" in cache.get(news_id(n), {}))
    print(f"Gespeichert: {len(de)} deutsche, {len(en)} englische Meldungen; {translated} davon übersetzt (fr/es/nl/it)")


if __name__ == "__main__":
    main()
