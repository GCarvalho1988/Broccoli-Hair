from history import load_history, should_include, update_deal, set_last_run_date

h = {"_meta": {"last_run_date": "2026-03-13"}}
# Simulate a deal that was in last report
h["newcastle"] = {"display_name": "Newcastle", "last_included_date": "2026-03-13"}

assert should_include("Newcastle", h, discussed=True)   == True,  "Discussed should always include"
assert should_include("Newcastle", h, discussed=False)  == True,  "In last report should include"
assert should_include("SWASH", h, discussed=False)      == False, "Never seen should exclude"

# Test update_deal
update_deal(h, "Newcastle", summary_lines=["Line 1"], discussed=True, report_date="2026-03-20")
assert h["newcastle"]["last_discussed_date"] == "2026-03-20"
assert h["newcastle"]["summary_lines"] == ["Line 1"]

print("history.py: all assertions passed")
