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
  "#6b6bd6",
];

const LEDGER_SERIES = [
  { key: "end_traditional", label: "Traditional", color: "var(--scenario-1)" },
  { key: "end_roth", label: "Roth", color: "var(--scenario-4)" },
  { key: "end_taxable", label: "Taxable brokerage", color: "var(--scenario-5)" },
];

// Every form field that should round-trip through the "save my numbers"
// localStorage profile. Kept as one list so save/load/clear stay generic
// instead of hand-listing each field three times.
const PROFILE_FIELDS = [
  { id: "filingStatus", type: "value" },
  { id: "state", type: "value" },
  { id: "stateInRetirement", type: "value" },
  { id: "currentAge", type: "value" },
  { id: "retirementAge", type: "value" },
  { id: "balTraditional", type: "value" },
  { id: "balRoth", type: "value" },
  { id: "balTaxable", type: "value" },
  { id: "employeeContrib", type: "value" },
  { id: "employerContrib", type: "value" },
  { id: "wageBase", type: "value" },
  { id: "spendingTarget", type: "value" },
  { id: "ssEnabled", type: "checkbox" },
  { id: "ssBenefit", type: "value" },
  { id: "ssClaimingAge", type: "value" },
  { id: "realReturn", type: "value" },
  { id: "longevityAge", type: "value" },
  { id: "withdrawalStrategy", type: "value" },
  { id: "bracketFillRate", type: "value" },
  { id: "widowAge", type: "value" },
  { id: "rmdStartAge", type: "value" },
  { id: "customTraditionalPct", type: "value" },
  { id: "dollarDisplay", type: "value" },
  { id: "inflationRate", type: "value" },
];
const PROFILE_STORAGE_KEY = "rothVsTraditionalScreen.profile.v1";

let pyodideReadyPromise = null;
let lastResults = [];

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

// Converts a real (today's-dollar) amount into a displayed amount, applying the
// nominal-dollar inflation factor if that toggle is on. yearsFromNow is the
// number of years between the household's current age and the age this dollar
// figure is valued at - a point-in-time conversion, not a sum-across-years one
// (see the "Lifetime tax paid" column, which deliberately stays real-dollar-only
// because a sum of flows from different years has no single nominal equivalent).
function displayDollar(realAmount, yearsFromNow) {
  if (document.getElementById("dollarDisplay").value !== "nominal") {
    return realAmount;
  }
  const rate = Number(document.getElementById("inflationRate").value) || 0;
  return realAmount * Math.pow(1 + rate, Math.max(0, yearsFromNow));
}

function currentAge() {
  return Number(document.getElementById("currentAge").value);
}
function longevityAge() {
  return Number(document.getElementById("longevityAge").value);
}

function readHousehold() {
  const ssEnabled = document.getElementById("ssEnabled").checked;
  const household = {
    household: {
      filingStatus: document.getElementById("filingStatus").value,
      state: document.getElementById("state").value,
      stateInRetirement: document.getElementById("stateInRetirement").value,
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
  const yearsFromNow = longevityAge() - currentAge();
  const displayed = results.map((r) => displayDollar(r.net_of_tax_wealth, yearsFromNow));
  const maxWealth = Math.max(...displayed, 1);

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
    const pct = Math.max(2, (displayed[i] / maxWealth) * 100);
    fill.style.width = pct + "%";
    fill.style.background = SCENARIO_COLORS[i % SCENARIO_COLORS.length];
    track.appendChild(fill);

    const value = document.createElement("div");
    value.className = "bar-value";
    value.textContent = fmtDollars(displayed[i]);

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
  const yearsFromNow = longevityAge() - currentAge();
  const isNominal = document.getElementById("dollarDisplay").value === "nominal";

  const table = document.createElement("table");
  const thead = document.createElement("thead");
  thead.innerHTML = `<tr>
    <th>Scenario</th>
    <th>Lifetime tax paid${isNominal ? " (always real $)" : ""}</th>
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
      const rothDisplay = fmtDollars(displayDollar(r.end_roth, yearsFromNow));
      notes.push(`Roth never withdrawn from — passes to heirs tax-free (${rothDisplay})`);
    }
    if (i === 0) {
      notes.push("<span class=\"badge\">best</span>");
    }
    tr.innerHTML = `
      <td>${r.name}</td>
      <td class="num">${fmtDollars(r.lifetime_tax)}</td>
      <td class="num">${fmtDollars(displayDollar(r.net_of_tax_wealth, yearsFromNow))}</td>
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

function populateLedgerScenarioSelect(results) {
  const select = document.getElementById("ledger-scenario-select");
  select.innerHTML = "";
  results.forEach((r) => {
    const opt = document.createElement("option");
    opt.value = r.name;
    opt.textContent = r.name;
    select.appendChild(opt);
  });
}

function renderLedgerChart(ledger) {
  const container = document.getElementById("ledger-chart");
  container.innerHTML = "";
  if (!ledger.length) return;

  const width = 700, height = 320, padding = { top: 16, right: 16, bottom: 32, left: 70 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;

  const ages = ledger.map((r) => r.age);
  const minAge = Math.min(...ages), maxAge = Math.max(...ages);
  const isNominal = document.getElementById("dollarDisplay").value === "nominal";
  const baseAge = currentAge();

  const displayedSeries = LEDGER_SERIES.map((s) => ({
    ...s,
    values: ledger.map((r) => displayDollar(r[s.key], r.age - baseAge)),
  }));
  const maxValue = Math.max(...displayedSeries.flatMap((s) => s.values), 1);

  const xForAge = (age) => padding.left + ((age - minAge) / Math.max(1, maxAge - minAge)) * plotWidth;
  const yForValue = (v) => padding.top + plotHeight - (v / maxValue) * plotHeight;

  const svgParts = [];
  svgParts.push(`<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Balance by account type over time">`);

  // gridlines + y-axis labels (0, 1/2 max, max)
  [0, 0.5, 1].forEach((frac) => {
    const y = padding.top + plotHeight - frac * plotHeight;
    svgParts.push(`<line x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}" stroke="var(--border)" stroke-width="1"/>`);
    svgParts.push(`<text x="${padding.left - 8}" y="${y + 4}" font-size="11" text-anchor="end" fill="var(--text-muted)">${fmtDollars(frac * maxValue)}</text>`);
  });
  // x-axis labels: min and max age plus a midpoint
  [minAge, Math.round((minAge + maxAge) / 2), maxAge].forEach((age) => {
    const x = xForAge(age);
    svgParts.push(`<text x="${x}" y="${height - padding.bottom + 18}" font-size="11" text-anchor="middle" fill="var(--text-muted)">age ${age}</text>`);
  });

  displayedSeries.forEach((s) => {
    const points = ledger.map((r, i) => `${xForAge(r.age)},${yForValue(s.values[i])}`).join(" ");
    svgParts.push(`<polyline points="${points}" fill="none" stroke="${s.color}" stroke-width="2.5"/>`);
  });

  svgParts.push("</svg>");
  container.innerHTML = svgParts.join("");

  const legend = document.createElement("div");
  legend.className = "chart-legend";
  LEDGER_SERIES.forEach((s) => {
    const item = document.createElement("span");
    item.className = "legend-item";
    item.innerHTML = `<span class="legend-swatch" style="background:${s.color}"></span>${s.label}`;
    legend.appendChild(item);
  });
  if (isNominal) {
    const note = document.createElement("p");
    note.className = "field-note";
    note.textContent = "Shown in nominal (future) dollars per the display setting above.";
    legend.appendChild(note);
  }
  container.appendChild(legend);
}

async function refreshLedgerView() {
  const pyodide = await pyodideReadyPromise;
  const bridge = pyodide.globals.get("web_bridge");
  const select = document.getElementById("ledger-scenario-select");
  const name = select.value;
  if (!name) return;
  const ledgerJson = bridge.get_ledger_json(name);
  const ledger = JSON.parse(ledgerJson);
  renderLedgerChart(ledger);
}

async function handleDownloadCsv() {
  const pyodide = await pyodideReadyPromise;
  const bridge = pyodide.globals.get("web_bridge");
  const name = document.getElementById("ledger-scenario-select").value;
  if (!name) return;
  const csvText = bridge.get_ledger_csv(name);
  const blob = new Blob([csvText], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const safeName = name.replace(/[^a-z0-9]+/gi, "_").toLowerCase();
  a.href = url;
  a.download = `${safeName}_ledger.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function toggleSocialSecurityFields() {
  const enabled = document.getElementById("ssEnabled").checked;
  document.getElementById("ss-fields").hidden = !enabled;
}

function toggleBracketFillRow() {
  const strategy = document.getElementById("withdrawalStrategy").value;
  document.getElementById("bracket-fill-rate-row").hidden = strategy !== "bracket_fill";
}

function toggleInflationRow() {
  const isNominal = document.getElementById("dollarDisplay").value === "nominal";
  document.getElementById("inflation-rate-row").hidden = !isNominal;
  if (lastResults.length) {
    renderChart(lastResults);
    renderTable(lastResults);
    refreshLedgerView();
  }
}

// --- Save/load profile (localStorage only - never sent anywhere) ---

function saveProfile() {
  const status = document.getElementById("profile-status");
  try {
    const data = {};
    for (const field of PROFILE_FIELDS) {
      const el = document.getElementById(field.id);
      data[field.id] = field.type === "checkbox" ? el.checked : el.value;
    }
    localStorage.setItem(PROFILE_STORAGE_KEY, JSON.stringify(data));
    status.textContent = "Saved.";
  } catch (err) {
    console.error(err);
    status.textContent = "Couldn't save (browser storage may be disabled).";
  }
}

function loadProfile() {
  const status = document.getElementById("profile-status");
  try {
    const raw = localStorage.getItem(PROFILE_STORAGE_KEY);
    if (!raw) {
      status.textContent = "No saved numbers found.";
      return;
    }
    const data = JSON.parse(raw);
    for (const field of PROFILE_FIELDS) {
      if (!(field.id in data)) continue;
      const el = document.getElementById(field.id);
      if (field.type === "checkbox") {
        el.checked = data[field.id];
      } else {
        el.value = data[field.id];
      }
    }
    toggleSocialSecurityFields();
    toggleBracketFillRow();
    toggleInflationRow();
    status.textContent = "Loaded.";
  } catch (err) {
    console.error(err);
    status.textContent = "Couldn't load saved numbers (browser storage may be disabled or the saved data is corrupted).";
  }
}

function clearProfile() {
  const status = document.getElementById("profile-status");
  try {
    localStorage.removeItem(PROFILE_STORAGE_KEY);
    status.textContent = "Cleared.";
  } catch (err) {
    console.error(err);
    status.textContent = "Couldn't clear (browser storage may be disabled).";
  }
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
    const customPctInput = document.getElementById("customTraditionalPct").value;
    const customPct = customPctInput === "" ? null : Number(customPctInput);

    const resultJson = bridge.run_all_scenarios(
      JSON.stringify(household),
      Number(document.getElementById("realReturn").value),
      document.getElementById("withdrawalStrategy").value,
      Number(document.getElementById("bracketFillRate").value),
      Number(document.getElementById("longevityAge").value),
      widowAge,
      Number(document.getElementById("rmdStartAge").value),
      customPct
    );
    const results = JSON.parse(resultJson);
    lastResults = results;

    renderChart(results);
    renderTable(results);
    populateLedgerScenarioSelect(results);
    await refreshLedgerView();

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
  document.getElementById("dollarDisplay").addEventListener("change", toggleInflationRow);
  document.getElementById("household-form").addEventListener("submit", handleSubmit);
  document.getElementById("ledger-scenario-select").addEventListener("change", refreshLedgerView);
  document.getElementById("download-csv-btn").addEventListener("click", handleDownloadCsv);
  document.getElementById("save-profile-btn").addEventListener("click", saveProfile);
  document.getElementById("load-profile-btn").addEventListener("click", loadProfile);
  document.getElementById("clear-profile-btn").addEventListener("click", clearProfile);

  pyodideReadyPromise = initPyodide();
  try {
    await pyodideReadyPromise;
    document.getElementById("loading").hidden = true;
    document.getElementById("household-form").hidden = false;
    document.getElementById("profile-controls").hidden = false;
  } catch (err) {
    console.error(err);
    document.getElementById("loading").hidden = true;
    const banner = document.getElementById("load-error");
    banner.hidden = false;
    banner.textContent = "Failed to load the Python engine: " + err.message;
  }
}

main();
