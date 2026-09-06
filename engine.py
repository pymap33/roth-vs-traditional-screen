"""
Projection engine for the Roth-vs-traditional contribution screen.

Everything is modeled in REAL (today's dollar) terms: wage income, spending, and tax
brackets are all held flat across the projection rather than carrying a separate
inflation track. See tax_tables.py docstring for why this is a reasonable
simplification for a directional screen.

Withdrawal order in retirement - two strategies, chosen via `withdrawal_strategy`:
- **"sequential" (v1 default):** RMD forced from traditional first; any additional
  spending need beyond the RMD is met taxable brokerage -> traditional -> Roth, in
  that order. "Spend the account you'd otherwise have to pay tax on soonest."
- **"bracket_fill" (v3):** on top of the forced RMD, PROACTIVELY withdraws additional
  traditional dollars up to the ceiling of `bracket_fill_target_rate` (e.g. 0.12 =
  top of the 12% federal bracket) even in years that don't need it for spending -
  banking the excess into taxable. The bet: paying a known, currently-low rate now on
  money that would otherwise sit and compound into a bigger, higher-bracket RMD later
  can beat waiting. Whether it actually beats "sequential" for a given household is
  exactly what this comparison is for - it is a strategy to test, not an assumed
  improvement. Simplification: the room calculation uses the RMD alone as "already
  counted" income, not the SS-taxability feedback loop (more traditional income can
  itself make more SS taxable) - close enough for a directional comparison, would need
  an iterative solve to get exactly right.
- **"pace_to_horizon" (v4):** the direct fix for the limitation bracket_fill's fixed
  target rate surfaced (the widow-anomaly investigation found no single fill rate is
  optimal across contribution splits - it depends on traditional balance size).
  Instead of targeting a fixed bracket ceiling, each year it PACES the traditional
  withdrawal toward draining the balance by `longevity_age`: target withdrawal =
  current traditional balance / years remaining (straight-line, recomputed fresh every
  year from the current balance and current years-remaining, so it self-corrects for
  actual growth/spending deviations rather than solving once at retirement). Takes
  whichever is larger, this paced amount or the forced RMD - RMD is still a floor, not
  a ceiling. Known simplification: straight-line division ignores that the balance
  still grows between now and next year's recompute, so realized depletion drifts
  slightly past `longevity_age` rather than landing exactly on it - re-solving every
  year keeps that drift small rather than letting it compound, but it is not an exact
  annuity/amortization solve. At the final modeled year (years remaining = 1), this
  reduces to "withdraw everything left," which is the intended behavior.

Social Security (v2): if `household.assumeZeroSocialSecurity` is false, an assumed
annual benefit starts at `socialSecurity.claimingAge` and reduces the withdrawal need
each year like any other income source. Its FEDERAL taxability follows the
provisional-income test in tax_tables.py; no state this tool supports taxes Social
Security, so it is never included in the state-tax base regardless of federal
treatment - the engine tracks separate federal vs. state ordinary-income figures for
this reason.

State taxation (v5, 2026-09-06): `household.state` (while working) and
`household.stateInRetirement` (may differ - e.g. a planned relocation) each select a
state whose rules apply for that phase. Unlike Wisconsin, which taxes wages and
retirement-account withdrawals identically, some states (Illinois so far) tax them
completely differently - Illinois exempts retirement withdrawals from state tax
entirely. So the engine tracks wage income and retirement-withdrawal income as
SEPARATE figures (`wage_income_state`/`retirement_withdrawal_state`) and hands both to
`tax_tables.state_tax()`/`state_marginal_rate()`, which dispatch to the selected
state's own rules - see tax_tables.py's module docstring and `STATE_TAX_FUNCS` for
which states are implemented. Requesting an unsupported state raises immediately
rather than silently defaulting to Wisconsin's rules.

Child tax credits, IRMAA, and ACA-subsidy interactions are NOT modeled - noted as
scope limits, not silent gaps.
"""

import json
import tax_tables


def load_household(path):
    with open(path) as f:
        return json.load(f)


def _solve_traditional_gross_up(target_net, base_fed_income, base_state_withdrawal,
                                 filing_status, state, available, age=0):
    """
    Finds the ADDITIONAL traditional withdrawal X (0 <= X <= available) whose
    AFTER-TAX proceeds equal target_net, given the ordinary income already in
    place (base_fed_income for federal; base_state_withdrawal as the
    retirement-withdrawal-income component for state) before X is added. After-tax
    proceeds are monotonically increasing in X regardless of whether the state is
    graduated (WI/SC), flat (IL/IN/MI), or exempts retirement withdrawals entirely
    (IL/FL) - solved via bisection rather than a closed form so it stays correct
    across all of those shapes without a state-specific formula. `age` is passed
    through for states whose deduction depends on it (SC) - unused by the rest.
    Returns (X, net_achieved) - net_achieved may be less than target_net if
    `available` isn't enough to cover it; the caller's existing remaining_need/
    depleted_at tracking handles that shortfall the same way it always has.
    """
    if available <= 0 or target_net <= 0:
        return 0.0, 0.0

    base_fed_tax = tax_tables.federal_tax(base_fed_income, filing_status)
    base_state_tax = tax_tables.state_tax(
        state, filing_status, wage_income=0.0, retirement_withdrawal_income=base_state_withdrawal, age=age)

    def net_at(x):
        fed_tax = tax_tables.federal_tax(base_fed_income + x, filing_status)
        state_tax = tax_tables.state_tax(
            state, filing_status, wage_income=0.0, retirement_withdrawal_income=base_state_withdrawal + x, age=age)
        return x - (fed_tax - base_fed_tax) - (state_tax - base_state_tax)

    if net_at(available) <= target_net:
        return available, net_at(available)

    lo, hi = 0.0, available
    for _ in range(40):
        mid = (lo + hi) / 2
        if net_at(mid) < target_net:
            lo = mid
        else:
            hi = mid
    return hi, net_at(hi)


def net_of_tax_wealth(final_row, ltcg_gain_fraction=0.60):
    """
    Gross end_total adds three pools that are NOT tax-equivalent: traditional dollars
    still owe ordinary income tax whenever withdrawn (by the owner or an heir), taxable
    dollars owe LTCG tax on their embedded-gain portion, Roth dollars owe nothing. This
    estimates what's actually spendable/inheritable net of that still-owed liability,
    using the final year's own marginal rate as the assumed future liquidation rate -
    a simplification (real liquidation may span years/brackets), not a precise number.
    Returns (net_wealth, liquidation_rate_used).
    """
    liquidation_rate = final_row["marginal_federal_rate"] + final_row["marginal_state_rate"]
    trad_net = final_row["end_traditional"] * (1 - liquidation_rate)
    taxable_net = final_row["end_taxable"] * (1 - ltcg_gain_fraction * tax_tables.LTCG_COMBINED_RATE)
    roth_net = final_row["end_roth"]
    return trad_net + taxable_net + roth_net, liquidation_rate


def run_scenario(hh, roth_fraction, real_return=0.05, ltcg_gain_fraction=0.6,
                  longevity_age=95, widow_at_age=None, scenario_name="",
                  withdrawal_strategy="sequential", bracket_fill_target_rate=0.12,
                  rmd_start_age=73):
    h = hh["household"]
    age = h["currentAge_primary"]
    retire_age = h["targetRetirementAge"]
    filing = h["filingStatus"]
    state_while_working = h.get("state", "WI")
    state_in_retirement = h.get("stateInRetirement", state_while_working)

    totals = hh["balances"]["totals"]
    trad = totals["traditional_all"]
    roth = totals["roth_all"]
    taxable = totals["taxable_all"]

    employee_contrib = hh["contributions_annual"]["roth401k_employee"]
    employer_contrib = hh["contributions_annual"]["employerMatchPlusBoost_preTax"]
    wage_base = hh["income"]["currentHouseholdTaxableIncomeApprox"]
    spending = hh["retirementSpending"]["annualSpendingTarget_todaysDollars"]

    ss_cfg = hh.get("socialSecurity", {})
    ss_enabled = not h.get("assumeZeroSocialSecurity", True)
    ss_annual_benefit = ss_cfg.get("estimatedAnnualBenefit_householdTotal_todaysDollars", 0) or 0
    ss_claiming_age = ss_cfg.get("claimingAge", 67)
    if ss_enabled and ss_claiming_age < retire_age:
        # Claiming SS while still working requires modeling the SS earnings test
        # (benefits withheld above an earnings threshold before full retirement age) -
        # not built. Clamping avoids silently paying SS during working years the
        # engine has no way to reduce correctly.
        ss_claiming_age = retire_age

    ledger = []
    depleted_at = None

    while age <= longevity_age:
        current_filing = "SINGLE" if (widow_at_age and age >= widow_at_age) else filing
        record = {"scenario": scenario_name, "age": age, "filingStatus": current_filing}

        rmd_amt = withdrawal_trad = withdrawal_roth = withdrawal_taxable = 0.0
        excess_rmd = 0.0

        if age < retire_age:
            roth_contrib = employee_contrib * roth_fraction
            trad_contrib = employee_contrib * (1 - roth_fraction) + employer_contrib
            trad += trad_contrib
            roth += roth_contrib
            ordinary_income_fed = max(0.0, wage_base - employee_contrib * (1 - roth_fraction))
            wage_income_state = ordinary_income_fed
            retirement_withdrawal_state = 0.0
            state_this_year = state_while_working
            ss_income = 0.0
            taxable_ss = 0.0
            record["phase"] = "accumulation"
        else:
            record["phase"] = "decumulation"
            divisor = tax_tables.rmd_divisor(age, rmd_start_age=rmd_start_age)
            if divisor:
                rmd_amt = trad / divisor
            ss_income = ss_annual_benefit if (ss_enabled and age >= ss_claiming_age) else 0.0

            additional_trad = 0.0
            available_beyond_rmd = max(0.0, trad - rmd_amt)
            if withdrawal_strategy == "bracket_fill":
                ceiling = tax_tables.bracket_ceiling_gross(bracket_fill_target_rate, current_filing)
                if ceiling is not None:
                    room = max(0.0, ceiling - rmd_amt)
                    additional_trad = min(room, available_beyond_rmd)
            elif withdrawal_strategy == "pace_to_horizon":
                years_remaining = max(1, longevity_age - age + 1)
                paced_amt = trad / years_remaining
                additional_trad = min(max(0.0, paced_amt - rmd_amt), available_beyond_rmd)

            # RMD (legally required) plus whatever the chosen strategy proactively
            # withdraws beyond it - neither is sized to meet spending. Compute the
            # actual AFTER-TAX cash these provide before deciding whether MORE
            # withdrawal is needed, or whether there's an after-tax EXCESS to
            # reinvest - a withdrawal that covers the gross spending figure isn't
            # the same as one that nets it after tax, which the pre-v5 version of
            # this engine conflated (a real gap, not a display issue - found
            # 2026-09-06 while testing the state-tax feature, but it affects every
            # state and every scenario, not just the state comparison).
            withdrawal_trad = rmd_amt + additional_trad
            # SS taxability depends on OTHER ordinary income - computed once here
            # from this base amount and held fixed through the rest of this year's
            # solve below (documented approximation: further traditional withdrawal
            # to cover remaining need could itself push more SS into being taxable,
            # an iterative feedback loop this tool doesn't chase, consistent with
            # the bracket-fill room calculation's existing same simplification).
            taxable_ss = tax_tables.taxable_social_security(ss_income, withdrawal_trad, current_filing)
            base_ordinary_fed = withdrawal_trad + taxable_ss
            base_fed_tax = tax_tables.federal_tax(base_ordinary_fed, current_filing)
            base_state_tax = tax_tables.state_tax(
                state_in_retirement, current_filing,
                wage_income=0.0, retirement_withdrawal_income=withdrawal_trad, age=age)
            base_after_tax_cash = (withdrawal_trad + ss_income) - base_fed_tax - base_state_tax

            remaining_need = max(0.0, spending - base_after_tax_cash)
            excess_after_tax = max(0.0, base_after_tax_cash - spending)

            # Cover any remaining need in the existing account-preference order
            # (taxable brokerage, then more traditional, then Roth), GROSSING UP
            # each source so the withdrawal actually NETS the dollars still needed
            # after its own tax, rather than just matching the gross shortfall.
            ltcg_rate_effective = ltcg_gain_fraction * tax_tables.LTCG_COMBINED_RATE
            withdrawal_taxable = 0.0
            if remaining_need > 0 and taxable > 0:
                gross_needed = remaining_need / (1 - ltcg_rate_effective)
                withdrawal_taxable = min(gross_needed, taxable)
                remaining_need -= withdrawal_taxable * (1 - ltcg_rate_effective)

            available_extra_trad = max(0.0, trad - withdrawal_trad)
            if remaining_need > 0 and available_extra_trad > 0:
                extra_trad, net_from_extra_trad = _solve_traditional_gross_up(
                    target_net=remaining_need,
                    base_fed_income=base_ordinary_fed,
                    base_state_withdrawal=withdrawal_trad,
                    filing_status=current_filing,
                    state=state_in_retirement,
                    available=available_extra_trad,
                    age=age,
                )
                withdrawal_trad += extra_trad
                remaining_need -= net_from_extra_trad

            withdrawal_roth = 0.0
            if remaining_need > 0:
                withdrawal_roth = min(remaining_need, roth)
                remaining_need -= withdrawal_roth

            if remaining_need > 0.01 and depleted_at is None:
                depleted_at = age
            record["spending_shortfall"] = round(remaining_need, 2)

            trad -= withdrawal_trad
            roth -= withdrawal_roth
            taxable -= withdrawal_taxable

            # Recompute final ordinary income now that withdrawal_trad may have
            # grown beyond the base (extra_trad added above). taxable_ss is NOT
            # recomputed - see the documented approximation above.
            ordinary_income_fed = withdrawal_trad + taxable_ss
            wage_income_state = 0.0
            retirement_withdrawal_state = withdrawal_trad
            state_this_year = state_in_retirement
            # Already net-of-tax (computed from exact base_fed_tax/base_state_tax
            # above) - reinvested directly below, no approximation needed.
            excess_rmd = excess_after_tax

        fed_tax = tax_tables.federal_tax(ordinary_income_fed, current_filing)
        state_tax_amt = tax_tables.state_tax(
            state_this_year, current_filing,
            wage_income=wage_income_state, retirement_withdrawal_income=retirement_withdrawal_state, age=age)
        ltcg_tax = withdrawal_taxable * ltcg_gain_fraction * tax_tables.LTCG_COMBINED_RATE
        marginal_fed = tax_tables.federal_marginal_rate(ordinary_income_fed, current_filing)
        marginal_state = tax_tables.state_marginal_rate(
            state_this_year, current_filing,
            wage_income=wage_income_state, retirement_withdrawal_income=retirement_withdrawal_state, age=age)
        total_tax = fed_tax + state_tax_amt + ltcg_tax

        if excess_rmd > 0:
            taxable += excess_rmd

        trad = max(0.0, trad) * (1 + real_return)
        roth = max(0.0, roth) * (1 + real_return)
        taxable = max(0.0, taxable) * (1 + real_return)

        record.update({
            "state": state_this_year,
            "ordinary_income_federal": round(ordinary_income_fed, 2),
            "ordinary_income_state": round(wage_income_state + retirement_withdrawal_state, 2),
            "ss_income": round(ss_income, 2),
            "taxable_ss": round(taxable_ss, 2),
            "withdrawal_traditional": round(withdrawal_trad, 2),
            "withdrawal_roth": round(withdrawal_roth, 2),
            "withdrawal_taxable": round(withdrawal_taxable, 2),
            "rmd_amount": round(rmd_amt, 2),
            "federal_tax": round(fed_tax, 2),
            "state_tax": round(state_tax_amt, 2),
            "ltcg_tax": round(ltcg_tax, 2),
            "total_tax": round(total_tax, 2),
            "marginal_federal_rate": marginal_fed,
            "marginal_state_rate": marginal_state,
            "end_traditional": round(trad, 2),
            "end_roth": round(roth, 2),
            "end_taxable": round(taxable, 2),
            "end_total": round(trad + roth + taxable, 2),
        })
        ledger.append(record)
        age += 1

    return ledger, depleted_at
