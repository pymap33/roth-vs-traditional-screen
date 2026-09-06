"""
Sensitivity test: how much does the zero-SS planning stance actually matter to the
Roth-vs-traditional ranking? Does NOT change inputs/household.json (that file keeps
the household's real, durable zero-SS stance) - this script overrides it in memory
only, to answer "what if SS does show up" without touching the planning position.
"""

from engine import load_household, run_scenario, net_of_tax_wealth

INPUT = "inputs/household.json"
BENEFIT_LEVELS = [0, 30_000, 40_000, 50_000]
SCENARIOS = [
    ("100pct_roth", 1.00),
    ("75_25_roth_trad", 0.75),
    ("50_50_roth_trad", 0.50),
    ("100pct_traditional", 0.00),
]

if __name__ == "__main__":
    hh = load_household(INPUT)
    retire_age = hh["household"]["targetRetirementAge"]

    for benefit in BENEFIT_LEVELS:
        hh["household"]["assumeZeroSocialSecurity"] = (benefit == 0)
        hh["socialSecurity"]["estimatedAnnualBenefit_householdTotal_todaysDollars"] = benefit
        hh["socialSecurity"]["claimingAge"] = retire_age  # claimed at retirement - see engine.py clamp note

        print(f"\n=== Assumed household SS benefit: ${benefit:,}/yr (claimed at age {retire_age}) ===")
        results = []
        for name, roth_fraction in SCENARIOS:
            ledger, _ = run_scenario(hh, roth_fraction, scenario_name=name)
            net_wealth, _ = net_of_tax_wealth(ledger[-1])
            lifetime_tax = sum(r["total_tax"] for r in ledger)
            results.append((name, net_wealth, lifetime_tax))

        for name, net_wealth, lifetime_tax in sorted(results, key=lambda x: -x[1]):
            print(f"  {name:22s}  net-of-tax ${net_wealth:>13,.0f}   "
                  f"lifetime tax ${lifetime_tax:>11,.0f}")

        best, worst = max(results, key=lambda x: x[1]), min(results, key=lambda x: x[1])
        print(f"  Spread (best - worst): ${best[1] - worst[1]:,.0f}")
