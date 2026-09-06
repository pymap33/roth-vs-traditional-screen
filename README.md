# Roth vs. Traditional Contribution Screen

A directional screening tool: given a household's account balances, contribution
split, and tax situation, it projects several Roth/traditional contribution-split
scenarios forward through retirement (including RMD-forced income and bracket
effects) and compares after-tax outcomes. Built to answer one question - *given my
specific numbers, does shifting my 401k contribution split toward traditional
actually help, once RMDs and future tax brackets are accounted for?* - which a
generic rule of thumb ("traditional if you expect a lower bracket in retirement")
doesn't really answer on its own.

**This is a screening tool, not tax or financial advice.** It models real IRS/state
tax mechanics (progressive brackets, RMD tables, the Social Security "provisional
income" test) but leaves out several things noted below - read "Known scope limits"
before trusting the output for a real decision.

## Quick start (Python)

```
pip install python (3.9+) - no other dependencies
cp inputs/household.json inputs/my-household.json   # keep your real numbers out of git
# edit my-household.json with your own figures
# edit the INPUT constant at the top of run_scenarios.py to point at your copy
python run_scenarios.py
```

Every field in `inputs/household.json` has an inline `_help`-style explanation next
to it - read those before changing a value you're unsure about, especially
`annualSpendingTarget_todaysDollars`, which is usually the softest number anyone
supplies and deserves the most scrutiny, not the least.

**Privacy note:** if you fill in real account balances, do not commit that file to a
public repo. `inputs/household.json` here is a generic placeholder template
(`_howToUse` field at the top explains it) - keep your own filled-in copy local, or
add it to `.gitignore` if you're working in a fork.

## What it models

- **Accumulation + RMD-forced decumulation** across a chosen longevity horizon.
- **Three withdrawal strategies**, comparable side by side via
  `compare_withdrawal_order.py`:
  - `sequential` - RMD forced from traditional first, then taxable -> traditional ->
    Roth for any remaining spending need.
  - `bracket_fill` - proactively withdraws extra traditional dollars up to a target
    federal bracket ceiling even beyond spending need, betting that paying a known
    low rate now beats a bigger, higher-bracket RMD later.
  - `pace_to_horizon` - paces traditional withdrawals to drain the balance by the
    longevity horizon, recomputed fresh every year. Not a strict upgrade over
    `bracket_fill` - it wins for small traditional balances, loses for large ones
    (no ceiling means it can front-load withdrawals into higher brackets as a large
    balance keeps compounding). Run `compare_withdrawal_order.py` to see all three
    against your own numbers.
- **Social Security** (optional, off by default) - federal taxability follows the
  real IRC 86 "provisional income" test; correctly excluded from state ordinary
  income for states that don't tax SS.
- **Legacy vs. spend-down framing** - shows both when undetermined, rather than
  silently assuming one.
- **Net-of-tax wealth**, not gross - traditional, Roth, and taxable-brokerage dollars
  are not tax-equivalent, and summing them at face value overstates
  traditional-heavy scenarios.

## Known scope limits (not modeled)

Child tax credits, IRMAA/ACA premium cliffs, long-term-care cost shocks,
pre-retirement wage growth/promotions, and mid-retirement state relocation are all
explicitly out of scope. Everything is modeled in real (today's) dollars - brackets
and spending held flat rather than carrying a separate inflation track. Federal tax
tables are high-confidence (checked against 2025 post-OBBBA law); Wisconsin's
brackets and standard-deduction phase-out are verified against the live WI DOR 2025
Form 1 instructions - **using a different state requires adding its own bracket/
deduction schedule to `tax_tables.py` first.**

## Sensitivity tools

- `sensitivity_return.py` - real return assumption, 2-6%.
- `sensitivity_social_security.py` - SS benefit on/off at several levels.
- `compare_withdrawal_order.py` - all three withdrawal strategies side by side.

## Browser version

`index.html` runs this exact `engine.py`/`tax_tables.py` in-browser via
[Pyodide](https://pyodide.org/) (Python compiled to WebAssembly) - not a hand-ported
JavaScript rewrite, so there is never a second implementation of the tax/withdrawal
logic to drift out of sync with the Python one. `web_bridge.py` is the only new code
involved - a thin orchestration layer that calls `engine.run_scenario()` once per
contribution-split scenario and shapes the results into JSON for the page; it
contains no tax/withdrawal logic of its own.

**Nothing you enter is sent anywhere** - the whole thing runs locally in your
browser tab, including the Python interpreter itself.

**To run it locally**, serve the folder over HTTP (opening `index.html` directly
from disk will fail - browsers block `fetch()` of sibling files from `file://`
URLs):

```
python -m http.server 8000
# then open http://localhost:8000/ in a browser
```

Once this repo is public, the same page can be hosted for free on GitHub Pages
with no server of your own required.

**Status:** built 2026-09-05, verified end-to-end in plain CPython (the bridge
function reproduces the CLI scripts' numbers exactly) and checked against Pyodide's
documented JS API, but **not yet confirmed running in an actual browser** - test it
yourself locally before relying on it or sharing a link.
