"""
Claude API calls for the weekly report.

draft_updates_from_transcript() — AI drafts deal updates from a transcript.
extract_upsell_items()           — AI extracts upsell items from a portfolio PDF.
update_summaries_from_updates()  — AI merges new update text into existing summaries.
generate_high_level_summary()    — One-liner per deal, used at PDF generation time.
"""
import json, re
import anthropic
from config import ANTHROPIC_API_KEY, MODEL
from history import get_deal

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def _html_to_text(html: str) -> str:
    """Strip HTML, preserving block boundaries as newlines.

    Quill emits empty paragraphs as <p><br></p>, which produces two newlines
    (one from <br>, one from </p>). The \\n{3,} collapse fires for 3+, so
    empty paragraphs appear as blank lines. This is intentional.
    """
    text = re.sub(r'</p>|</li>|<br\s*/?>', '\n', html or '', flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text


def _lines_to_html(lines: list[str]) -> str:
    """Wrap plain text lines in <p> tags."""
    return ''.join(f'<p>{line}</p>' for line in lines if line.strip())


# ─── 1. Draft updates from transcript ────────────────────────────────────────

def draft_updates_from_transcript(deals: list[dict], transcript: str,
                                   history: dict) -> dict:
    """
    Returns:
    {
      "deal_updates": [
        {
          "deal": str,
          "mentioned": bool,
          "update_lines": [str],
          "summary_action": "unchanged" | "updated" | "new",
          "summary_lines": [str]
        }
      ]
    }
    """
    deals_text = _format_deals(deals, history)
    existing_summaries = _format_summaries(deals, history)

    prompt = f"""You are helping a Sales Manager at Sectra (UK medical imaging software) write a weekly sales report.

ACTIVE DEALS IN SMARTSHEET (in pipeline order):
{deals_text}

EXISTING DEAL SUMMARIES (from previous reports):
{existing_summaries}

MEETING TRANSCRIPT (Teams auto-generated — may use abbreviations or informal names):
{transcript[:8000]}

---

TASK: Produce a JSON response with exactly this structure (no markdown, no extra text — raw JSON only):

{{
  "deal_updates": [
    {{
      "deal": "<exact Smartsheet deal name>",
      "mentioned": <true|false>,
      "update_lines": ["<bullet 1>", "<bullet 2>"],
      "summary_action": "<unchanged|updated|new>",
      "summary_lines": ["<line 1>", "<line 2>", "..."]
    }}
  ]
}}

RULES:
1. DEAL NAME MATCHING: Map every transcript mention to the exact Smartsheet deal name.
   The meeting follows Smartsheet pipeline order — use this to resolve abbreviations.
   Examples: NCL → North Central London (Radiology), Barts → Barts Health, NENC → North East and North Cumbria Digital Pathology.

2. DEAL UPDATES: Include ALL active deals, not just mentioned ones.
   - If mentioned: write 1–2 concise bullet points summarising the discussion. No fluff.
   - If not mentioned: set mentioned=false, update_lines=["No update."]
   - Do not use markdown bold (**). Do not repeat the deal name in the update text.

3. SUMMARY LINES: Each deal needs a summary covering: customer background, sites covered,
   current vendors, deal value, and key events to date — in bullet-point format.
   - summary_action="unchanged": existing summary is fine, return it as-is
   - summary_action="updated": there is significant new info — return the full updated summary
   - summary_action="new": no existing summary — draft one from Smartsheet data and transcript.
     If you have very little data, draft what you can and flag the first line as "[AI DRAFT — please review]"

4. PRESERVE DETAILS: Never remove or overwrite specific factual details already in the existing summary.
   This includes: NHS trust/ICB/CCG/board names, number of sites, current incumbent vendors,
   deal values and contract periods, key dates, clinical/pathology context, geography.
   If there is new information, ADD it. Summaries should grow and improve, never shrink or lose facts.
"""

    message = client.messages.create(
        model=MODEL,
        max_tokens=10000,
        messages=[{"role": "user", "content": prompt}]
    )

    if not message.content:
        print("Empty response from AI")
        return _empty_result(deals, history)
    raw = message.content[0].text
    return _parse_response(raw, deals, history)


# ─── 2. Extract upsell items from portfolio PDF ───────────────────────────────

def extract_upsell_items(portfolio_text: str) -> list[str]:
    """
    Parse each portfolio's 'Sales Opportunities' section from the full PDF text,
    then ask AI to produce a 1-2 sentence summary per portfolio.
    Returns a list of "Portfolio Name – summary" strings, or [] if none found.
    """
    if not portfolio_text.strip():
        return []

    # ── Parse per-portfolio Sales Opportunities sections ──────────────────────
    # Header format: "CO UK Weekly Report - Benton Eir Portfolio (1) - Report"
    header_re = re.compile(r'CO UK Weekly Report\s*-\s*(.+?)\s*Portfolio', re.IGNORECASE)
    sales_re  = re.compile(r'Sales Opportunities:\s*\n(.*?)(?=Submitted by:|$)', re.DOTALL | re.IGNORECASE)

    headers = list(header_re.finditer(portfolio_text))
    portfolio_opps = []

    for i, match in enumerate(headers):
        name = match.group(1).strip()
        start = match.start()
        end   = headers[i + 1].start() if i + 1 < len(headers) else len(portfolio_text)
        section = portfolio_text[start:end]

        sales_match = sales_re.search(section)
        if not sales_match:
            continue
        opps = sales_match.group(1).strip()
        if opps.lower() in ("none", "n/a", ""):
            continue
        portfolio_opps.append({"portfolio": name, "opportunities": opps})

    if not portfolio_opps:
        return []

    # ── Ask AI to summarise each portfolio in 1-2 sentences ───────────────────
    blocks = ""
    for p in portfolio_opps:
        blocks += f"\n\n[{p['portfolio']}]\n{p['opportunities']}"

    prompt = f"""You are summarising sales opportunities for a UK medical imaging software sales team (Sectra UK&I).

For each portfolio below, write one concise sentence (two at most) capturing the key opportunity.
Omit portfolios with nothing material. If none, return [].

{blocks}

Respond with raw JSON only — a list of strings, one per portfolio (no markdown):
["<Portfolio Name> – <summary>", ...]"""

    message = client.messages.create(
        model=MODEL,
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}]
    )

    if not message.content:
        return []
    raw = message.content[0].text
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw)
    try:
        result = json.loads(raw)
        return result if isinstance(result, list) else []
    except json.JSONDecodeError:
        print(f"extract_upsell_items: invalid JSON: {raw[:200]}")
        return []


# ─── 3. Update summaries from written updates ─────────────────────────────────

def update_summaries_from_updates(deals: list[dict]) -> dict[str, list[str]]:
    """
    For each deal with new update_lines, merge them into the existing summary.

    Input:  [{"deal": str, "existing_summary_lines": [str], "update_lines": [str]}]
    Returns: {"deal name": [updated_summary_lines], ...}

    Deals not present in the input are not returned (caller only passes deals with updates).
    Returns {} on error — caller falls back to existing summaries.
    """
    if not deals:
        return {}

    deals_block = ""
    for d in deals:
        deals_block += f"\n\n=== {d['deal']} ===\n"
        deals_block += "EXISTING SUMMARY:\n"
        for line in d["existing_summary_lines"]:
            deals_block += f"  - {line}\n"
        deals_block += "NEW UPDATE THIS WEEK:\n"
        for line in d["update_lines"]:
            deals_block += f"  - {line}\n"

    prompt = f"""You are updating deal summaries for a UK medical imaging software sales pipeline (Sectra UK&I).

For each deal below, produce an updated summary by merging the NEW UPDATE into the EXISTING SUMMARY.

RULES:
1. PRESERVE all existing factual details: NHS trust/ICB/CCG/board names, number of sites,
   current incumbent vendors, deal values and contract periods, key dates, clinical/pathology
   context, geography, stage history. Never remove or overwrite these facts.
2. ADD information from the new update. If the update is already captured in the summary,
   return the summary unchanged.
3. Summaries must be a bullet-point list of concise factual statements.
4. Do not add padding or repetition. Summaries should grow in accuracy, not length.
{deals_block}

Respond with raw JSON only (no markdown):
{{
  "<exact deal name>": ["updated bullet 1", "updated bullet 2", ...],
  ...
}}"""

    message = client.messages.create(
        model=MODEL,
        max_tokens=6000,
        messages=[{"role": "user", "content": prompt}]
    )

    if not message.content:
        return {}
    raw = message.content[0].text
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw)
    try:
        result = json.loads(raw)
        return {k: v for k, v in result.items() if isinstance(v, list)}
    except json.JSONDecodeError:
        print(f"update_summaries_from_updates: invalid JSON: {raw[:200]}")
        return {}


# ─── 4. High-level summary (unchanged) ───────────────────────────────────────

def generate_high_level_summary(deals: list[dict]) -> list[dict]:
    """
    Generate a one-liner per deal from its summary and update lines.
    Input:   [{"deal", "stage", "stage_num", "summary_lines", "update_lines", "forecast"}]
    Returns: [{"deal", "stage", "stage_num", "one_liner", "forecast"}]
    """
    if not deals:
        return []

    deals_text = "\n\n".join(
        f'{d["deal"]}:\n'
        + (
            "  UPDATE THIS WEEK:\n" + "\n".join(
                f"    - {u}" for u in d.get("update_lines") or []
                if u.strip() and u.strip() != "No update."
            ) + "\n"
            if any(u.strip() and u.strip() != "No update."
                   for u in (d.get("update_lines") or []))
            else ""
        )
        + "  BACKGROUND SUMMARY:\n"
        + "\n".join(
            f"    - {s}" for s in (d.get("summary_lines") or ["(no summary)"])
        )
        for d in deals
    )

    prompt = f"""You are helping write a weekly sales pipeline report for Sectra UK.

For each deal below, write ONE concise sentence describing the current pipeline status.
If an UPDATE THIS WEEK is provided, base the status predominantly on that.
Otherwise use the BACKGROUND SUMMARY.
Be specific and direct. Use present tense. Do not start with the deal name.
Do not add external information.

{deals_text}

Respond with raw JSON only — no markdown, no extra text:
[
  {{"deal": "<exact deal name>", "one_liner": "<one sentence>"}},
  ...
]"""

    message = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    if not message.content:
        return [_hls_fallback(d) for d in deals]

    raw = message.content[0].text
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw)

    try:
        items = json.loads(raw)
        result_map = {item["deal"].lower(): item["one_liner"]
                      for item in items if "deal" in item}
        return [
            {
                "deal":      d["deal"],
                "stage":     d.get("stage", ""),
                "stage_num": d.get("stage_num", "0"),
                "one_liner": result_map.get(d["deal"].lower())
                             or _hls_fallback(d)["one_liner"],
                "forecast":  d.get("forecast", ""),
            }
            for d in deals
        ]
    except (json.JSONDecodeError, KeyError):
        return [_hls_fallback(d) for d in deals]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _hls_fallback(d: dict) -> dict:
    lines = d.get("summary_lines") or []
    return {
        "deal":      d["deal"],
        "stage":     d.get("stage", ""),
        "stage_num": d.get("stage_num", "0"),
        "one_liner": lines[0] if lines else "",
        "forecast":  d.get("forecast", ""),
    }


def _format_deals(deals: list[dict], history: dict) -> str:
    lines = []
    for d in deals:
        fit  = d.get("Strategic Fit", "?")
        prof = d.get("Profitability", "?")
        lines.append(
            f"- {d['Opportunity']} | Stage: {d['Sales Stage']} | "
            f"£{d.get('Forecast Amount', 'N/A')} | Rep: {d.get('Sales Rep', '')} | "
            f"Fit: {fit} | Profit: {prof} | Next: {d.get('Next Step', '')}"
        )
    return "\n".join(lines)


def _format_summaries(deals: list[dict], history: dict) -> str:
    lines = []
    for d in deals:
        entry = get_deal(d["Opportunity"], history)
        summary_text = _html_to_text(entry.get("summary_html", "")) if entry else ""
        if summary_text.strip():
            lines.append(f"\n{d['Opportunity']}:")
            for s in summary_text.split('\n'):
                if s.strip():
                    lines.append(f"  - {s.strip()}")
        else:
            lines.append(f"\n{d['Opportunity']}: (no summary on record)")
    return "\n".join(lines)


def _parse_response(raw: str, deals: list[dict], history: dict) -> dict:
    """Parse the JSON response, falling back gracefully on errors."""
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print(f"AI response was not valid JSON:\n{raw[:500]}")
        return _empty_result(deals, history)

    # Ensure every active deal has an entry
    existing = {item["deal"].lower(): item for item in data.get("deal_updates", [])}
    for d in deals:
        if d["Opportunity"].lower() not in existing:
            entry = get_deal(d["Opportunity"], history)
            summary_lines = (
                [l for l in _html_to_text(entry.get("summary_html", "")).splitlines() if l.strip()]
                if entry else []
            )
            data.setdefault("deal_updates", []).append({
                "deal": d["Opportunity"],
                "mentioned": False,
                "update_lines": ["No update."],
                "summary_action": "unchanged",
                "summary_lines": summary_lines,
            })

    return data


def _empty_result(deals: list[dict], history: dict) -> dict:
    updates = []
    for d in deals:
        entry = get_deal(d["Opportunity"], history)
        summary_lines = (
            [l for l in _html_to_text(entry.get("summary_html", "")).splitlines() if l.strip()]
            if entry else []
        )
        updates.append({
            "deal": d["Opportunity"],
            "mentioned": False,
            "update_lines": ["No update."],
            "summary_action": "unchanged",
            "summary_lines": summary_lines,
        })
    return {"deal_updates": updates}
