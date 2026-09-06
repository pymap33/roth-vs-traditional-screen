import csv
import os

from engine import load_household, run_scenario, net_of_tax_wealth

HERE = os.path.dirname(__file__)
INPUT = os.path.join(HERE, "inputs", "household.json")
OUTDIR = os.path.join(HERE, "output")

SCENARIOS = [
    ("100pct_roth_current_mix", 1.00, None),
    ("75_25_roth_trad", 0.75, None),
    ("50_50_roth_trad", 0.50, None),
    ("100pct_traditional", 0.00, None),
    ("current_mix_widow_stress_age80", 1.00, 80),
]

# Default withdrawal strategy for this comparison. Set to bracket-fill-to-12% as of
# 2026-09-05, since compare_withdrawal_order.py showed it beats plain "sequential" in
# every contribution-split scenario tested (see CLAUDE.md v3 section for the numbers).
# Re-run compare_withdrawal_order.py if this ever needs re-justifying.
WITHDRAWAL_STRATEGY = "bracket_fill"
BRACKET_FILL_TARGET_RATE = 0.12


def write_ledger(name, ledger):
    path = os.path.join(OUTDIR, f"{name}.csv")
    fieldnames = []
    for row in ledger:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(ledger)
    return path


def legacy_metrics(ledger):
    """
    Computes the two numbers a "spend it down" vs. "leave it to heirs" framing each
    care about most, so summarize() can headline whichever one the household says
    matters more - see household.legacyIntent and the CLAUDE.md discussion of why
    this is asked as a direct question rather than inferred.
    """
    decum = [r for r in ledger if r["phase"] == "decumulation"]
    total_roth_withdrawn = sum(r["withdrawal_roth"] for r in decum)
    roth_touch_age = next((r["age"] for r in decum if r["withdrawal_roth"] > 0.01), None)
    trad_and_taxable_exhausted_age = next(
        (r["age"] for r in decum if r["end_traditional"] <= 0.01 and r["end_taxable"] <= 0.01),
        None,
    )
    return {
        "total_roth_withdrawn": total_roth_withdrawn,
        "roth_touch_age": roth_touch_age,
        "trad_and_taxable_exhausted_age": trad_and_taxable_exhausted_age,
    }


def summarize(name, ledger, depleted_at, legacy_intent):
    lifetime_tax = sum(r["total_tax"] for r in ledger)
    final = ledger[-1]
    peak_marginal = max(r["marginal_federal_rate"] for r in ledger if r["phase"] == "decumulation")
    net_wealth, liq_rate = net_of_tax_wealth(final)
    lm = legacy_metrics(ledger)

    print(f"\n=== {name} ===")
    print(f"  Lifetime tax paid (real $, to age {final['age']}): ${lifetime_tax:,.0f}")
    print(f"  GROSS ending balance (real $): ${final['end_total']:,.0f}  "
          f"(trad {final['end_traditional']:,.0f} / roth {final['end_roth']:,.0f} / "
          f"taxable {final['end_taxable']:,.0f})")
    print(f"  NET-OF-TAX ending wealth (real $, ~{liq_rate:.0%} assumed rate on remaining "
          f"traditional): ${net_wealth:,.0f}")
    print(f"  Peak marginal federal bracket hit in retirement: {peak_marginal:.0%}")
    print(f"  Withdrawal strategy: {WITHDRAWAL_STRATEGY}"
          + (f" (target {BRACKET_FILL_TARGET_RATE:.0%})" if WITHDRAWAL_STRATEGY == "bracket_fill" else ""))
    if depleted_at:
        print(f"  [WARNING] SPENDING SHORTFALL starting age {depleted_at} — balances insufficient")

    # Legacy/spend-down framing - which line leads depends on the household's own
    # stated intent, not a default. "undetermined" shows both, deliberately, so the
    # question gets asked rather than answered for the user.
    if legacy_intent in ("spend-down", "balanced", "undetermined"):
        if lm["trad_and_taxable_exhausted_age"]:
            print(f"  [SPEND-DOWN VIEW] taxable + traditional exhausted by age "
                  f"{lm['trad_and_taxable_exhausted_age']} — from then on, spending "
                  f"relies entirely on Roth.")
        else:
            print(f"  [SPEND-DOWN VIEW] taxable + traditional last the full "
                  f"projection (never exhausted through age {final['age']}).")
    if legacy_intent in ("legacy", "balanced", "undetermined"):
        if lm["roth_touch_age"] is None:
            print(f"  [LEGACY VIEW] Roth balance (${final['end_roth']:,.0f}) was "
                  f"NEVER withdrawn from — it passes to heirs entirely tax-free, "
                  f"functioning as a de facto bequest rather than retirement income.")
        else:
            print(f"  [LEGACY VIEW] Roth first tapped at age {lm['roth_touch_age']}; "
                  f"${lm['total_roth_withdrawn']:,.0f} withdrawn from it over the "
                  f"projection, ${final['end_roth']:,.0f} remains at age {final['age']}.")

    return net_wealth


if __name__ == "__main__":
    os.makedirs(OUTDIR, exist_ok=True)
    hh = load_household(INPUT)

    if hh["retirementSpending"]["status"].startswith("provisional"):
        print("NOTE: retirement spending target is PROVISIONAL ($75,000/yr, user's own "
              "composite budget figure pending refinement) — treat output as directional.\n")

    legacy_intent = hh["household"].get("legacyIntent", "undetermined")
    if legacy_intent == "undetermined":
        print("NOTE: legacyIntent is undetermined - showing BOTH the spend-down view "
              "(how long money lasts / when Roth becomes the only source left) and "
              "the legacy view (what's left as a bequest). Answering \"is this money "
              "meant to be spent by us, or left to heirs?\" in household.json will "
              "make this output headline the one that matters to you.\n")

    results = []
    for name, roth_fraction, widow_age in SCENARIOS:
        ledger, depleted_at = run_scenario(hh, roth_fraction, widow_at_age=widow_age,
                                            scenario_name=name,
                                            withdrawal_strategy=WITHDRAWAL_STRATEGY,
                                            bracket_fill_target_rate=BRACKET_FILL_TARGET_RATE)
        path = write_ledger(name, ledger)
        net_wealth = summarize(name, ledger, depleted_at, legacy_intent)
        print(f"  Ledger written: {os.path.relpath(path, HERE)}")
        results.append((name, net_wealth))

    print("\n=== RANKED BY NET-OF-TAX ENDING WEALTH (highest first) ===")
    for name, net_wealth in sorted(results, key=lambda x: -x[1]):
        print(f"  {name}: ${net_wealth:,.0f}")
