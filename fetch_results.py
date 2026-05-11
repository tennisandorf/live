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
    {"meeting_id": "1866859"},
    # Weitere IDs hier ergänzen:
    # {"meeting_id": "1860681"},
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
    if m:
        h["erfasst_datum"] = m.group(1)
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
    pattern = re.compile(
        r"^(\d+)\s+\d+\s+\d+\s+"
        r"([A-ZÄÖÜa-zäöüß,\.\s\-]+?)\s+(?:UKR\s+|GER\s+|CZE\s+|SVK\s+|HUN\s+)?ITN\s+([\d,]+)\s+"
        r"\d+\s+\d+\s+"
        r"([A-ZÄÖÜa-zäöüß,\.\s\-]+?)\s+(?:UKR\s+|GER\s+|CZE\s+|SVK\s+|HUN\s+)?(?:\(ret\.\)\s+)?ITN\s+([\d,]+)\s+"
        r"(\d+):(\d+)\s+(\d+):(\d+)\s+(\d+):(\d+)",
        re.MULTILINE
    )
    for match in pattern.finditer(block):
        s1h,s1g = int(match.group(6)),int(match.group(7))
        s2h,s2g = int(match.group(8)),int(match.group(9))
        s3h,s3g = int(match.group(10)),int(match.group(11))
        sets_heim = (1 if s1h>s1g else 0)+(1 if s2h>s2g else 0)+(1 if s3h>s3g else 0)
        singles.append({
            "nr": int(match.group(1)),
            "heim": match.group(2).strip().rstrip(","),
            "heim_itn": match.group(3).replace(",","."),
            "gast": match.group(4).strip().rstrip(","),
            "gast_itn": match.group(5).replace(",","."),
            "satz1": f"{s1h}:{s1g}",
            "satz2": f"{s2h}:{s2g}",
            "satz3": f"{s3h}:{s3g}" if not (s3h==0 and s3g==0) else "",
            "winner": "heim" if sets_heim>=2 else "gast",
        })
    return singles


def parse_doubles(text):
    doubles = []
    m = re.search(r"Doppel.*?erfasst.*?[\r\n](.*?)Doppel-Summe", text, re.DOTALL | re.IGNORECASE)
    if not m:
        return doubles
    block = m.group(1)
    name_pat = re.compile(r"([A-ZÄÖÜ][a-zäöüß\-]+,\s[A-ZÄÖÜa-zäöüß\s\-]+?)\s+(?:UKR\s+|GER\s+|CZE\s+|SVK\s+|HUN\s+)?ITN")
    all_names = [n.strip() for n in name_pat.findall(block)]
    sat_pat = re.compile(r"(\d+):(\d+)\s+(\d+):(\d+)\s+(\d+):(\d+)\s+(\d)\s+\d")
    for i, sm in enumerate(sat_pat.finditer(block), 1):
        s1h,s1g = int(sm.group(1)),int(sm.group(2))
        s2h,s2g = int(sm.group(3)),int(sm.group(4))
        s3h,s3g = int(sm.group(5)),int(sm.group(6))
        winner = "heim" if int(sm.group(7))==1 else "gast"
        offset = (i-1)*4
        heim = " / ".join(all_names[offset:offset+2]) if len(all_names)>=offset+2 else ""
        gast = " / ".join(all_names[offset+2:offset+4]) if len(all_names)>=offset+4 else ""
        doubles.append({
            "nr": i, "heim": heim, "gast": gast,
            "satz1": f"{s1h}:{s1g}", "satz2": f"{s2h}:{s2g}",
            "satz3": f"{s3h}:{s3g}" if not (s3h==0 and s3g==0) else "",
            "winner": winner,
        })
    return doubles


def process_match(meeting_id):
    result = {
        "meeting_id": meeting_id,
        "url": BASE_URL.format(meeting_id=meeting_id),
        "status": "error",
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "header": {}, "singles": [], "doubles": [],
    }
    try:
        text = fetch_text(meeting_id)
        result["header"] = parse_header(text)
        result["singles"] = parse_singles(text)
        result["doubles"] = parse_doubles(text)
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


def main():
    output = {"generated_at": datetime.now(timezone.utc).isoformat(), "matches": []}
    seen = set()
    for m in MATCHES:
        mid = m["meeting_id"]
        if mid in seen:
            continue
        seen.add(mid)
        print(f"  Lade meeting={mid} ...", end=" ", flush=True)
        data = process_match(mid)
        h = data.get("header", {})
        print(f"{data['status']} | {h.get('datum','')} | {h.get('heim','')} vs {h.get('gast','')}")
        output["matches"].append(data)
    output["matches"].sort(key=lambda x: x.get("header", {}).get("datum_iso", "9999"))
    with open("results.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nresults.json gespeichert – {len(output['matches'])} Spiele ✓")


if __name__ == "__main__":
    main()
