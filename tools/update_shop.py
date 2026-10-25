"""Für alle NerdClocks: neueste Produkte aus dem Nerdminer.de-Shop als kleine Liste + Bilder bereitstellen.
Quelle: https://nerdminer.de/products.json (Shopify, öffentlich). Ausgabe: shop/shop.json + shop/img/<id>.jpg (300×300, Baseline-JPEG
für den Bilddecoder der Uhr). Die Uhr lädt nur diese kleinen Dateien (GitHub Pages) – nicht die große Shop-Liste.
Aufruf: python -I tools/update_shop.py shop"""
import html
import io
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "shop")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NerdClock-Shopfeed"}
MAX = 8                    # so viele Produkte zeigt die Uhr
NEW_DAYS = 45              # so lange gilt ein Produkt als „neu“


def get(url, timeout=30):
    """Über curl (Shopify blockt Pythons urllib mit 429), bis zu 3 Versuche."""
    import subprocess, time
    for k in range(3):
        r = subprocess.run(["curl", "-sfL", "-m", str(timeout), "-A", UA["User-Agent"], url], capture_output=True)
        if r.returncode == 0 and r.stdout: return r.stdout
        time.sleep(5 * (k + 1))
    raise SystemExit(f"nicht erreichbar: {url}")


def short(body):
    """Erster Satz/Absatz aus der Produktbeschreibung, ohne HTML, höchstens ~140 Zeichen."""
    t = html.unescape(re.sub(r"<[^>]+>", "\n", body or ""))
    for line in (l.strip() for l in t.split("\n")):
        line = line.lstrip("✓•-– ").strip()
        if len(line) >= 25:
            if len(line) > 140: line = line[:137].rsplit(" ", 1)[0] + " …"
            return line
    return ""


def price(v):
    p = float(v)
    s = f"{p:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return (s[:-3] if s.endswith(",00") else s) + " €"


def main():
    data = json.loads(get("https://nerdminer.de/products.json?limit=250"))
    prods = [p for p in data["products"] if p.get("images") and p.get("variants")]
    prods.sort(key=lambda p: p.get("published_at") or p["created_at"], reverse=True)
    sel = json.loads((OUT / "auswahl.json").read_text(encoding="utf-8")) if (OUT / "auswahl.json").exists() else {}
    if sel:                                                       # Auswahl: feste Artikel zuerst, dann neue ab Datum; nie Zubehör
        nie = [w.lower() for w in sel.get("nie", [])]
        ok = lambda p: not any(w in p["title"].lower() for w in nie)
        by = {p["handle"]: p for p in prods}
        fest = [by[h] for h in sel.get("fest", []) if h in by and ok(by[h])]
        neu = [p for p in prods if p not in fest and ok(p) and (p.get("published_at") or p["created_at"])[:10] >= sel.get("neu_ab", "9999")]
        prods = neu + fest                                         # ganz neue Artikel vorne, dann die festen in ihrer Reihenfolge
    now = datetime.now(timezone.utc)
    (OUT / "img").mkdir(parents=True, exist_ok=True)
    items = []
    for p in prods[:MAX]:
        pid = str(p["id"]); v = p["variants"][0]
        pub = datetime.fromisoformat((p.get("published_at") or p["created_at"]).replace("Z", "+00:00"))
        img = OUT / "img" / f"{pid}.jpg"
        if not img.exists():
            src = p["images"][0]["src"]
            raw = get(src + ("&" if "?" in src else "?") + "width=600")
            im = Image.open(io.BytesIO(raw)).convert("RGBA")
            bg = Image.new("RGBA", im.size, (255, 255, 255, 255)); bg.alpha_composite(im)
            im = bg.convert("RGB"); im.thumbnail((300, 300), Image.LANCZOS)
            sq = Image.new("RGB", (300, 300), (255, 255, 255)); sq.paste(im, ((300 - im.width) // 2, (300 - im.height) // 2))
            sq.save(img, "JPEG", quality=86, progressive=False, optimize=True)
        it = {"id": pid, "t": p["title"].strip(), "p": price(v["price"]), "d": short(p.get("body_html")),
              "u": f"https://nerdminer.de/products/{p['handle']}", "img": f"shop/img/{pid}.jpg", "date": pub.strftime("%Y-%m-%d"),
              "n": 1 if now - pub < timedelta(days=NEW_DAYS) else 0}
        if v.get("compare_at_price") and float(v["compare_at_price"]) > float(v["price"]): it["alt"] = price(v["compare_at_price"])
        items.append(it)
    for v_ in sel.get("vorschau", []) if sel else []:             # noch nicht lieferbar: von Hand eingetragen, mit „ab“
        if len(items) >= MAX: break
        items.insert(0, {"id": v_["id"], "t": v_["t"], "p": v_.get("p", ""), "d": v_.get("d", ""), "u": v_.get("u", "https://nerdminer.de"),
                         "img": f"shop/img/{v_['id']}.jpg", "date": now.strftime("%Y-%m-%d"), "n": 1, "ab": v_["ab"]})
    keep = {f"{i['id']}.jpg" for i in items}                     # Bilder alter Produkte aufräumen
    for f in (OUT / "img").glob("*.jpg"):
        if f.name not in keep: f.unlink()
    doc = {"v": 1, "items": items}
    old = (OUT / "shop.json").read_text(encoding="utf-8") if (OUT / "shop.json").exists() else ""
    new = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    if new != old: (OUT / "shop.json").write_text(new, encoding="utf-8")
    print(len(items), "Produkte,", sum(i["n"] for i in items), "neu")


main()
