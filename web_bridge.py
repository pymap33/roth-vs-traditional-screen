"""
Browser-only orchestration layer for the Pyodide harness (index.html/app.js).

Deliberately thin: every line of actual tax/RMD/withdrawal logic lives in
engine.py and tax_tables.py, which this module imports and calls unchanged.
This file exists only to (a) accept a JSON string from JS, (b) call
engine.run_scenario() once per contribution-split scenario, and (c) shape the
results back into a JSON-serializable list, so the JS side never has to know
Python data structures. Adding logic here that isn't pure orchestration would
recreate the exact "second implementation to drift out of sync" problem this
whole Pyodide approach was chosen to avoid - see CLAUDE.md in the KB copy of
this project ("Delivery format decision") for that reasoning.
"""

import json
import engine

SCENARIOS = [
    ("100% Roth", 1.00),
    ("75% Roth / 25% Traditional", 0.75),
    ("50% Roth / 50% Traditional", 0.50),
    ("25% Roth / 75% Traditional", 0.25),
    ("100% Traditional", 0.00),
]


def run_all_scenarios(household_json, real_return, withdrawal_strategy,
                       bracket_fill_target_rate, longevity_age, widow_at_age):
    """
    Runs every scenario in SCENARIOS against one household + one set of
    engine-level assumptions, and returns a JSON string (a list of dicts) -
    the browser side never touches a Python object directly, only this JSON.
    """
    hh = json.loads(household_json)
    widow_age = int(widow_at_age) if widow_at_age not in (None, "", 0) else None

    results = []
    for name, roth_fraction in SCENARIOS:
        ledger, depleted_at = engine.run_scenario(
            hh, roth_fraction,
            real_return=real_return,
            longevity_age=longevity_age,
            widow_at_age=widow_age,
            scenario_name=name,
            withdrawal_strategy=withdrawal_strategy,
            bracket_fill_target_rate=bracket_fill_target_rate,
        )
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
