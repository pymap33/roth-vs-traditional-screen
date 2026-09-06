"""
Tax bracket / deduction lookup tables, isolated from engine logic so this is the
easy-to-inspect, easy-to-correct piece.

All figures are held constant in REAL (today's dollar) terms for the life of the
projection. This is a standard simplifying technique: brackets are inflation-indexed
in nominal terms, so modeling everything in real dollars against fixed real brackets
approximates that indexing without carrying a separate nominal/inflation track
through the engine.

CONFIDENCE (federal checked 2026-09-05 against known law; WI verified 2026-09-05
against live WI DOR Form 1 2025 instructions, read directly off the PDF by the user):
- FEDERAL brackets + standard deduction: HIGH CONFIDENCE. These match the 2025
  post-OBBBA figures (One Big Beautiful Bill Act, 2025, made the TCJA brackets
  permanent and raised the standard deduction to $31,500 MFJ / $15,750 single).
  2026's actual inflation-indexed figures will run a percent or two higher, immaterial
  to a real-dollar directional screen.
- WI brackets: HIGH CONFIDENCE. Verified 2025 thresholds from revenue.wi.gov (2025 Tax
  Computation Worksheet, Form 1 instructions p.44) - MFJ 5.3% bracket $67,300-$431,060,
  Single/HoH 5.3% bracket $50,480-$323,290, 7.65% above those ceilings. Previous
  brackets in this file were 2024-vintage guesses and were meaningfully off (e.g. MFJ
  top bracket started at $540,700 instead of the real $431,060).
- WI standard deduction: MODERATE-HIGH CONFIDENCE, materially corrected. WI's standard
  deduction is NOT flat - it phases out linearly with income and reaches ZERO well
  within this household's projected retirement income range. Verified from the Form 1
  instructions' Standard Deduction Table (user read the table directly):
    MFJ:    $25,110 flat through $28,000 income, phasing linearly to $0 at $155,169.
    Single: $13,560 flat through $19,500 income, phasing linearly to $0 at $132,500.
  The prior flat $24,000 MFJ / $13,000 Single assumption was overstating this
  household's WI deduction (understating WI tax owed) in every projected year above
  ~$150K MFJ income - i.e. most retirement years under the bracket-fill strategy.
  Modeled here as a straight-line interpolation between the flat-amount ceiling and the
  $0 point, which is a reasonable approximation of WI's actual $100-increment table but
  not an exact replication of it.
"""

# (lower bound, rate) pairs, cumulative bracket style. Federal, approx 2026 current law.
FEDERAL_BRACKETS_MFJ = [
    (0, 0.10),
    (23_850, 0.12),
    (96_950, 0.22),
    (206_700, 0.24),
    (394_600, 0.32),
    (501_050, 0.35),
    (751_600, 0.37),
]
FEDERAL_BRACKETS_SINGLE = [
    (0, 0.10),
    (11_925, 0.12),
    (48_475, 0.22),
    (103_350, 0.24),
    (197_300, 0.32),
    (250_525, 0.35),
    (375_800, 0.37),
]
STANDARD_DEDUCTION = {"MFJ": 31_500, "SINGLE": 15_750}

# Wisconsin, verified 2025 brackets on ordinary income (retirement account
# withdrawals are ordinary income under WI law - no LTCG-style exclusion applies).
WI_BRACKETS_MFJ = [
    (0, 0.035),
    (19_580, 0.044),
    (67_300, 0.053),
    (431_060, 0.0765),
]
WI_BRACKETS_SINGLE = [
    (0, 0.035),
    (14_680, 0.044),
    (50_480, 0.053),
    (323_290, 0.0765),
]

# WI standard deduction phases out linearly with income and reaches zero - it is NOT
# a flat amount. (flat_amount, phaseout_start, zero_point), all verified 2025 figures.
WI_STD_DEDUCTION_SCHEDULE = {
    "MFJ": (25_110, 28_000, 155_169),
    "SINGLE": (13_560, 19_500, 132_500),
}


def wi_standard_deduction(ordinary_income, filing_status):
    flat_amount, phaseout_start, zero_point = WI_STD_DEDUCTION_SCHEDULE[filing_status]
    if ordinary_income <= phaseout_start:
        return flat_amount
    if ordinary_income >= zero_point:
        return 0.0
    slope = flat_amount / (zero_point - phaseout_start)
    return flat_amount - slope * (ordinary_income - phaseout_start)

# Combined federal LTCG + WI effective rate for taxable-brokerage gains, per
# memory/user_location_tax.md (18.71%). Held flat - does not vary by income here.
LTCG_COMBINED_RATE = 0.1871

# IRS Uniform Lifetime Table (SECURE 2.0), age -> divisor. Applies once traditional
# balances are subject to RMD starting age 73.
RMD_DIVISORS = {
    73: 26.5, 74: 25.5, 75: 24.6, 76: 23.7, 77: 22.9, 78: 22.0, 79: 21.1,
    80: 20.2, 81: 19.4, 82: 18.5, 83: 17.7, 84: 16.8, 85: 16.0, 86: 15.2,
    87: 14.4, 88: 13.7, 89: 12.9, 90: 12.2, 91: 11.5, 92: 10.8, 93: 10.1,
    94: 9.5, 95: 8.9, 96: 8.4, 97: 7.8, 98: 7.3, 99: 6.8, 100: 6.4,
}


def _progressive_tax(taxable_income, brackets):
    if taxable_income <= 0:
        return 0.0
    tax = 0.0
    for i, (lower, rate) in enumerate(brackets):
        upper = brackets[i + 1][0] if i + 1 < len(brackets) else float("inf")
        if taxable_income <= lower:
            break
        tax += (min(taxable_income, upper) - lower) * rate
    return tax


def _marginal_rate(taxable_income, brackets):
    rate = brackets[0][1]
    for lower, r in brackets:
        if taxable_income > lower:
            rate = r
    return rate


def federal_tax(ordinary_income, filing_status):
    brackets = FEDERAL_BRACKETS_MFJ if filing_status == "MFJ" else FEDERAL_BRACKETS_SINGLE
    taxable = max(0.0, ordinary_income - STANDARD_DEDUCTION[filing_status])
    return _progressive_tax(taxable, brackets)


def federal_marginal_rate(ordinary_income, filing_status):
    brackets = FEDERAL_BRACKETS_MFJ if filing_status == "MFJ" else FEDERAL_BRACKETS_SINGLE
    taxable = max(0.0, ordinary_income - STANDARD_DEDUCTION[filing_status])
    return _marginal_rate(taxable, brackets)


def wi_tax(ordinary_income, filing_status):
    brackets = WI_BRACKETS_MFJ if filing_status == "MFJ" else WI_BRACKETS_SINGLE
    taxable = max(0.0, ordinary_income - wi_standard_deduction(ordinary_income, filing_status))
    return _progressive_tax(taxable, brackets)


def bracket_ceiling_gross(target_rate, filing_status):
    """
    Gross ordinary income (i.e. before the standard deduction, matching how
    ordinary_income_fed/wi are tracked in engine.py) at the TOP of the named federal
    bracket - e.g. bracket_ceiling_gross(0.12, "MFJ") returns the income you could
    have while staying inside the 12% bracket. Used by the bracket-fill withdrawal
    strategy to decide how much extra traditional withdrawal "fits" before spilling
    into the next-higher rate. Returns None if the target rate isn't in the table
    (e.g. requesting the top bracket, which has no ceiling).
    """
    brackets = FEDERAL_BRACKETS_MFJ if filing_status == "MFJ" else FEDERAL_BRACKETS_SINGLE
    for i, (lower, rate) in enumerate(brackets):
        if rate == target_rate:
            if i + 1 >= len(brackets):
                return None
            upper_taxable = brackets[i + 1][0]
            return upper_taxable + STANDARD_DEDUCTION[filing_status]
    return None


def wi_marginal_rate(ordinary_income, filing_status):
    brackets = WI_BRACKETS_MFJ if filing_status == "MFJ" else WI_BRACKETS_SINGLE
    taxable = max(0.0, ordinary_income - wi_standard_deduction(ordinary_income, filing_status))
    return _marginal_rate(taxable, brackets)


def rmd_divisor(age):
    if age < 73:
        return None
    return RMD_DIVISORS.get(age, RMD_DIVISORS[max(RMD_DIVISORS)])


# "Provisional income" test thresholds (IRC 86) for how much Social Security is
# federally taxable. Simplified from the IRS worksheet - accurate to the standard
# published tiers, not to every worksheet line item (e.g. tax-exempt interest add-back
# omitted, assumed zero). WISCONSIN DOES NOT TAX SOCIAL SECURITY AT ALL - this
# function is federal-only; never add its output to the WI ordinary-income base.
SS_PROVISIONAL_THRESHOLDS = {"MFJ": (32_000, 44_000), "SINGLE": (25_000, 34_000)}


def taxable_social_security(ss_benefit, other_ordinary_income, filing_status):
    if ss_benefit <= 0:
        return 0.0
    t1, t2 = SS_PROVISIONAL_THRESHOLDS[filing_status]
    provisional = other_ordinary_income + 0.5 * ss_benefit
    if provisional <= t1:
        return 0.0
    if provisional <= t2:
        return min(0.5 * (provisional - t1), 0.5 * ss_benefit)
    tier1 = min(0.5 * (t2 - t1), 0.5 * ss_benefit)
    taxable = tier1 + 0.85 * (provisional - t2)
    return min(taxable, 0.85 * ss_benefit)
