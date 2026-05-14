#!/usr/bin/env python3
import json, re, io, urllib.request
from datetime import datetime, timezone

BASE_URL = (
    "https://oetv-austria.liga.nu/cgi-bin/WebObjects/nuLigaDokumentTENAT.woa"
    "/wa/nuDokument?dokument=MeetingReportFOP&meeting={meeting_id}"
)

MATCHES = [
    {"meeting_id": "1866397"},
    {"meeting_id": "1861376"},
    {"meeting_id": "1863373", "datum_override": "14.05.2026"},  # ursprünglich 17.05., vorverlegt
    {"meeting_id": "1866859"},
    {"meeting_id": "1860681"},
    {"meeting_id": "1863909"},
    {"meeting_id": "1867090"},
    {"meeting_id": "1866167"},
    {"meeting_id": "1861028"},
    {"meeting_id": "1867134"},
    {"meeting_id": "1866988"},
    {"meeting_id": "1860465"},
    {"meeting_id": "1861454"},
    {"meeting_id": "1864022"},
    {"meeting_id": "1860786"},
    {"meeting_id": "1863290"},
    {"meeting_id": "1866146"},
    {"meeting_id": "1860453"},
    {"meeting_id": "1861626"},
    {"meeting_id": "1863914"},
    {"meeting_id": "1867129"},
    {"meeting_id": "1866925"},
    {"meeting_id": "1860973"},
    {"meeting_id": "1863177"},
    {"meeting_id": "1866408"},
    {"meeting_id": "1860517"},
    {"meeting_id": "1861580"},
    {"meeting_id": "1863861"},
    {"meeting_id": "1867264"},
    {"meeting_id": "1866916"},
    {"meeting_id": "1861040"},
    {"meeting_id": "1863275"},
]


def fetch_text(meeting_id):
    url = BASE_URL.format(meeting_id=meeting_id)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "de-AT,de;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        content_type = resp.headers.get("Content-Type", "")
        raw = resp.read()
    print(f"    Content-Type: {content_type}, Size: {len(raw)} bytes")
    if b"%PDF" in raw[:10] or "pdf" in content_type.lower():
        try:
            from pdfminer.high_level import extract_text_to_fp
            from pdfminer.layout import LAParams
            out = io.StringIO()
            extract_text_to_fp(io.BytesIO(raw), out, laparams=LAParams(), output_type="text", codec="utf-8")
            text = out.getvalue()
            print(f"    PDF extrahiert: {len(text)} Zeichen")
            return text
        except Exception as e:
            print(f"    PDF-Fehler: {e}")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def parse_header(text):
    h = {}
    m = re.search(r"(OÖ\..+?)[\r\n]", text)
    if m: h["bewerb"] = m.group(1).strip()
    m = re.search(r"OÖ\..+?[\r\n](.+?)[\r\n]", text)
    if m: h["gruppe"] = m.group(1).strip()
    m = re.search(r"Termin\s+(\d{2}\.\d{2}\.\d{4})\s+(\d{2}:\d{2})\s+-\s+(.+?)[\r\n]", text)
    if m:
        h["datum"] = m.group(1)
        h["uhrzeit"] = m.group(2)
        h["runde"] = m.group(3).strip()
        d = m.group(1).split(".")
        h["datum_iso"] = f"{d[2]}-{d[1]}-{d[0]}"
    m = re.search(r"vollständig erfasst am\s+(\d{2}\.\d{2}\.\d{4})\s+(\d{2}:\d{2})", text)
    if not m:
        # Alternative: "abgeschlossen am" im Termin-Header
        m = re.search(r"abgeschlossen am\s+(\d{2}\.\d{2}\.\d{4})", text)
        if m:
            h["erfasst_datum"] = m.group(1)
            h["erfasst_uhrzeit"] = ""
    if m and len(m.groups()) >= 2:
        h["erfasst_datum"]   = m.group(1)
        h["erfasst_uhrzeit"] = m.group(2)
    m = re.search(r"^(.+?)\s+:\s+(.+?)\s+(\d+)\s*:\s*(\d+)\s*$", text, re.MULTILINE)
    if m:
        h["heim"] = m.group(1).strip()
        h["gast"] = m.group(2).strip()
        h["ergebnis_heim"] = int(m.group(3))
        h["ergebnis_gast"] = int(m.group(4))
    else:
        m2 = re.search(r"^(.+?)\s+:\s+(.+?)\s+Ergebnis", text, re.MULTILINE)
        if m2:
            h["heim"] = m2.group(1).strip()
            h["gast"] = m2.group(2).strip()
        h["ergebnis_heim"] = None
        h["ergebnis_gast"] = None
    return h


def parse_singles(text):
    singles = []
    m = re.search(r"Einzel.*?[\r\n](.*?)Doppel", text, re.DOTALL | re.IGNORECASE)
    if not m:
        return singles
    block = m.group(1)

    # Alle Spielernamen mit ITN finden
    name_itn = re.findall(r"([A-ZÄÖÜ][a-zäöüß\-]+,\s[A-ZÄÖÜa-zäöüß\s\-]+?)\s+(?:UKR\s+|GER\s+|CZE\s+|SVK\s+|HUN\s+|AUT\s+)?ITN\s+([\d,]+)", block)
    n_singles = len(name_itn) // 2

    # Sätze erst NACH dem letzten Spieler-ITN extrahieren (Teamsummen > 30 ignorieren)
    last_itn_pos = 0
    for nm in re.finditer(r"ITN\s+([\d,]+)", block):
        try:
            if float(nm.group(1).replace(",", ".")) < 30:
                last_itn_pos = nm.end()
        except ValueError:
            pass
    score_block = block[last_itn_pos:]
    satz_scores = [(int(a), int(b)) for a, b in re.findall(r"(\d+):(\d+)", score_block)]

    # Namen kommen im PDF gruppiert: erst alle Heim, dann alle Gast
    heim_names = name_itn[:n_singles]
    gast_names = name_itn[n_singles:]

    for i in range(n_singles):
        try:
            heim_name, heim_itn = heim_names[i]
            gast_name, gast_itn = gast_names[i]
            s1h, s1g = satz_scores[i * 3]
            s2h, s2g = satz_scores[i * 3 + 1]
            s3h, s3g = satz_scores[i * 3 + 2]
            has_s3 = not (s3h == 0 and s3g == 0)
            sets_heim = (1 if s1h > s1g else 0) + (1 if s2h > s2g else 0) + (1 if has_s3 and s3h > s3g else 0)
            singles.append({
                "nr": i + 1,
                "heim": heim_name.strip().rstrip(","),
                "heim_itn": heim_itn.replace(",", "."),
                "gast": gast_name.strip().rstrip(","),
                "gast_itn": gast_itn.replace(",", "."),
                "satz1": f"{s1h}:{s1g}",
                "satz2": f"{s2h}:{s2g}",
                "satz3": f"{s3h}:{s3g}" if has_s3 else "",
                "winner": "heim" if sets_heim >= 2 else "gast",
            })
        except IndexError:
            break
    return singles


def parse_doubles(text):
    doubles = []
    normalized = re.sub(r'[ \t]+', ' ', text)
    normalized = re.sub(r'\n+', '\n', normalized)
    m = re.search(r"Doppel.*?erfasst.*?[\r\n](.*?)Doppel-Summe", normalized, re.DOTALL | re.IGNORECASE)
    if not m:
        return doubles
    block = m.group(1)

    # Alle Namen + ITN aus Doppel-Block
    name_itn = re.findall(r"([A-ZÄÖÜ][a-zäöüß\-]+,\s[A-ZÄÖÜa-zäöüß\s\-]+?)\s+(?:UKR\s+|GER\s+|CZE\s+|SVK\s+|HUN\s+|AUT\s+)?ITN\s+([\d,\.]+)", block)

    # Sätze erst NACH dem letzten Spieler-ITN extrahieren (Teamsummen > 30 ignorieren)
    last_itn_pos = 0
    for nm in re.finditer(r"ITN\s+([\d,\.]+)", block):
        try:
            if float(nm.group(1).replace(",", ".")) < 30:
                last_itn_pos = nm.end()
        except ValueError:
            pass
    score_block = block[last_itn_pos:]
    satz_scores = [(int(a), int(b)) for a, b in re.findall(r"(\d+):(\d+)", score_block)]

    # Namen kommen gruppiert: erst alle Heim-Paare, dann alle Gast-Paare
    n_doubles = len(name_itn) // 4
    heim_names = name_itn[:n_doubles * 2]
    gast_names = name_itn[n_doubles * 2:]

    for i in range(n_doubles):
        try:
            heim1 = heim_names[i * 2][0].strip().rstrip(",")
            heim2 = heim_names[i * 2 + 1][0].strip().rstrip(",")
            gast1 = gast_names[i * 2][0].strip().rstrip(",")
            gast2 = gast_names[i * 2 + 1][0].strip().rstrip(",")
            s1h, s1g = satz_scores[i * 3]
            s2h, s2g = satz_scores[i * 3 + 1]
            s3h, s3g = satz_scores[i * 3 + 2]
            has_s3 = not (s3h == 0 and s3g == 0)
            sets_heim = (1 if s1h > s1g else 0) + (1 if s2h > s2g else 0) + (1 if has_s3 and s3h > s3g else 0)
            doubles.append({
                "nr": i + 1,
                "heim": f"{heim1} / {heim2}",
                "gast": f"{gast1} / {gast2}",
                "satz1": f"{s1h}:{s1g}",
                "satz2": f"{s2h}:{s2g}",
                "satz3": f"{s3h}:{s3g}" if has_s3 else "",
                "winner": "heim" if sets_heim >= 2 else "gast",
            })
        except IndexError:
            break
    return doubles


def get_matches_to_fetch():
    """
    Gibt nur die relevanten Spiele zurück die tatsächlich abgerufen werden sollen:
    - Heute: alle (ab 1h vor Spielbeginn)
    - Nächste 7 Tage: alle (Vorschau)
    - Weiter in der Zukunft: nur einmal täglich (zur vollen Stunde ±5 Min)
    - Vergangen + finished: nie mehr
    - Vergangen + nicht finished: noch heute bis Mitternacht
    """
    import datetime as dt
    now_utc = datetime.now(timezone.utc)
    now_at = now_utc.replace(tzinfo=None) + dt.timedelta(hours=2)
    today = now_at.date()
    zur_vollen_stunde = now_at.minute < 5  # erste 5 Min jeder Stunde

    cached_matches = {}
    try:
        with open("results.json", encoding="utf-8") as f:
            cached = json.load(f)
        for cm in cached.get("matches", []):
            cached_matches[cm["meeting_id"]] = cm
    except Exception:
        pass

    to_fetch = []
    seen = set()
    for m in MATCHES:
        mid = m["meeting_id"]
        if mid in seen:
            continue
        seen.add(mid)

        datum_str = m.get("datum_override") or cached_matches.get(mid, {}).get("header", {}).get("datum")
        status = cached_matches.get(mid, {}).get("status")

        # Datum unbekannt oder noch nie abgerufen → immer abrufen
        if not datum_str or mid not in cached_matches:
            to_fetch.append(m)
            continue

        try:
            d, mo, y = datum_str.split(".")
            spiel_date = dt.date(int(y), int(mo), int(d))
        except Exception:
            to_fetch.append(m)
            continue

        diff = (spiel_date - today).days

        if diff == 0:
            # Heute: ab 1h vor Spielbeginn abrufen
            uhrzeit = cached_matches.get(mid, {}).get("header", {}).get("uhrzeit")
            if uhrzeit:
                try:
                    h, mi2 = map(int, uhrzeit.split(":"))
                    spielbeginn = now_at.replace(hour=h, minute=mi2, second=0, microsecond=0)
                    if now_at >= spielbeginn - dt.timedelta(hours=1):
                        to_fetch.append(m)
                except Exception:
                    to_fetch.append(m)
            else:
                to_fetch.append(m)

        elif 0 < diff <= 7:
            # Nächste 7 Tage: alle 12 Stunden (0:00 und 12:00)
            if now_at.hour in (0, 12) and zur_vollen_stunde:
                to_fetch.append(m)

        elif diff > 7:
            # Weiter in der Zukunft: alle 24 Stunden (0:00)
            if now_at.hour == 0 and zur_vollen_stunde:
                to_fetch.append(m)

        elif diff < 0:
            # Vergangen → nie mehr abrufen (aus Cache)
            pass

    return to_fetch


def process_match(meeting_id, datum_override=None):
    result = {
        "meeting_id": meeting_id,
        "url": BASE_URL.format(meeting_id=meeting_id),
        "status": "error",
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "header": {}, "singles": [], "doubles": [],
    }
    try:
        text = fetch_text(meeting_id)
        if meeting_id == "1863373":
            print("RAW TEXT:")
            print(repr(text[:3000]))
        result["header"] = parse_header(text)
        result["singles"] = parse_singles(text)
        result["doubles"] = parse_doubles(text)
        print(f"    → erfasst={result['header'].get('erfasst_datum','–')} singles={len(result['singles'])} doubles={len(result['doubles'])}")
        if datum_override:
            d = datum_override.split(".")
            result["header"]["datum"] = datum_override
            result["header"]["datum_iso"] = f"{d[2]}-{d[1]}-{d[0]}"
            print(f"    ⚠ Datum überschrieben: {datum_override}")
        h = result["header"]
        if h.get("erfasst_datum"):
            result["status"] = "finished"
        elif result["singles"] or result["doubles"]:
            result["status"] = "live"
        else:
            result["status"] = "upcoming"
    except Exception as e:
        result["error"] = str(e)
    return result


def should_run():
    """
    Läuft immer, außer:
    - Alle Spiele sind 'finished' UND kein Spiel in den nächsten 60 Tagen
    An Spieltagen: ab 1h vor Spielbeginn bis Mitternacht (alle 5 Min)
    Sonst: läuft durch für Vorschau-Updates
    """
    import datetime as dt
    now_utc = datetime.now(timezone.utc)
    now_at = now_utc.replace(tzinfo=None) + dt.timedelta(hours=2)
    today = now_at.date()

    # Gecachte results.json laden
    cached_matches = {}
    try:
        with open("results.json", encoding="utf-8") as f:
            cached = json.load(f)
        for cm in cached.get("matches", []):
            cached_matches[cm["meeting_id"]] = cm
    except Exception:
        return True  # Kein Cache → immer laufen

    has_future = False
    for m in MATCHES:
        mid = m["meeting_id"]
        datum_str = m.get("datum_override") or cached_matches.get(mid, {}).get("header", {}).get("datum")

        # Datum noch unbekannt (neues Spiel ohne Cache) → laufen lassen
        if not datum_str:
            return True

        try:
            d, mo, y = datum_str.split(".")
            spiel_date = dt.date(int(y), int(mo), int(d))
        except Exception:
            return True

        diff = (spiel_date - today).days

        # Spiel heute → ab 1h vor Spielbeginn
        if diff == 0:
            uhrzeit = cached_matches.get(mid, {}).get("header", {}).get("uhrzeit")
            if uhrzeit:
                try:
                    h, mi2 = map(int, uhrzeit.split(":"))
                    spielbeginn = now_at.replace(hour=h, minute=mi2, second=0, microsecond=0)
                    fenster_start = spielbeginn - dt.timedelta(hours=1)
                    if now_at >= fenster_start:
                        return True
                except Exception:
                    return True
            else:
                return True

        # Spiel in der Zukunft → merken
        elif diff > 0:
            has_future = True

    # Keine heutigen Spiele aktiv, aber zukünftige vorhanden → laufen
    if has_future:
        return True

    # Alle Spiele vergangen → nicht mehr laufen
    return False


def main():
    if not should_run():
        print("Kein aktives Spiel und keine zukünftigen Spiele – kein Update nötig.")
        return

    # Nur relevante Spiele abrufen
    to_fetch = get_matches_to_fetch()
    to_fetch_ids = {m["meeting_id"] for m in to_fetch}
    print(f"Rufe {len(to_fetch_ids)} von {len(MATCHES)} Spielen ab.")

    # Gecachte Daten für nicht abgerufene Spiele laden
    cached_matches = {}
    try:
        with open("results.json", encoding="utf-8") as f:
            cached = json.load(f)
        for cm in cached.get("matches", []):
            cached_matches[cm["meeting_id"]] = cm
    except Exception:
        pass

    output = {"generated_at": datetime.now(timezone.utc).isoformat(), "matches": []}
    seen = set()

    for m in MATCHES:
        mid = m["meeting_id"]
        if mid in seen:
            continue
        seen.add(mid)

        if mid in to_fetch_ids:
            # Frisch abrufen
            print(f"  Lade meeting={mid} ...", end=" ", flush=True)
            data = process_match(mid, m.get("datum_override"))
            h = data.get("header", {})
            print(f"{data['status']} | {h.get('datum', '')} | {h.get('heim', '')} vs {h.get('gast', '')}")
        else:
            # Aus Cache nehmen
            if mid in cached_matches:
                data = cached_matches[mid]
                # datum_override auch auf Cache anwenden
                if m.get("datum_override"):
                    d = m["datum_override"].split(".")
                    data["header"]["datum"] = m["datum_override"]
                    data["header"]["datum_iso"] = f"{d[2]}-{d[1]}-{d[0]}"
                print(f"  Cache   meeting={mid} | {data.get('header', {}).get('datum', '')} | {data.get('status', '')}")
            else:
                # Noch nie abgerufen → trotzdem holen
                print(f"  Lade meeting={mid} (kein Cache) ...", end=" ", flush=True)
                data = process_match(mid, m.get("datum_override"))
                print(f"{data['status']}")

        output["matches"].append(data)

    output["matches"].sort(key=lambda x: x.get("header", {}).get("datum_iso", "9999"))
    with open("results.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nresults.json gespeichert – {len(output['matches'])} Spiele ✓")


if __name__ == "__main__":
    main()
    
