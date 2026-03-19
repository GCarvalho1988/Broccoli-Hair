"""
Seed reports/history.json from all S&M Weekly Reports in uploads/S&M Weekly Reports/.

Processes every .docx file chronologically, extracting per-deal summaries and updates.
The most-recent data for each deal wins.  Run once (or re-run to refresh).

Usage:
    python seed_all_reports.py
"""
import os, re, glob
from datetime import date, datetime
from docx import Document
from history import load_history, save_history, update_deal, set_last_run_date

REPORTS_DIR = os.path.join(os.path.dirname(__file__),
                           "uploads", "S&M Weekly Reports")

MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "may": 5, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_SECTION_HEADERS = {
    "general updates", "high-level summary", "detailed updates",
    "other portfolio upsell", "other team updates", "summary", "update",
}


def _parse_date(filename: str) -> date | None:
    """Extract a date from filenames like 'SM WR 9th Jan.docx'."""
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)\s+([A-Za-z]+)", filename)
    if not m:
        return None
    day   = int(m.group(1))
    month = MONTH_MAP.get(m.group(2).lower()[:3])
    if not month:
        return None
    # All reports are 2026; adjust if needed
    year = 2026
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _is_bold(para) -> bool:
    return any(r.bold and r.text.strip() for r in para.runs)


def extract_deal_data(docx_path: str) -> dict[str, dict]:
    """
    Returns {deal_name: {"summary_lines": [...], "update_lines": [...]}}
    """
    doc = Document(docx_path)
    paragraphs = list(doc.paragraphs)

    # Find "Detailed Updates" section
    detailed_start = next(
        (i for i, p in enumerate(paragraphs)
         if re.search(r"detailed\s+updates", p.text, re.IGNORECASE)), None)
    if detailed_start is None:
        return {}

    section_end = next(
        (i for i in range(detailed_start + 1, len(paragraphs))
         if paragraphs[i].text.strip().lower().rstrip(":")
            in {"other portfolio upsell", "other team updates"}),
        len(paragraphs))

    deals: dict[str, dict] = {}
    current_deal = None
    collecting   = None   # "summary" | "update" | None
    sum_lines: list[str] = []
    upd_lines: list[str] = []

    def _flush():
        if current_deal:
            deals[current_deal] = {
                "summary_lines": sum_lines[:],
                "update_lines":  upd_lines[:],
            }

    for p in paragraphs[detailed_start + 1: section_end]:
        text = p.text.strip()
        if not text:
            continue

        # "Summary:" label
        if re.match(r"^summary\s*:", text, re.IGNORECASE) and not _is_bold(p):
            collecting = "summary"
            after = re.sub(r"^summary\s*:\s*", "", text, flags=re.IGNORECASE).strip()
            if after:
                sum_lines.append(after)
            continue

        # "Update:" label
        if re.match(r"^update\s*:", text, re.IGNORECASE) and not _is_bold(p):
            collecting = "update"
            after = re.sub(r"^update\s*:\s*", "", text, flags=re.IGNORECASE).strip()
            if after:
                upd_lines.append(after)
            continue

        # Bold short line = new deal heading
        if (_is_bold(p) and len(text) < 120
                and text.strip().lower().rstrip(":") not in _SECTION_HEADERS):
            _flush()
            current_deal = text
            sum_lines, upd_lines, collecting = [], [], None
            continue

        # Accumulate content
        if collecting == "summary" and current_deal:
            sum_lines.append(text)
        elif collecting == "update" and current_deal:
            upd_lines.append(text)

    _flush()
    return deals


def main():
    # Collect all .docx files under the reports directory
    pattern = os.path.join(REPORTS_DIR, "**", "*.docx")
    all_files = glob.glob(pattern, recursive=True)

    # Pair each file with its parsed date; skip undateable files
    dated = []
    for path in all_files:
        d = _parse_date(os.path.basename(path))
        if d:
            dated.append((d, path))
        else:
            print(f"  SKIP (no date): {os.path.basename(path)}")

    if not dated:
        print("No dateable report files found.")
        return

    # Process in chronological order so later data overwrites earlier
    dated.sort(key=lambda x: x[0])

    history = load_history()
    # Clear existing deal entries (keep _meta)
    for key in list(history.keys()):
        if key != "_meta":
            del history[key]

    total_deals = 0
    for report_date, path in dated:
        date_str = report_date.isoformat()
        fname    = os.path.basename(path)
        print(f"\n{date_str}  {fname}")

        deals = extract_deal_data(path)
        if not deals:
            print("  (no deal data found)")
            continue

        for name, data in deals.items():
            s_count = len(data["summary_lines"])
            u_count = len(data["update_lines"])
            update_deal(
                history, name,
                summary_lines=data["summary_lines"] if data["summary_lines"] else None,
                update_lines=data["update_lines"]   if data["update_lines"]  else None,
                discussed=bool(data["update_lines"]),
                report_date=date_str,
            )
            print(f"  {name!r:50s}  summary:{s_count}  update:{u_count}")
            total_deals += 1

    # Remove stray entries with no summary (bullet points mis-detected as headings)
    spurious = [k for k, v in history.items()
                if k != "_meta" and not v.get("summary_lines")]
    for k in spurious:
        del history[k]
    if spurious:
        print(f"\nCleaned {len(spurious)} spurious entries (no summary lines).")

    # Last report's date becomes last_run_date
    last_date = dated[-1][0].isoformat()
    set_last_run_date(history, last_date)
    save_history(history)

    real_deals = len(history) - 1
    print(f"\nDone — {real_deals} deals in history, seeded across {len(dated)} reports.")
    print(f"last_run_date = {last_date}")


if __name__ == "__main__":
    main()
