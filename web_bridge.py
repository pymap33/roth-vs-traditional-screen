"""
Browser-only orchestration layer for the Pyodide harness (index.html/app.js).

Deliberately thin: every line of actual tax/RMD/withdrawal logic lives in
engine.py and tax_tables.py, which this module imports and calls unchanged.
This file exists only to (a) accept a JSON string from JS, (b) call
engine.run_scenario() once per contribution-split scenario, and (c) shape the
results back into JSON/CSV for the page, so the JS side never has to know
Python data structures. Adding logic here that isn't pure orchestration would
recreate the exact "second implementation to drift out of sync" problem this
whole Pyodide approach was chosen to avoid - see CLAUDE.md in the KB copy of
this project ("Delivery format decision") for that reasoning.
"""

import csv
import io
import json

import engine

FIXED_SCENARIOS = [
    ("100% Roth", 1.00),
    ("75% Roth / 25% Traditional", 0.75),
    ("50% Roth / 50% Traditional", 0.50),
    ("25% Roth / 75% Traditional", 0.25),
    ("100% Traditional", 0.00),
]

# Populated fresh by every run_all_scenarios() call: scenario name -> full ledger
# (list of per-year dicts). Kept so the chart and CSV-export features can pull a
# specific scenario's year-by-year detail without re-running the engine - the
# summary numbers returned to JS are a small slice of this, not a duplicate of it.
_LAST_LEDGERS = {}


def _to_optional_int(value):
    """
    Converts a value that may be a real number, a numeric string, Python None, an
    empty string, or (for JS `null` specifically) a Pyodide JsNull proxy that is
    not and does not equal Python None - into an int or None. Used for any
    optional integer field coming from the browser form.
    """
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return None if result == 0 else result


def run_all_scenarios(household_json, real_return, withdrawal_strategy,
                       bracket_fill_target_rate, longevity_age, widow_at_age,
                       rmd_start_age=73, custom_traditional_pct=None):
    """
    Runs the five fixed contribution-split scenarios, plus one custom split if
    custom_traditional_pct is given (0-100, share going to traditional), against
    one household + one set of engine-level assumptions. Returns a JSON string
    (a list of summary dicts) - the browser side never touches a Python object
    directly. Full ledgers are cached in _LAST_LEDGERS for get_ledger_csv/
    get_ledger_json to pull from afterward.
    """
    hh = json.loads(household_json)
    widow_age = _to_optional_int(widow_at_age)
    rmd_age = _to_optional_int(rmd_start_age) or 73

    scenarios = list(FIXED_SCENARIOS)
    custom_pct = _to_optional_int(custom_traditional_pct)
    if custom_pct is not None and 0 <= custom_pct <= 100:
        scenarios.append((f"Custom: {custom_pct}% Traditional", 1 - custom_pct / 100))

    _LAST_LEDGERS.clear()
    results = []
    for name, roth_fraction in scenarios:
        ledger, depleted_at = engine.run_scenario(
            hh, roth_fraction,
            real_return=real_return,
            longevity_age=longevity_age,
            widow_at_age=widow_age,
            scenario_name=name,
            withdrawal_strategy=withdrawal_strategy,
            bracket_fill_target_rate=bracket_fill_target_rate,
            rmd_start_age=rmd_age,
        )
        _LAST_LEDGERS[name] = ledger

        final_row = ledger[-1]
        net_wealth, liquidation_rate = engine.net_of_tax_wealth(final_row)
        lifetime_tax = sum(r["total_tax"] for r in ledger)
        peak_bracket = max(r["marginal_federal_rate"] for r in ledger)
        roth_touched = any(r["withdrawal_roth"] > 0.01 for r in ledger)
        roth_never_touched_balance = final_row["end_roth"] if not roth_touched else 0.0

        results.append({
            "name": name,
            "roth_fraction": roth_fraction,
            "lifetime_tax": round(lifetime_tax, 2),
            "net_of_tax_wealth": round(net_wealth, 2),
            "gross_ending_total": final_row["end_total"],
            "end_traditional": final_row["end_traditional"],
            "end_roth": final_row["end_roth"],
            "end_taxable": final_row["end_taxable"],
            "peak_marginal_federal_bracket": peak_bracket,
            "depleted_at_age": depleted_at,
            "roth_touched": roth_touched,
            "roth_bequest_if_untouched": roth_never_touched_balance,
        })

    results.sort(key=lambda r: -r["net_of_tax_wealth"])
    return json.dumps(results)


def get_ledger_json(scenario_name):
    """Full per-year ledger for one scenario from the last run_all_scenarios() call."""
    return json.dumps(_LAST_LEDGERS.get(scenario_name, []))


def get_ledger_csv(scenario_name):
    """
    Same fieldnames-union + DictWriter approach run_scenarios.py uses for its CSV
    output, just written to an in-memory buffer instead of a file so the browser
    can offer it as a download.
    """
    ledger = _LAST_LEDGERS.get(scenario_name, [])
    if not ledger:
        return ""
    fieldnames = []
    for row in ledger:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(ledger)
    return buf.getvalue()


def list_scenario_names():
    return json.dumps(list(_LAST_LEDGERS.keys()))
