const tokenInput = document.getElementById("tokenInput");
const saveTokenBtn = document.getElementById("saveTokenBtn");
const refreshBtn = document.getElementById("refreshBtn");
const flash = document.getElementById("flash");

const syncLimitInput = document.getElementById("syncLimit");
const runNetboxBtn = document.getElementById("runNetboxBtn");
const runBackstageBtn = document.getElementById("runBackstageBtn");
const triggerNetboxScheduleBtn = document.getElementById("triggerNetboxScheduleBtn");
const triggerBackstageScheduleBtn = document.getElementById("triggerBackstageScheduleBtn");
const runLifecycleBtn = document.getElementById("runLifecycleBtn");

function getToken() {
  return localStorage.getItem("cmdb_service_token") || "";
}

function setToken(token) {
  localStorage.setItem("cmdb_service_token", token);
}

function showFlash(message, isError = false) {
  flash.textContent = message;
  flash.classList.remove("hidden");
  flash.style.borderColor = isError ? "#f2b8b5" : "#b9ddff";
  flash.style.background = isError ? "#fff1f1" : "#eef7ff";
}

async function api(path, options = {}) {
  const token = getToken();
  if (!token) {
    throw new Error("Missing service token. Add it above first.");
  }
  const headers = { ...(options.headers || {}), Authorization: `Bearer ${token}` };
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${body}`);
  }
  return response.json();
}

function td(text, cssClass = "") {
  const element = document.createElement("td");
  element.textContent = text == null ? "-" : String(text);
  if (cssClass) element.className = cssClass;
  return element;
}

function renderRows(containerId, rows) {
  const tbody = document.getElementById(containerId);
  tbody.innerHTML = "";
  if (!rows.length) {
    const tr = document.createElement("tr");
    tr.appendChild(td("No data"));
    tbody.appendChild(tr);
    return;
  }
  rows.forEach((row) => tbody.appendChild(row));
}

async function loadSummary() {
  const summary = await api("/dashboard/summary");
  document.getElementById("kpiTotalCis").textContent = summary.totals.cis;
  document.getElementById("kpiRelationships").textContent = summary.totals.relationships;
  document.getElementById("kpiCollisions").textContent = summary.totals.open_collisions;
  document.getElementById("kpiIngest24h").textContent = summary.totals.ingest_events_last_24h;
  document.getElementById("kpiJobsQueued").textContent = summary.sync.jobs_queued;
  document.getElementById("kpiJobsFailed").textContent = summary.sync.jobs_failed;

  document.getElementById("watermarks").textContent = JSON.stringify(summary.sync.netbox_watermarks, null, 2);
  document.getElementById("sources").textContent = JSON.stringify(summary.distributions.by_source, null, 2);
}

async function loadCis() {
  const result = await api("/cis?limit=20");
  const rows = result.items.map((ci) => {
    const tr = document.createElement("tr");
    tr.appendChild(td(ci.name));
    tr.appendChild(td(ci.ci_type));
    tr.appendChild(td(ci.status));
    tr.appendChild(td(ci.source));
    tr.appendChild(td(ci.owner || "-"));
    tr.appendChild(td(ci.updatedAt || ci.updated_at || "-"));
    return tr;
  });
  renderRows("ciRows", rows);
}

async function loadJobs() {
  const jobs = await api("/integrations/jobs?limit=20");
  const rows = jobs.map((job) => {
    const tr = document.createElement("tr");
    tr.appendChild(td(job.id.slice(0, 8), "mono"));
    tr.appendChild(td(job.job_type));
    tr.appendChild(td(job.status));
    tr.appendChild(td(`${job.attempt_count}/${job.max_attempts}`));
    tr.appendChild(td(job.requested_by || "-"));
    tr.appendChild(td(job.created_at));
    return tr;
  });
  renderRows("jobRows", rows);
}

async function loadCollisions() {
  const collisions = await api("/governance/collisions");
  const rows = collisions.slice(0, 20).map((collision) => {
    const tr = document.createElement("tr");
    tr.appendChild(td(collision.id));
    tr.appendChild(td(`${collision.scheme}:${collision.value}`, "mono"));
    tr.appendChild(td(collision.existing_ci_id, "mono"));
    tr.appendChild(td(collision.incoming_ci_id, "mono"));
    tr.appendChild(td(collision.created_at));
    return tr;
  });
  renderRows("collisionRows", rows);
}

async function loadActivity() {
  const activity = await api("/dashboard/activity?limit=20");
  const rows = activity.items.map((event) => {
    const tr = document.createElement("tr");
    tr.appendChild(td(event.created_at));
    tr.appendChild(td(event.event_type));
    tr.appendChild(td(event.ci_name || event.ci_id || "-"));
    tr.appendChild(td(JSON.stringify(event.payload), "mono"));
    return tr;
  });
  renderRows("activityRows", rows);
}

async function refreshAll() {
  try {
    await Promise.all([loadSummary(), loadCis(), loadJobs(), loadCollisions(), loadActivity()]);
    showFlash("Portal refreshed.");
  } catch (error) {
    showFlash(error.message, true);
  }
}

async function runAction(path, message) {
  try {
    const result = await api(path, { method: "POST" });
    showFlash(`${message}: ${JSON.stringify(result)}`);
    await refreshAll();
  } catch (error) {
    showFlash(error.message, true);
  }
}

saveTokenBtn.addEventListener("click", () => {
  const token = tokenInput.value.trim();
  if (!token) {
    showFlash("Token is empty.", true);
    return;
  }
  setToken(token);
  tokenInput.value = "";
  showFlash("Token saved.");
  refreshAll();
});

refreshBtn.addEventListener("click", refreshAll);
runNetboxBtn.addEventListener("click", () => {
  const limit = Number(syncLimitInput.value || 200);
  runAction(`/integrations/netbox/import?asyncJob=true&incremental=true&limit=${limit}`, "NetBox async job queued");
});
runBackstageBtn.addEventListener("click", () => {
  const limit = Number(syncLimitInput.value || 200);
  runAction(`/integrations/backstage/sync?asyncJob=true&limit=${limit}`, "Backstage async job queued");
});
triggerNetboxScheduleBtn.addEventListener("click", () => {
  runAction("/integrations/schedules/netbox-import/trigger", "NetBox schedule triggered");
});
triggerBackstageScheduleBtn.addEventListener("click", () => {
  runAction("/integrations/schedules/backstage-sync/trigger", "Backstage schedule triggered");
});
runLifecycleBtn.addEventListener("click", () => {
  runAction("/lifecycle/run", "Lifecycle run started");
});

tokenInput.value = "";
if (getToken()) {
  refreshAll();
} else {
  showFlash("Add a service token to load secured CMDB data.");
}
