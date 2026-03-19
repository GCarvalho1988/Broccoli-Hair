"""
Claude API calls for the weekly report.

draft_report_content() — single call that drafts updates, summaries, and upsell items.
generate_high_level_summary() — lightweight call: one-liner per deal from summaries only.
"""
import json, re
import anthropic
from config import ANTHROPIC_API_KEY, MODEL
from history import get_deal

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def draft_report_content(deals: list[dict], transcript: str,
                         portfolio_text: str, history: dict) -> dict:
    """
    Returns:
    {
      "deal_updates": [
        {
          "deal": str,           # matched to Smartsheet name
          "mentioned": bool,
          "update_lines": [str],
          "summary_action": "unchanged" | "updated" | "new",
          "summary_lines": [str]
        }
      ],
      "upsell_items": [str]
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

PORTFOLIO WEEKLY REPORT (for upsell items):
{portfolio_text[:3000]}

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
  ],
  "upsell_items": ["<item 1>", "<item 2>"]
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

4. UPSELL: Extract upsell opportunities from the Portfolio PDF and transcript. If none: [].
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


def generate_high_level_summary(deals: list[dict]) -> list[dict]:
    """
    Generate a one-liner per deal from its summary lines only.
    Input:   [{"deal", "stage", "stage_num", "summary_lines", "forecast"}]
    Returns: [{"deal", "stage", "stage_num", "one_liner", "forecast"}]
    """
    if not deals:
        return []

    deals_text = "\n\n".join(
        f'{d["deal"]}:\n' + "\n".join(
            f"  - {s}" for s in (d.get("summary_lines") or ["(no summary)"])
        )
        for d in deals
    )

    prompt = f"""You are helping write a weekly sales pipeline report for Sectra UK.

For each deal below, write ONE concise sentence describing the current pipeline status.
Base your answer ONLY on the summary provided. Do not add external information.
Be specific and direct. Use present tense. Do not start with the deal name.

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
                "one_liner": result_map.get(d["deal"].lower(), ""),
                "forecast":  d.get("forecast", ""),
            }
            for d in deals
        ]
    except (json.JSONDecodeError, KeyError):
        return [_hls_fallback(d) for d in deals]


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
        if entry and entry.get("summary_lines"):
            lines.append(f"\n{d['Opportunity']}:")
            for s in entry["summary_lines"]:
                lines.append(f"  - {s}")
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
            data.setdefault("deal_updates", []).append({
                "deal": d["Opportunity"],
                "mentioned": False,
                "update_lines": ["No update."],
                "summary_action": "unchanged",
                "summary_lines": entry.get("summary_lines", []) if entry else [],
            })

    return data


def _empty_result(deals: list[dict], history: dict) -> dict:
    updates = []
    for d in deals:
        entry = get_deal(d["Opportunity"], history)
        updates.append({
            "deal": d["Opportunity"],
            "mentioned": False,
            "update_lines": ["No update."],
            "summary_action": "unchanged",
            "summary_lines": entry.get("summary_lines", []) if entry else [],
        })
    return {"deal_updates": updates, "upsell_items": []}
