"""
Sensitivity test: does the Roth-vs-traditional ranking survive a lower/higher real
return assumption, or was 5%/yr doing more work than it should?
"""

from engine import load_household, run_scenario, net_of_tax_wealth

INPUT = "inputs/household.json"
RETURN_RATES = [0.02, 0.03, 0.04, 0.05, 0.06]
SCENARIOS = [
    ("100pct_roth", 1.00),
    ("75_25_roth_trad", 0.75),
    ("50_50_roth_trad", 0.50),
    ("100pct_traditional", 0.00),
]

if __name__ == "__main__":
    hh = load_household(INPUT)

    for rate in RETURN_RATES:
        print(f"\n=== Real return assumption: {rate:.0%}/yr ===")
        results = []
        for name, roth_fraction in SCENARIOS:
            ledger, depleted_at = run_scenario(hh, roth_fraction, real_return=rate,
                                                scenario_name=name)
            final = ledger[-1]
            net_wealth, _ = net_of_tax_wealth(final)
            lifetime_tax = sum(r["total_tax"] for r in ledger)
            results.append((name, net_wealth, lifetime_tax))

        for name, net_wealth, lifetime_tax in sorted(results, key=lambda x: -x[1]):
            print(f"  {name:22s}  net-of-tax ${net_wealth:>13,.0f}   "
                  f"lifetime tax ${lifetime_tax:>11,.0f}")

        best = max(results, key=lambda x: x[1])
        worst_of_four = min(results, key=lambda x: x[1])
        spread = best[1] - worst_of_four[1]
        print(f"  Spread (best - worst): ${spread:,.0f}")
