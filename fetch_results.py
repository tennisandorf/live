#!/usr/bin/env python3
"""
fetch_results.py
Ruft Tennis-Spielberichte vom ÖTVAT-Server ab, parst die Daten
und speichert sie als results.json für die Live-Seite.
"""

import json
import re
import urllib.request
import urllib.error
from datetime import datetime, timezone

# ── Hier die Spiele eintragen ──────────────────────────────────────────────────
MATCHES = [
    {
        "id": "1866397",
        "label": "TV Andorf 1 vs SPG Prambachki/Waizenki 1",
        "url": "https://oetv-austria.liga.nu/cgi-bin/WebObjects/nuLigaDokumentTENAT.woa/wa/nuDokument?dokument=MeetingReportFOP&meeting=1866397&etag=7d2f969c-5eae-4c42-a487-2d2da6cc1a78"
    },
    # Weitere Spiele einfach hier hinzufügen:
    # {
    #     "id": "1234567",
    #     "label": "Team A vs Team B",
    #     "url": "https://oetv-austria.liga.nu/..."
    # },
]
# ──────────────────────────────────────────────────────────────────────────────


def fetch_pdf_text(url: str) -> str:
    """Lädt die URL und gibt den Textinhalt zurück."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read()
    # pdfminer für echte PDFs, sonst plain-text / HTML
    try:
        from pdfminer.high_level import extract_text_to_fp
        from pdfminer.layout import LAParams
        import io
        out = io.StringIO()
        extract_text_to_fp(io.BytesIO(raw), out, laparams=LAParams(), output_type="text", codec="utf-8")
        return out.getvalue()
    except Exception:
        return raw.decode("utf-8", errors="replace")


def parse_header(text: str) -> dict:
    """Liest Bewerb, Runde, Termin und Mannschaften aus."""
    header = {}
    # Bewerb
    m = re.search(r"(OÖ\..+?)\n", text)
    if m:
        header["bewerb"] = m.group(1).strip()
    # Klasse / Gruppe
    m = re.search(r"\n(.+?)\n.*?Spielbericht", text, re.DOTALL)
    if m:
        header["gruppe"] = m.group(1).strip()
    # Runde & Datum
    m = re.search(r"Termin\s+(\d{2}\.\d{2}\.\d{4})\s+(\d{2}:\d{2})\s+-\s+(.+?)(?:\n|Spielbericht)", text)
    if m:
        header["datum"] = m.group(1)
        header["uhrzeit"] = m.group(2)
        header["runde"] = m.group(3).strip()
    # Heimmannschaft & Gastmannschaft + Ergebnis
    m = re.search(r"(TV .+?|UTC .+?|SPG .+?|TC .+?|ATSV .+?|USV .+?)\s+:\s+(.+?)\s+(\d+)\s*:\s*(\d+)", text)
    if m:
        header["heim"] = m.group(1).strip()
        header["gast"] = m.group(2).strip()
        header["ergebnis_heim"] = int(m.group(3))
        header["ergebnis_gast"] = int(m.group(4))
    else:
        # Spiel noch nicht begonnen – nur Mannschaftsnamen
        m2 = re.search(r"(TV .+?|UTC .+?|SPG .+?|TC .+?|ATSV .+?|USV .+?)\s+:\s+(.+?)\s+Ergebnis", text)
        if m2:
            header["heim"] = m2.group(1).strip()
            header["gast"] = m2.group(2).strip()
            header["ergebnis_heim"] = None
            header["ergebnis_gast"] = None
    return header


def parse_singles(text: str) -> list:
    """Parst alle Einzel-Matches."""
    singles = []
    # Suche Zeilen mit Spielernamen und Satzergebnissen
    pattern = re.compile(
        r"(\d+)\s+"                          # Platznr
        r"\d+\s+\d+\s+"                      # Meldelistennr + Lizenznr (Heim)
        r"(.+?)\s+ITN\s+([\d,]+)\s+"         # Spieler Heim + ITN
        r"\d+\s+\d+\s+"                      # Meldelistennr + Lizenznr (Gast)
        r"(.+?)\s+(?:\(ret\.\)\s+)?ITN\s+([\d,]+)\s+"  # Spieler Gast + ITN
        r"(\d+):(\d+)\s+"                    # Satz 1
        r"(\d+):(\d+)\s+"                    # Satz 2
        r"(\d+):(\d+)"                       # Satz 3
    )
    for m in pattern.finditer(text):
        s1h, s1g = int(m.group(6)), int(m.group(7))
        s2h, s2g = int(m.group(8)), int(m.group(9))
        s3h, s3g = int(m.group(10)), int(m.group(11))
        winner = "heim" if s3h > s3g or (s3h == 0 and s3g == 0 and s1h > s1g) else "gast"
        singles.append({
            "nr": int(m.group(1)),
            "heim": m.group(2).strip(),
            "heim_itn": m.group(3),
            "gast": m.group(4).strip(),
            "gast_itn": m.group(5),
            "satz1": f"{s1h}:{s1g}",
            "satz2": f"{s2h}:{s2g}",
            "satz3": f"{s3h}:{s3g}" if not (s3h == 0 and s3g == 0) else "",
            "winner": winner,
        })
    return singles


def parse_doubles(text: str) -> list:
    """Parst Doppel-Matches (vereinfacht)."""
    doubles = []
    # Doppel-Abschnitt isolieren
    m = re.search(r"Doppel(?:,.*?)?\n(.+?)Doppel-Summe", text, re.DOTALL)
    if not m:
        return doubles
    block = m.group(1)
    # Satzergebnisse suchen
    sat_pattern = re.compile(r"(\d+):(\d+)\s+(\d+):(\d+)\s+(\d+):(\d+)")
    for i, sm in enumerate(sat_pattern.finditer(block), 1):
        s1h, s1g = int(sm.group(1)), int(sm.group(2))
        s2h, s2g = int(sm.group(3)), int(sm.group(4))
        s3h, s3g = int(sm.group(5)), int(sm.group(6))
        doubles.append({
            "nr": i,
            "satz1": f"{s1h}:{s1g}",
            "satz2": f"{s2h}:{s2g}",
            "satz3": f"{s3h}:{s3g}" if not (s3h == 0 and s3g == 0) else "",
            "winner": "heim" if s1h > s1g else "gast",
        })
    return doubles


def process_match(match: dict) -> dict:
    """Verarbeitet ein einzelnes Spiel komplett."""
    result = {
        "id": match["id"],
        "label": match["label"],
        "url": match["url"],
        "status": "error",
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "header": {},
        "singles": [],
        "doubles": [],
    }
    try:
        text = fetch_pdf_text(match["url"])
        result["header"] = parse_header(text)
        result["singles"] = parse_singles(text)
        result["doubles"] = parse_doubles(text)
        if result["header"].get("ergebnis_heim") is not None:
            result["status"] = "finished"
        elif result["singles"]:
            result["status"] = "live"
        else:
            result["status"] = "upcoming"
    except Exception as e:
        result["error"] = str(e)
    return result


def main():
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "matches": []
    }
    for match in MATCHES:
        print(f"Verarbeite: {match['label']} ...")
        data = process_match(match)
        output["matches"].append(data)
        print(f"  Status: {data['status']}")

    with open("results.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("results.json gespeichert.")


if __name__ == "__main__":
    main()

