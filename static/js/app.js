/* ============================================================================
   State
============================================================================ */
let METHOD_META = null;
const selectedInstances = [];
const runState = {}; // includes charts per run

// SSE resume state (prevents duplicated events after reconnect)
const lastEventIdByRun = {}; // { [runId]: number }

/* ============================================================================
   Utilities
============================================================================ */
function setStatus(msg){ document.getElementById("status").textContent = msg; }

function escHtml(s){
  return String(s)
    .replaceAll("&","&amp;")
    .replaceAll("<","&lt;")
    .replaceAll(">","&gt;")
    .replaceAll('"',"&quot;");
}

function uuidShort(prefix="m"){
  const t = Date.now().toString(36);
  const r = Math.random().toString(36).slice(2,7);
  return `${prefix}-${t}-${r}`;
}

function humanLabel(name, params){
  const keys = Object.keys(params || {}).filter(k => params[k] !== "" && params[k] != null && !Number.isNaN(params[k]));
  if (!keys.length) return name;
  const bits = keys.map(k => `${k}=${params[k]}`);
  return `${name} • ${bits.join(", ")}`;
}

function updateSelectedBadge(){
  const el = document.getElementById("methodCountBadge");
  if (el) el.textContent = `${selectedInstances.length} selected`;
}

function countByMethod(){
  const m = {};
  for (const inst of selectedInstances){
    m[inst.name] = (m[inst.name] || 0) + 1;
  }
  return m;
}

/* Run status pill helper */
function setRunPill(run_id, status){
  const el = document.getElementById(`runStatus-${run_id}`);
  if (!el) return;

  el.classList.remove("ok","bad","warn");
  if (status === "running") el.classList.add("warn");
  if (status === "completed") el.classList.add("ok");
  if (status === "failed") el.classList.add("bad");

  if (status === "running"){
    el.innerHTML = `<span class="spinner"></span><span>running</span>`;
  } else if (status === "completed"){
    el.innerHTML = `<span class="checkIcon">✓</span><span>completed</span>`;
  } else if (status === "failed"){
    el.innerHTML = `<span>failed</span>`;
  } else {
    el.innerHTML = `<span>${escHtml(status)}</span>`;
  }
}

function statusIcon(status){
  if (status === "running") return `<span class="spinner" style="width:12px;height:12px;border-width:2px;"></span>`;
  if (status === "completed") return `<span class="checkIcon" style="width:12px;height:12px;border-radius:3px;font-size:11px;">✓</span>`;
  if (status === "failed") return `<span style="width:12px;height:12px;display:inline-flex;align-items:center;justify-content:center;font-weight:900;color:var(--bad);">!</span>`;
  return `<span style="width:12px;height:12px;display:inline-block;"></span>`;
}

/* ============================================================================
   Color helpers (deterministic per method label)
   - Used for polar colors “per method”
============================================================================ */
function hashStrToHue(str){
  let h = 0;
  for (let i=0;i<str.length;i++){
    h = (h * 31 + str.charCodeAt(i)) >>> 0;
  }
  return h % 360;
}
function rgbaFromHue(h, a){
  return `hsla(${h}, 75%, 55%, ${a})`;
}
function borderFromHue(h){
  return `hsla(${h}, 75%, 40%, 1)`;
}

/* ============================================================================
   SSE (resumable, no duplicates)
   Requires backend to include `_event_id` in event JSON and accept `?since=...`
============================================================================ */
function persistLastEventId(runId, eventId){
  lastEventIdByRun[runId] = eventId;

  // Optional persistence across reloads
  try {
    localStorage.setItem(`teda:lastEventId:${runId}`, String(eventId));
  } catch (e) {}
}

function loadLastEventId(runId){
  if (lastEventIdByRun[runId] != null) return lastEventIdByRun[runId];
  try {
    const s = localStorage.getItem(`teda:lastEventId:${runId}`);
    if (s != null && s !== ""){
      const n = Number(s);
      if (Number.isFinite(n)) {
        lastEventIdByRun[runId] = n;
        return n;
      }
    }
  } catch (e) {}
  lastEventIdByRun[runId] = 0;
  return 0;
}

function closeRunSSE(runId){
  const st = runState[runId];
  if (st && st.es){
    try { st.es.close(); } catch (e) {}
    st.es = null;
  }
}

function openRunEvents(runId, onEvent){
  // Close previous for this run (if any)
  closeRunSSE(runId);

  const since = loadLastEventId(runId) || 0;
  const url = `/api/runs/${runId}/events?since=${encodeURIComponent(since)}`;
  const es = new EventSource(url);

  // attach to state (so we can close later)
  runState[runId].es = es;

  const types = [
    "hello",
    "keepalive",
    "run_created",
    "run_started",
    "method_started",
    "partial",
    "method_completed",
    "run_completed",
    "run_failed",
    "done"
  ];

  function handle(ev){
    let payload = {};
    try { payload = JSON.parse(ev.data || "{}"); } catch (e) {}

    // Update resume pointer (prevents duplicates after reconnect)
    if (typeof payload._event_id === "number"){
      persistLastEventId(runId, payload._event_id);
    }

    onEvent(ev.type, payload);

    // Stop stream on terminal states
    if (ev.type === "run_completed" || ev.type === "run_failed" || ev.type === "done"){
      closeRunSSE(runId);
    }
  }

  types.forEach(t => es.addEventListener(t, handle));

  // EventSource auto-reconnects. With `since`, reconnection is safe.
  es.onerror = () => {};

  return es;
}

/* ============================================================================
   Load methods + render chips + help
============================================================================ */
async function loadMethods(){
  const res = await fetch("/api/methods");
  METHOD_META = await res.json();

  renderMethodChips();
  renderHelpModal();
  updateSelectedBadge();

  // sensible default demo
  if (selectedInstances.length === 0){
    if (METHOD_META.methods.includes("letkf")){
      addMethodInstance("letkf");
      addMethodInstance("letkf");
      const inst2 = selectedInstances[1];
      if (inst2 && inst2.params && Object.prototype.hasOwnProperty.call(inst2.params, "r")){
        inst2.params.r = 2;
        inst2.label = humanLabel(inst2.name, inst2.params);
      }
    } else if (METHOD_META.methods.length){
      addMethodInstance(METHOD_META.methods[0]);
    }
    renderMethodTablets();
    renderMethodChips(); // refresh selected styling + counts
  }
}

function renderMethodChips(){
  const chips = document.getElementById("methodChips");
  chips.innerHTML = "";

  const counts = countByMethod();

  METHOD_META.methods.forEach(name => {
    const chip = document.createElement("div");
    const isSelected = (counts[name] || 0) > 0;

    chip.className = "methodChip" + (isSelected ? " selected" : "");
    chip.innerHTML = `
      <span class="dot"></span>
      <span>${escHtml(name)}</span>
      <span class="chipCount">${counts[name] || 0}</span>
    `;

    chip.addEventListener("click", () => {
      addMethodInstance(name);
      renderMethodTablets();
      renderMethodChips(); // update chip colors after selecting
    });

    chips.appendChild(chip);
  });
}

function renderHelpModal(){
  const grid = document.getElementById("helpGrid");
  grid.innerHTML = "";
  const help = METHOD_META.help || {};

  METHOD_META.methods.forEach(name => {
    const card = document.createElement("div");
    card.className = "helpCard";
    const text = help[name] || "No help text available yet.";
    card.innerHTML = `<strong>${escHtml(name)}</strong><p>${escHtml(text)}</p>`;
    grid.appendChild(card);
  });
}

/* ============================================================================
   Method instances
============================================================================ */
function addMethodInstance(name){
  const defaults = (METHOD_META.defaults && METHOD_META.defaults[name])
    ? structuredClone(METHOD_META.defaults[name])
    : {};

  const id = uuidShort("mid");
  const params = defaults || {};
  const label = humanLabel(name, params);

  selectedInstances.push({ id, name, label, params });
  updateSelectedBadge();
}

function removeMethodInstance(id){
  const idx = selectedInstances.findIndex(x => x.id === id);
  if (idx >= 0) selectedInstances.splice(idx, 1);
  updateSelectedBadge();
}

function moveInstance(id, dir){
  const idx = selectedInstances.findIndex(x => x.id === id);
  if (idx < 0) return;
  const j = idx + dir;
  if (j < 0 || j >= selectedInstances.length) return;
  const tmp = selectedInstances[idx];
  selectedInstances[idx] = selectedInstances[j];
  selectedInstances[j] = tmp;
}

function renderMethodTablets(){
  const wrap = document.getElementById("methodTablets");
  wrap.innerHTML = "";

  if (selectedInstances.length === 0){
    const empty = document.createElement("div");
    empty.className = "muted";
    empty.style.marginTop = "8px";
    empty.textContent = "No methods selected yet. Add one using the chips above.";
    wrap.appendChild(empty);
    return;
  }

  selectedInstances.forEach((inst, index) => {
    const tablet = document.createElement("div");
    tablet.className = "tablet";
    tablet.id = `tablet-${inst.id}`;

    const head = document.createElement("div");
    head.className = "tabletHead";

    const left = document.createElement("div");
    left.className = "tabletLeft";
    left.innerHTML = `
      <div class="dot ok"></div>
      <div class="tabletTitle">
        <strong>${escHtml(inst.label)}</strong>
        <span>ID: ${escHtml(inst.id)} • ${escHtml(inst.name)}</span>
      </div>
    `;

    const right = document.createElement("div");
    right.className = "tabletRight";
    right.innerHTML = `
      <button class="miniBtn" title="Move up" ${index===0 ? "disabled" : ""} data-act="up">↑</button>
      <button class="miniBtn" title="Move down" ${index===selectedInstances.length-1 ? "disabled" : ""} data-act="down">↓</button>
      <button class="miniBtn" title="Remove" data-act="rm">Remove</button>
      <span style="margin-left:6px;" data-arrow>▼</span>
    `;

    head.appendChild(left);
    head.appendChild(right);

    const body = document.createElement("div");
    body.className = "tabletBody";   // collapsed by default

    const schema = (METHOD_META.schema && METHOD_META.schema[inst.name]) ? METHOD_META.schema[inst.name] : {};
    body.appendChild(renderParamForm(inst, schema));

    head.addEventListener("click", (e) => {
      const btn = e.target.closest("button");
      if (btn) return;
      const open = body.classList.toggle("open");
      right.querySelector("[data-arrow]").textContent = open ? "▲" : "▼";
    });

    right.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      const act = b.getAttribute("data-act");
      if (act === "rm"){
        removeMethodInstance(inst.id);
        renderMethodTablets();
        renderMethodChips();
      }
      if (act === "up"){
        moveInstance(inst.id, -1);
        renderMethodTablets();
      }
      if (act === "down"){
        moveInstance(inst.id, +1);
        renderMethodTablets();
      }
    });

    tablet.appendChild(head);
    tablet.appendChild(body);
    wrap.appendChild(tablet);
  });
}

function renderParamForm(inst, schema){
  const container = document.createElement("div");

  const keys = Object.keys(schema || {});
  if (keys.length === 0){
    const p = document.createElement("div");
    p.className = "muted";
    p.textContent = "No tunable parameters detected for this method.";
    container.appendChild(p);
    return container;
  }

  const grid = document.createElement("div");
  grid.className = "paramGrid";

  keys.forEach(k => {
    const spec = schema[k] || { type:"str", label:k };

    const field = document.createElement("div");
    field.className = "paramField";
    const lab = document.createElement("label");
    lab.textContent = spec.label || k;

    let input;

    if (spec.type === "bool"){
      input = document.createElement("select");
      input.innerHTML = `<option value="true">true</option><option value="false">false</option>`;
      input.value = String(!!inst.params[k]);
      input.addEventListener("change", () => {
        inst.params[k] = (input.value === "true");
        inst.label = humanLabel(inst.name, inst.params);
        document.querySelector(`#tablet-${inst.id} .tabletTitle strong`).textContent = inst.label;
        renderMethodChips();
      });
    } else {
      input = document.createElement("input");
      input.type = (spec.type === "int" || spec.type === "float") ? "number" : "text";
      if (spec.type === "float") input.step = spec.step ?? "0.01";
      if (spec.type === "int") input.step = spec.step ?? "1";
      if (spec.min != null) input.min = String(spec.min);

      const v = inst.params[k];
      input.value = (v === undefined || v === null) ? "" : String(v);

      input.addEventListener("input", () => {
        const raw = input.value;
        if (spec.type === "int") inst.params[k] = raw === "" ? "" : parseInt(raw, 10);
        else if (spec.type === "float") inst.params[k] = raw === "" ? "" : parseFloat(raw);
        else inst.params[k] = raw;

        inst.label = humanLabel(inst.name, inst.params);
        document.querySelector(`#tablet-${inst.id} .tabletTitle strong`).textContent = inst.label;
        renderMethodChips();
      });
    }

    field.appendChild(lab);
    field.appendChild(input);
    grid.appendChild(field);
  });

  container.appendChild(grid);

  const tip = document.createElement("div");
  tip.className = "muted";
  tip.style.marginTop = "8px";
  tip.textContent = "Tip: labels update automatically based on parameters.";
  container.appendChild(tip);

  return container;
}

/* ============================================================================
   Runs UI + charts
============================================================================ */
function createRunCard(run_id, model){
  const runs = document.getElementById("runs");

  const card = document.createElement("div");
  card.className = "runCard";
  card.id = `run-${run_id}`;

  const head = document.createElement("div");
  head.className = "runHead";

  const left = document.createElement("div");
  left.className = "runTitle";
  left.innerHTML = `<strong>Run ${run_id.slice(0,8)} • ${model}</strong>
                    <span id="runSub-${run_id}">Queued…</span>`;

  const right = document.createElement("div");
  right.className = "right";
  right.innerHTML = `
    <a class="miniBtn" href="/api/runs/${run_id}/csv" style="text-decoration:none;" title="Download CSV">
      Download CSV
    </a>
    <span class="pill" id="runStatus-${run_id}"><span>queued</span></span>
    <span data-arrow>▼</span>
  `;

  head.appendChild(left);
  head.appendChild(right);

  const body = document.createElement("div");
  body.className = "runBody";

  const toolbar = document.createElement("div");
  toolbar.className = "toolbar";
  toolbar.innerHTML = `
    <div class="chipbar" id="runChips-${run_id}"></div>
    <div class="toggle">
      <span>Scale</span>
      <button id="lin-${run_id}">Linear</button>
      <button id="log-${run_id}" class="active">Log</button>
    </div>
  `;

  // SECTION: Time series chart (open by default)
  const secChart = document.createElement("div");
  secChart.className = "section";
  secChart.innerHTML = `
    <div class="sectionHead" data-sec="chart">
      <strong>Chart</strong>
      <div class="sectionRight">
        <span class="muted">Streaming updates</span>
        <span data-arrow>▲</span>
      </div>
    </div>
    <div class="sectionBody open" id="secChartBody-${run_id}">
      <div class="chartWrap">
        <canvas id="chart-${run_id}"></canvas>
      </div>
    </div>
  `;

  // SECTION: Metrics (collapsed by default)
  const secTable = document.createElement("div");
  secTable.className = "section";
  secTable.innerHTML = `
    <div class="sectionHead" data-sec="table">
      <strong>Metrics</strong>
      <div class="sectionRight">
        <span class="muted">RMSE + summary</span>
        <span data-arrow>▼</span>
      </div>
    </div>
    <div class="sectionBody" id="secTableBody-${run_id}">
      <div class="summaryGrid">
        <div class="chartWrap">
          <div class="summaryTitle">
            <span>RMSE by method (Background vs Analysis)</span>
            <span class="muted">radar</span>
          </div>
          <canvas id="rmseRadar-${run_id}"></canvas>
        </div>

        <div class="chartWrap">
          <div class="summaryTitle">
            <span>RMSE improvement (%)</span>
            <span class="muted">polar</span>
          </div>
          <canvas id="rmsePolar-${run_id}"></canvas>
        </div>
      </div>

      <table>
        <thead>
          <tr>
            <th>Method</th>
            <th>Status</th>
            <th>RMSE (analysis)</th>
            <th>RMSE (background)</th>
            <th>Final</th>
            <th>Mean</th>
            <th>Min</th>
            <th>Runtime (s)</th>
            <th>Params</th>
          </tr>
        </thead>
        <tbody id="tbl-${run_id}"></tbody>
      </table>
    </div>
  `;

  body.appendChild(toolbar);
  body.appendChild(secChart);
  body.appendChild(secTable);

  head.addEventListener("click", (e) => {
    if (e.target.closest("a")) return;
    const open = body.classList.toggle("open");
    right.querySelector("[data-arrow]").textContent = open ? "▲" : "▼";
  });

  // toggle sections
  secChart.querySelector(".sectionHead").addEventListener("click", () => {
    const b = document.getElementById(`secChartBody-${run_id}`);
    const arrow = secChart.querySelector(".sectionHead [data-arrow]");
    const open = b.classList.toggle("open");
    arrow.textContent = open ? "▲" : "▼";
    if (open) redraw(run_id);
  });

  secTable.querySelector(".sectionHead").addEventListener("click", () => {
    const b = document.getElementById(`secTableBody-${run_id}`);
    const arrow = secTable.querySelector(".sectionHead [data-arrow]");
    const open = b.classList.toggle("open");
    arrow.textContent = open ? "▲" : "▼";
    if (open){
      ensureSummaryCharts(run_id);
      updateSummaryCharts(run_id);
    }
  });

  card.appendChild(head);
  card.appendChild(body);
  runs.prepend(card);

  runState[run_id] = {
    chart: null,
    rmseRadar: null,
    rmsePolar: null,
    scaleMode: "log",
    instancesById: {},
    seriesA: {},
    statuses: {},
    metrics: {},
    runtime: {},
    lastDraw: 0,
    es: null
  };

  document.getElementById(`lin-${run_id}`).addEventListener("click", () => setScale(run_id, "linear"));
  document.getElementById(`log-${run_id}`).addEventListener("click", () => setScale(run_id, "log"));

  openRunCard(run_id);
  setScale(run_id, "log"); // default log scale
}

function openRunCard(run_id){
  document.querySelectorAll(".runBody.open").forEach(el => el.classList.remove("open"));
  document.querySelectorAll(".runHead .right [data-arrow]").forEach(a => a.textContent = "▼");

  const body = document.querySelector(`#run-${run_id} .runBody`);
  const arrow = document.querySelector(`#run-${run_id} .runHead .right [data-arrow]`);
  if (body) body.classList.add("open");
  if (arrow) arrow.textContent = "▲";
}

function setScale(run_id, mode){
  runState[run_id].scaleMode = mode;
  document.getElementById(`lin-${run_id}`).classList.toggle("active", mode === "linear");
  document.getElementById(`log-${run_id}`).classList.toggle("active", mode === "log");
  redraw(run_id);
}

function ensureChart(run_id){
  const st = runState[run_id];
  if (st.chart) return;

  const ctx = document.getElementById(`chart-${run_id}`).getContext("2d");

  st.chart = new Chart(ctx, {
    type: "line",
    data: { datasets: [] },
    options: {
      responsive: true,
      animation: false,
      parsing: false,
      scales: {
        x: { type: "linear", title: { display: true, text: "t" } },
        y: { type: "logarithmic", title: { display: true, text: "relative error" } }
      },
      plugins: { legend: { display: true } }
    }
  });
}

function redraw(run_id){
  ensureChart(run_id);
  const st = runState[run_id];

  st.chart.options.scales.y.type = (st.scaleMode === "log") ? "logarithmic" : "linear";

  const datasets = [];
  for (const method_id of Object.keys(st.seriesA)){
    const pts = st.seriesA[method_id] || [];
    const meta = st.instancesById[method_id] || {};
    const label = meta.label || method_id;

    datasets.push({
      label: `${label} (analysis)`,
      data: pts,
      borderWidth: 2,
      pointRadius: 0
    });
  }

  st.chart.data.datasets = datasets;
  st.chart.update();
}

/* ====== Summary charts (radar + polar) ====== */
function ensureSummaryCharts(run_id){
  const st = runState[run_id];

  if (!st.rmseRadar){
    const ctxR = document.getElementById(`rmseRadar-${run_id}`).getContext("2d");
    st.rmseRadar = new Chart(ctxR, {
      type: "radar",
      data: {
        labels: [],
        datasets: [
          { label: "RMSE background", data: [], fill: true, pointRadius: 2 },
          { label: "RMSE analysis", data: [], fill: true, pointRadius: 2 }
        ]
      },
      options: {
        responsive: true,
        animation: false,
        plugins: { legend: { display: true } },
        scales: {
          r: {
            beginAtZero: true,
            ticks: { callback: (v) => v }
          }
        }
      }
    });
  }

  if (!st.rmsePolar){
    const ctxP = document.getElementById(`rmsePolar-${run_id}`).getContext("2d");
    st.rmsePolar = new Chart(ctxP, {
      type: "polarArea",
      data: { labels: [], datasets: [{ label: "Improvement (%)", data: [], backgroundColor: [], borderColor: [], borderWidth: 1 }] },
      options: {
        responsive: true,
        animation: false,
        plugins: { legend: { display: true } },
        scales: {
          r: { suggestedMin: 0, suggestedMax: 100, ticks: { callback: (v) => v + "%" } }
        }
      }
    });
  }
}

function safeNum(x){
  const n = Number(x);
  return Number.isFinite(n) ? n : null;
}

function clamp(x, a, b){ return Math.max(a, Math.min(b, x)); }

function updateSummaryCharts(run_id){
  const st = runState[run_id];
  if (!st.rmseRadar || !st.rmsePolar) return;

  const ids = Object.keys(st.instancesById);
  const labels = [];
  const rmseB = [];
  const rmseA = [];

  for (const id of ids){
    const meta = st.instancesById[id] || {};
    const m = st.metrics[id] || {};
    const a = safeNum(m.rmse_a);
    const b = safeNum(m.rmse_b);

    if (a == null && b == null) continue;

    labels.push(meta.label || meta.name || id.slice(0,6));
    rmseA.push(a ?? null);
    rmseB.push(b ?? null);
  }

  // Radar
  st.rmseRadar.data.labels = labels;
  st.rmseRadar.data.datasets[0].data = rmseB.map(v => v ?? null);
  st.rmseRadar.data.datasets[1].data = rmseA.map(v => v ?? null);
  st.rmseRadar.update();

  // Polar
  const perc = [];
  const bgColors = [];
  const brColors = [];

  const validA = rmseA.filter(v => v != null);
  const maxA = validA.length ? Math.max(...validA) : null;

  for (let i=0; i<labels.length; i++){
    const a = rmseA[i];
    const b = rmseB[i];

    let p = 0;
    if (a != null && b != null && b > 0){
      p = (1 - (a / b)) * 100;
    } else if (a != null && maxA != null && maxA > 0){
      p = (1 - (a / maxA)) * 100;
    }
    p = clamp(p, 0, 100);
    perc.push(p);

    const hue = hashStrToHue(labels[i]);
    bgColors.push(rgbaFromHue(hue, 0.55));
    brColors.push(borderFromHue(hue));
  }

  st.rmsePolar.data.labels = labels;
  st.rmsePolar.data.datasets[0].data = perc;
  st.rmsePolar.data.datasets[0].backgroundColor = bgColors;
  st.rmsePolar.data.datasets[0].borderColor = brColors;
  st.rmsePolar.update();
}

/* ====== Run chips + table ====== */
function renderRunChips(run_id){
  const chipWrap = document.getElementById(`runChips-${run_id}`);
  chipWrap.innerHTML = "";

  const st = runState[run_id];

  Object.keys(st.instancesById).forEach(method_id => {
    const meta = st.instancesById[method_id];
    const status = st.statuses[method_id] || "queued";

    let dotClass = "";
    if (status === "completed") dotClass = "ok";
    else if (status === "failed") dotClass = "bad";
    else if (status === "running") dotClass = "warn";

    const chip = document.createElement("div");
    chip.className = "runChip";
    chip.innerHTML = `
      <span class="dot ${dotClass}"></span>
      ${statusIcon(status)}
      <span>${escHtml(meta.label || meta.name || method_id)}</span>
      <span style="color:#64748b;">${escHtml(status)}</span>
    `;
    chipWrap.appendChild(chip);
  });
}

function fmtNum(x, digits=6){
  if (x === null || x === undefined) return "";
  const n = Number(x);
  if (!Number.isFinite(n)) return "";
  return n.toFixed(digits);
}

function updateTable(run_id){
  const st = runState[run_id];
  const tbody = document.getElementById(`tbl-${run_id}`);
  tbody.innerHTML = "";

  Object.keys(st.instancesById).forEach(method_id => {
    const meta = st.instancesById[method_id] || {};
    const status = st.statuses[method_id] || "queued";
    const metrics = st.metrics[method_id] || {};
    const rt = st.runtime[method_id];

    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${escHtml(meta.label || meta.name || method_id)}</strong><br/><small>${escHtml(method_id)}</small></td>
      <td>${escHtml(status)}</td>
      <td>${fmtNum(metrics.rmse_a, 6)}</td>
      <td>${fmtNum(metrics.rmse_b, 6)}</td>
      <td>${fmtNum(metrics.final, 6)}</td>
      <td>${fmtNum(metrics.mean, 6)}</td>
      <td>${fmtNum(metrics.min, 6)}</td>
      <td>${rt != null ? Number(rt).toFixed(3) : ""}</td>
      <td><small>${escHtml(JSON.stringify(meta.params || {}))}</small></td>
    `;
    tbody.appendChild(tr);
  });
}

/* ============================================================================
   Run creation + SSE (UPDATED)
============================================================================ */
async function createRun(){
  if (!METHOD_META){
    setStatus("Methods metadata not loaded yet.");
    return;
  }

  if (selectedInstances.length === 0){
    setStatus("Please add at least one method instance.");
    return;
  }

  const methods = selectedInstances.map(inst => {
    const cleaned = {};
    for (const k of Object.keys(inst.params || {})){
      const v = inst.params[k];
      if (v === "" || v === null || Number.isNaN(v)) continue;
      cleaned[k] = v;
    }
    return {
      id: inst.id,
      name: inst.name,
      label: inst.label,
      params: cleaned
    };
  });

  const payload = {
    model: "lorenz96",
    ensemble_size: parseInt(document.getElementById("ensemble_size").value, 10),
    m: parseInt(document.getElementById("m").value, 10),
    std_obs: parseFloat(document.getElementById("std_obs").value),
    obs_freq: parseFloat(document.getElementById("obs_freq").value),
    end_time: parseFloat(document.getElementById("end_time").value),
    inf_fact: parseFloat(document.getElementById("inf_fact").value),
    methods
  };

  setStatus("Creating run…");

  const res = await fetch("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });

  const data = await res.json();
  if (!res.ok){
    setStatus("Error: " + (data.error || "unknown"));
    return;
  }

  const run_id = data.run_id;
  createRunCard(run_id, payload.model);

  const st = runState[run_id];
  methods.forEach(m => {
    st.instancesById[m.id] = { name: m.name, label: m.label, params: m.params };
    st.statuses[m.id] = "queued";
    st.seriesA[m.id] = [];
  });

  renderRunChips(run_id);
  updateTable(run_id);
  redraw(run_id);

  // summary charts exist but metrics section is closed by default
  ensureSummaryCharts(run_id);
  updateSummaryCharts(run_id);

  setStatus(`Run created: ${run_id.slice(0,8)} (streaming…)`);
  setRunPill(run_id, "queued");

  // Start SSE with resume pointer (since=lastEventId)
  openRunEvents(run_id, (type, d) => {
    // Keep UI responsive even if we receive keepalive/hello
    if (type === "hello" || type === "keepalive") return;

    if (type === "run_started"){
      setRunPill(run_id, "running");
      document.getElementById(`runSub-${run_id}`).textContent = "Running…";
      return;
    }

    if (type === "method_started"){
      st.statuses[d.method_id] = "running";
      st.instancesById[d.method_id] = st.instancesById[d.method_id] || { name: d.name, label: d.label, params: d.params };
      renderRunChips(run_id);
      updateTable(run_id);
      updateSummaryCharts(run_id);
      return;
    }

    if (type === "partial"){
      const method_id = d.method_id;

      if (!st.seriesA[method_id]) st.seriesA[method_id] = [];
      st.seriesA[method_id].push({ x: d.t, y: d.error_a });

      const now = performance.now();
      if (now - st.lastDraw > 220){
        st.lastDraw = now;
        redraw(run_id);
      }
      return;
    }

    if (type === "method_completed"){
      st.statuses[d.method_id] = "completed";
      st.metrics[d.method_id] = d.metrics || {};
      st.runtime[d.method_id] = d.runtime_sec;

      renderRunChips(run_id);
      updateTable(run_id);
      redraw(run_id);
      updateSummaryCharts(run_id);
      return;
    }

    if (type === "run_completed"){
      setRunPill(run_id, "completed");
      document.getElementById(`runSub-${run_id}`).textContent = "Completed";
      renderRunChips(run_id);
      updateTable(run_id);
      redraw(run_id);
      updateSummaryCharts(run_id);

      // openRunEvents will close SSE automatically on terminal events
      return;
    }

    if (type === "run_failed"){
      setRunPill(run_id, "failed");
      document.getElementById(`runSub-${run_id}`).textContent = "Failed: " + (d.error || "unknown error");
      return;
    }

    if (type === "done"){
      // no-op; stream already closed
      return;
    }
  });
}

/* ============================================================================
   Modals
============================================================================ */
const helpModal = document.getElementById("helpModal");
document.getElementById("openHelpBtn").addEventListener("click", () => helpModal.classList.add("open"));
document.getElementById("closeHelpBtn").addEventListener("click", () => helpModal.classList.remove("open"));
helpModal.addEventListener("click", (e) => { if (e.target === helpModal) helpModal.classList.remove("open"); });

const citeModal = document.getElementById("citeModal");
document.getElementById("openCiteBtn").addEventListener("click", () => citeModal.classList.add("open"));
document.getElementById("closeCiteBtn").addEventListener("click", () => citeModal.classList.remove("open"));
citeModal.addEventListener("click", (e) => { if (e.target === citeModal) citeModal.classList.remove("open"); });

const resourcesModal = document.getElementById("resourcesModal");
document.getElementById("openResourcesBtn").addEventListener("click", () => resourcesModal.classList.add("open"));
document.getElementById("closeResourcesBtn").addEventListener("click", () => resourcesModal.classList.remove("open"));
resourcesModal.addEventListener("click", (e) => { if (e.target === resourcesModal) resourcesModal.classList.remove("open"); });

/* ============================================================================
   Buttons
============================================================================ */
document.getElementById("runBtn").addEventListener("click", () => createRun());

document.getElementById("clearMethodsBtn").addEventListener("click", () => {
  selectedInstances.splice(0, selectedInstances.length);
  updateSelectedBadge();
  renderMethodTablets();
  renderMethodChips();
  setStatus("Cleared method instances.");
});

/* ============================================================================
   Init
============================================================================ */
loadMethods();
