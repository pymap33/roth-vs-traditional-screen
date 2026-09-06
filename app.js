// Loads the real engine.py / tax_tables.py / web_bridge.py from this repo into
// Pyodide (Python compiled to WebAssembly) and runs them unmodified in-browser.
// There is no second implementation of the tax/withdrawal logic anywhere in
// this file - every number below comes from calling the actual Python engine.

const SOURCE_FILES = ["tax_tables.py", "engine.py", "web_bridge.py"];

const SCENARIO_COLORS = [
  "var(--scenario-1)",
  "var(--scenario-2)",
  "var(--scenario-3)",
  "var(--scenario-4)",
  "var(--scenario-5)",
];

let pyodideReadyPromise = null;

async function initPyodide() {
  const pyodide = await loadPyodide();
  for (const filename of SOURCE_FILES) {
    const response = await fetch(filename, { cache: "no-cache" });
    if (!response.ok) {
      throw new Error(`Could not load ${filename} (HTTP ${response.status}). ` +
        `If you're opening this file directly from disk, serve it over a local ` +
        `web server instead (e.g. "python -m http.server") - browsers block ` +
        `same-origin file fetches from file:// URLs.`);
    }
    const text = await response.text();
    pyodide.FS.writeFile(filename, text);
  }
  pyodide.runPython("import sys\nif '.' not in sys.path:\n    sys.path.insert(0, '.')\n");
  pyodide.runPython("import engine, web_bridge");
  return pyodide;
}

function fmtDollars(n) {
  return n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

function fmtPct(n) {
  return (n * 100).toFixed(0) + "%";
}

function readHousehold() {
  const ssEnabled = document.getElementById("ssEnabled").checked;
  const household = {
    household: {
      filingStatus: document.getElementById("filingStatus").value,
      state: document.getElementById("state").value,
      stateInRetirement: document.getElementById("state").value,
      dependents: 0,
      currentAge_primary: Number(document.getElementById("currentAge").value),
      targetRetirementAge: Number(document.getElementById("retirementAge").value),
      assumeZeroSocialSecurity: !ssEnabled,
      legacyIntent: "undetermined",
      knownFutureFilingStatusChange: false,
    },
    socialSecurity: {
      estimatedAnnualBenefit_householdTotal_todaysDollars: ssEnabled
        ? Number(document.getElementById("ssBenefit").value) : 0,
      claimingAge: ssEnabled ? Number(document.getElementById("ssClaimingAge").value) : 67,
    },
    income: {
      currentHouseholdTaxableIncomeApprox: Number(document.getElementById("wageBase").value),
      currentApproxMarginalFederalBracket: 0,
    },
    balances: {
      totals: {
        traditional_all: Number(document.getElementById("balTraditional").value),
        roth_all: Number(document.getElementById("balRoth").value),
        taxable_all: Number(document.getElementById("balTaxable").value),
      },
    },
    contributions_annual: {
      roth401k_employee: Number(document.getElementById("employeeContrib").value),
      employerMatchPlusBoost_preTax: Number(document.getElementById("employerContrib").value),
    },
    retirementSpending: {
      status: "entered via browser tool",
      annualSpendingTarget_todaysDollars: Number(document.getElementById("spendingTarget").value),
      excludesHousingPayment: false,
    },
  };
  return household;
}

function renderChart(results) {
  const chart = document.getElementById("chart");
  chart.innerHTML = "";
  const maxWealth = Math.max(...results.map((r) => r.net_of_tax_wealth), 1);

  results.forEach((r, i) => {
    const row = document.createElement("div");
    row.className = "bar-row";

    const label = document.createElement("div");
    label.className = "bar-label";
    label.textContent = r.name;

    const track = document.createElement("div");
    track.className = "bar-track";
    const fill = document.createElement("div");
    fill.className = "bar-fill";
    const pct = Math.max(2, (r.net_of_tax_wealth / maxWealth) * 100);
    fill.style.width = pct + "%";
    fill.style.background = SCENARIO_COLORS[i % SCENARIO_COLORS.length];
    track.appendChild(fill);

    const value = document.createElement("div");
    value.className = "bar-value";
    value.textContent = fmtDollars(r.net_of_tax_wealth);

    row.appendChild(label);
    row.appendChild(track);
    row.appendChild(value);
    chart.appendChild(row);
  });
}

function renderTable(results) {
  const container = document.getElementById("results-table");
  const wrap = document.createElement("div");
  wrap.className = "table-wrap";

  const table = document.createElement("table");
  const thead = document.createElement("thead");
  thead.innerHTML = `<tr>
    <th>Scenario</th>
    <th>Lifetime tax paid</th>
    <th>Net-of-tax ending wealth</th>
    <th>Peak marginal federal bracket</th>
    <th>Notes</th>
  </tr>`;
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  results.forEach((r, i) => {
    const tr = document.createElement("tr");
    const notes = [];
    if (r.depleted_at_age) {
      notes.push(`spending shortfall from age ${r.depleted_at_age}`);
    }
    if (!r.roth_touched && r.end_roth > 0.01) {
      notes.push(`Roth never withdrawn from — passes to heirs tax-free (${fmtDollars(r.end_roth)})`);
    }
    if (i === 0) {
      notes.push("<span class=\"badge\">best</span>");
    }
    tr.innerHTML = `
      <td>${r.name}</td>
      <td class="num">${fmtDollars(r.lifetime_tax)}</td>
      <td class="num">${fmtDollars(r.net_of_tax_wealth)}</td>
      <td class="num">${fmtPct(r.peak_marginal_federal_bracket)}</td>
      <td>${notes.join("; ") || "&mdash;"}</td>
    `;
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  wrap.appendChild(table);
  container.innerHTML = "";
  container.appendChild(wrap);
}

function toggleSocialSecurityFields() {
  const enabled = document.getElementById("ssEnabled").checked;
  document.getElementById("ss-fields").hidden = !enabled;
}

function toggleBracketFillRow() {
  const strategy = document.getElementById("withdrawalStrategy").value;
  document.getElementById("bracket-fill-rate-row").hidden = strategy !== "bracket_fill";
}

async function handleSubmit(event) {
  event.preventDefault();
  const button = document.getElementById("run-button");
  button.disabled = true;
  button.textContent = "Running…";

  try {
    const pyodide = await pyodideReadyPromise;
    const household = readHousehold();
    const bridge = pyodide.globals.get("web_bridge");

    const widowAgeInput = document.getElementById("widowAge").value;
    const widowAge = widowAgeInput === "" ? null : Number(widowAgeInput);

    const resultJson = bridge.run_all_scenarios(
      JSON.stringify(household),
      Number(document.getElementById("realReturn").value),
      document.getElementById("withdrawalStrategy").value,
      Number(document.getElementById("bracketFillRate").value),
      Number(document.getElementById("longevityAge").value),
      widowAge
    );
    const results = JSON.parse(resultJson);

    renderChart(results);
    renderTable(results);
    document.getElementById("results").hidden = false;
    document.getElementById("results").scrollIntoView({ behavior: "smooth" });
  } catch (err) {
    console.error(err);
    const banner = document.getElementById("load-error");
    banner.hidden = false;
    banner.textContent = "Something went wrong running the scenarios: " + err.message;
  } finally {
    button.disabled = false;
    button.textContent = "Run comparison";
  }
}

async function main() {
  document.getElementById("ssEnabled").addEventListener("change", toggleSocialSecurityFields);
  document.getElementById("withdrawalStrategy").addEventListener("change", toggleBracketFillRow);
  document.getElementById("household-form").addEventListener("submit", handleSubmit);

  pyodideReadyPromise = initPyodide();
  try {
    await pyodideReadyPromise;
    document.getElementById("loading").hidden = true;
    document.getElementById("household-form").hidden = false;
  } catch (err) {
    console.error(err);
    document.getElementById("loading").hidden = true;
    const banner = document.getElementById("load-error");
    banner.hidden = false;
    banner.textContent = "Failed to load the Python engine: " + err.message;
  }
}

main();
