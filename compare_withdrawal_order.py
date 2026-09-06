"""
Does proactively filling a low tax bracket with extra traditional withdrawals
(bracket_fill), or pacing withdrawals to drain traditional by the longevity horizon
(pace_to_horizon), beat the simple sequential order (taxable -> traditional -> Roth)?
Tests all three withdrawal strategies against all four contribution-split scenarios.
"""

from engine import load_household, run_scenario, net_of_tax_wealth

INPUT = "inputs/household.json"
SCENARIOS = [
    ("100pct_roth", 1.00),
    ("75_25_roth_trad", 0.75),
    ("50_50_roth_trad", 0.50),
    ("100pct_traditional", 0.00),
]
STRATEGIES = [
    ("sequential", "sequential", {}),
    ("bracket_fill_12pct", "bracket_fill", {"bracket_fill_target_rate": 0.12}),
    ("bracket_fill_22pct", "bracket_fill", {"bracket_fill_target_rate": 0.22}),
    ("pace_to_horizon", "pace_to_horizon", {}),
]

if __name__ == "__main__":
    hh = load_household(INPUT)

    for strat_name, strategy, extra_kwargs in STRATEGIES:
        print(f"\n=== Withdrawal strategy: {strat_name} ===")
        results = []
        for name, roth_fraction in SCENARIOS:
            kwargs = {"withdrawal_strategy": strategy, **extra_kwargs}
            ledger, depleted_at = run_scenario(hh, roth_fraction, scenario_name=name, **kwargs)
            net_wealth, _ = net_of_tax_wealth(ledger[-1])
            lifetime_tax = sum(r["total_tax"] for r in ledger)
            roth_touched = any(r["withdrawal_roth"] > 0.01 for r in ledger)
            results.append((name, net_wealth, lifetime_tax, roth_touched, depleted_at))

        for name, net_wealth, lifetime_tax, roth_touched, depleted_at in sorted(
                results, key=lambda x: -x[1]):
            flag = " [ROTH TAPPED]" if roth_touched else ""
            shortfall = f" [SHORTFALL age {depleted_at}]" if depleted_at else ""
            print(f"  {name:22s}  net-of-tax ${net_wealth:>13,.0f}   "
                  f"lifetime tax ${lifetime_tax:>11,.0f}{flag}{shortfall}")
