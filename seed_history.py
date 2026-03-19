"""
One-time script: parse SM WR 06th Mar.docx and seed reports/history.json.
Run once: python seed_history.py
"""
import os, re
from docx import Document
from history import load_history, save_history, update_deal, set_last_run_date

REPORT_PATH = os.path.join(os.path.dirname(__file__), "SM WR 06th Mar.docx")
REPORT_DATE = "2026-03-06"

_SECTION_HEADERS = {
    "general updates:", "high-level summary:", "detailed updates:",
    "other portfolio upsell", "other team updates", "summary:", "update:",
}


def _is_bold(para):
    return any(r.bold and r.text.strip() for r in para.runs)


def extract_summaries(docx_path):
    doc = Document(docx_path)
    paragraphs = list(doc.paragraphs)

    detailed_start = next(
        (i for i, p in enumerate(paragraphs)
         if re.search(r"detailed updates", p.text, re.IGNORECASE)), None)
    if detailed_start is None:
        return {}

    section_end = next(
        (i for i in range(detailed_start + 1, len(paragraphs))
         if paragraphs[i].text.strip().lower() in
            {"other portfolio upsell", "other team updates"}),
        len(paragraphs))

    summaries, current_deal, collecting, lines = {}, None, None, []

    for p in paragraphs[detailed_start + 1: section_end]:
        text = p.text.strip()
        if not text:
            continue
        if re.match(r"^summary\s*:", text, re.IGNORECASE) and not _is_bold(p):
            collecting = "summary"
            after = re.sub(r"^summary\s*:\s*", "", text, flags=re.IGNORECASE).strip()
            if after:
                lines.append(after)
            continue
        if re.match(r"^update\s*:", text, re.IGNORECASE) and not _is_bold(p):
            collecting = "update"
            continue
        if (_is_bold(p) and len(text) < 100
                and text.strip().lower().rstrip(":") not in
                {h.rstrip(":") for h in _SECTION_HEADERS}):
            if current_deal and lines:
                summaries[current_deal] = lines[:]
            current_deal, lines, collecting = text, [], None
            continue
        if collecting == "summary" and current_deal:
            lines.append(text)

    if current_deal and lines:
        summaries[current_deal] = lines[:]
    return summaries


def main():
    print(f"Parsing {REPORT_PATH} ...")
    summaries = extract_summaries(REPORT_PATH)
    if not summaries:
        print("No summaries found.")
        return

    history = load_history()
    for name, lines in summaries.items():
        update_deal(history, name, summary_lines=lines,
                    report_date=REPORT_DATE)
        print(f"  Seeded: {name!r} ({len(lines)} lines)")

    set_last_run_date(history, REPORT_DATE)
    save_history(history)
    print(f"\nDone — {len(summaries)} deals seeded, last_run_date={REPORT_DATE}")


if __name__ == "__main__":
    main()
