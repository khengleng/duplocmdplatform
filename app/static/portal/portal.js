const tokenInput = document.getElementById("tokenInput");
const saveTokenBtn = document.getElementById("saveTokenBtn");
const refreshBtn = document.getElementById("refreshBtn");
const flash = document.getElementById("flash");
const authPrincipal = document.getElementById("authPrincipal");
const authScopeBadge = document.getElementById("authScope");

const syncLimitInput = document.getElementById("syncLimit");
const runNetboxBtn = document.getElementById("runNetboxBtn");
const runBackstageBtn = document.getElementById("runBackstageBtn");
const triggerNetboxScheduleBtn = document.getElementById("triggerNetboxScheduleBtn");
const triggerBackstageScheduleBtn = document.getElementById("triggerBackstageScheduleBtn");
const runLifecycleBtn = document.getElementById("runLifecycleBtn");
const collisionStatusFilter = document.getElementById("collisionStatusFilter");
const refreshCollisionsBtn = document.getElementById("refreshCollisionsBtn");
const ciFilterQInput = document.getElementById("ciFilterQ");
const ciFilterSourceSelect = document.getElementById("ciFilterSource");
const ciFilterStatusSelect = document.getElementById("ciFilterStatus");
const ciFilterOwnerInput = document.getElementById("ciFilterOwner");
const ciFilterEnvironmentInput = document.getElementById("ciFilterEnvironment");
const ciPageLimitSelect = document.getElementById("ciPageLimit");
const applyCiFiltersBtn = document.getElementById("applyCiFiltersBtn");
const resetCiFiltersBtn = document.getElementById("resetCiFiltersBtn");
const ciPrevPageBtn = document.getElementById("ciPrevPageBtn");
const ciNextPageBtn = document.getElementById("ciNextPageBtn");
const ciPaginationInfo = document.getElementById("ciPaginationInfo");

const relSourceSelect = document.getElementById("relSourceCiId");
const relTargetSelect = document.getElementById("relTargetCiId");
const relTypeInput = document.getElementById("relType");
const createRelationshipBtn = document.getElementById("createRelationshipBtn");
const driftSourceSelect = document.getElementById("driftSourceSelect");
const driftFieldName = document.getElementById("driftFieldName");
const driftFieldType = document.getElementById("driftFieldType");
const driftFieldOwner = document.getElementById("driftFieldOwner");
const resolveDriftBtn = document.getElementById("resolveDriftBtn");
const ciGraphSummary = document.getElementById("ciGraphSummary");
const ciGraphUpstream = document.getElementById("ciGraphUpstream");
const ciGraphDownstream = document.getElementById("ciGraphDownstream");
const exportLimitInput = document.getElementById("exportLimit");
const exportAuditBtn = document.getElementById("exportAuditBtn");
const exportNetboxBtn = document.getElementById("exportNetboxBtn");

let selectedCiId = null;
let currentScope = "viewer";
const ciNameById = new Map();
const defaultCiQueryState = {
  q: "",
  source: "",
  status: "",
  owner: "",
  environment: "",
  limit: 20,
  offset: 0,
};
const ciQueryState = { ...defaultCiQueryState };

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

function ciLabel(ciId) {
  return ciNameById.get(ciId) || ciId;
}

function formatCiOptionLabel(ci) {
  return `${ci.name} (${ci.ci_type}) - ${ci.id}`;
}

function buildCiQueryString() {
  const params = new URLSearchParams();
  params.set("limit", String(ciQueryState.limit));
  params.set("offset", String(ciQueryState.offset));
  if (ciQueryState.q) params.set("q", ciQueryState.q);
  if (ciQueryState.source) params.set("source", ciQueryState.source);
  if (ciQueryState.status) params.set("status", ciQueryState.status);
  if (ciQueryState.owner) params.set("owner", ciQueryState.owner);
  if (ciQueryState.environment) params.set("environment", ciQueryState.environment);
  return params.toString();
}

function syncCiFilterInputsToState() {
  ciQueryState.q = (ciFilterQInput?.value || "").trim();
  ciQueryState.source = ciFilterSourceSelect?.value || "";
  ciQueryState.status = ciFilterStatusSelect?.value || "";
  ciQueryState.owner = (ciFilterOwnerInput?.value || "").trim();
  ciQueryState.environment = (ciFilterEnvironmentInput?.value || "").trim();
  ciQueryState.limit = Number(ciPageLimitSelect?.value || defaultCiQueryState.limit);
}

function resetCiFilterState() {
  if (ciFilterQInput) ciFilterQInput.value = "";
  if (ciFilterSourceSelect) ciFilterSourceSelect.value = "";
  if (ciFilterStatusSelect) ciFilterStatusSelect.value = "";
  if (ciFilterOwnerInput) ciFilterOwnerInput.value = "";
  if (ciFilterEnvironmentInput) ciFilterEnvironmentInput.value = "";
  if (ciPageLimitSelect) ciPageLimitSelect.value = String(defaultCiQueryState.limit);
  Object.assign(ciQueryState, defaultCiQueryState);
}

function updateCiPagination(total, currentItemCount) {
  if (!ciPaginationInfo || !ciPrevPageBtn || !ciNextPageBtn) return;
  const start = total > 0 ? ciQueryState.offset + 1 : 0;
  const end = total > 0 ? ciQueryState.offset + currentItemCount : 0;
  ciPaginationInfo.textContent = `Showing ${start}-${end} of ${total}`;
  ciPrevPageBtn.disabled = ciQueryState.offset <= 0;
  ciNextPageBtn.disabled = ciQueryState.offset + currentItemCount >= total;
}

function renderGraphList(container, relationships) {
  container.innerHTML = "";
  if (!relationships.length) {
    const empty = document.createElement("li");
    empty.className = "graph-empty";
    empty.textContent = "No data";
    container.appendChild(empty);
    return;
  }
  relationships.forEach((rel) => {
    const item = document.createElement("li");
    item.textContent = `${rel.relation_type}: ${ciLabel(rel.source_ci_id)} -> ${ciLabel(rel.target_ci_id)} (${rel.source})`;
    container.appendChild(item);
  });
}

function clearCiSelectionViews() {
  document.getElementById("ciDetail").textContent = "Select a CI row to inspect details.";
  document.getElementById("ciIdentities").textContent = "-";
  document.getElementById("ciDrift").textContent = "-";
  ciGraphSummary.textContent = "Select a CI to load graph relationships.";
  renderGraphList(ciGraphUpstream, []);
  renderGraphList(ciGraphDownstream, []);
  renderRows("relationshipRows", []);
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

function updateScopeUi(scope) {
  currentScope = scope || "viewer";
  authScopeBadge.textContent = currentScope;
  authScopeBadge.className = `badge ${currentScope}`;
  document.querySelectorAll(".operator-action").forEach((el) => {
    el.disabled = currentScope !== "operator";
    if (currentScope !== "operator") {
      el.title = "Operator scope required";
    } else {
      el.title = "";
    }
  });
}

function createCiOption(ci) {
  const option = document.createElement("option");
  option.value = ci.id;
  option.textContent = formatCiOptionLabel(ci);
  return option;
}

function setRelationshipSelectOptions(cis) {
  const previousSource = relSourceSelect.value;
  const previousTarget = relTargetSelect.value;

  relSourceSelect.innerHTML = "";
  relTargetSelect.innerHTML = "";

  const sourcePlaceholder = document.createElement("option");
  sourcePlaceholder.value = "";
  sourcePlaceholder.textContent = "Select source CI";
  relSourceSelect.appendChild(sourcePlaceholder);

  const targetPlaceholder = document.createElement("option");
  targetPlaceholder.value = "";
  targetPlaceholder.textContent = "Select target CI";
  relTargetSelect.appendChild(targetPlaceholder);

  cis.forEach((ci) => {
    relSourceSelect.appendChild(createCiOption(ci));
    relTargetSelect.appendChild(createCiOption(ci));
  });

  if (previousSource && cis.some((ci) => ci.id === previousSource)) {
    relSourceSelect.value = previousSource;
  } else if (selectedCiId && cis.some((ci) => ci.id === selectedCiId)) {
    relSourceSelect.value = selectedCiId;
  }

  if (previousTarget && cis.some((ci) => ci.id === previousTarget)) {
    relTargetSelect.value = previousTarget;
  }
}

async function loadCiOptions() {
  const cis = await api("/pickers/cis?limit=200");
  ciNameById.clear();
  cis.forEach((ci) => {
    ciNameById.set(ci.id, formatCiOptionLabel(ci));
  });
  setRelationshipSelectOptions(cis);
}

async function loadAuthMe() {
  const me = await api("/dashboard/me");
  authPrincipal.textContent = me.principal;
  updateScopeUi(me.scope);
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
  const result = await api(`/cis?${buildCiQueryString()}`);
  const items = Array.isArray(result.items) ? result.items : [];
  const rows = items.map((ci) => {
    const tr = document.createElement("tr");
    tr.classList.add("clickable-row");
    if (selectedCiId === ci.id) tr.classList.add("selected");
    tr.addEventListener("click", () => selectCi(ci.id, { refreshList: true }));
    tr.appendChild(td(ci.name));
    tr.appendChild(td(ci.ci_type));
    tr.appendChild(td(ci.status));
    tr.appendChild(td(ci.source));
    tr.appendChild(td(ci.owner || "-"));
    tr.appendChild(td(ci.updatedAt || ci.updated_at || "-"));
    return tr;
  });
  renderRows("ciRows", rows);
  updateCiPagination(result.total || 0, items.length);

  if ((result.total || 0) === 0) {
    selectedCiId = null;
    clearCiSelectionViews();
    return;
  }

  if (!selectedCiId && items.length > 0) {
    await selectCi(items[0].id, { refreshList: false });
  }
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
  const statusFilter = collisionStatusFilter ? collisionStatusFilter.value : "open";
  const collisions = await api(`/governance/collisions?status=${encodeURIComponent(statusFilter)}`);
  const rows = collisions.slice(0, 20).map((collision) => {
    const tr = document.createElement("tr");
    tr.appendChild(td(collision.id));
    tr.appendChild(td(`${collision.scheme}:${collision.value}`, "mono"));
    tr.appendChild(td(collision.existing_ci_id, "mono"));
    tr.appendChild(td(collision.incoming_ci_id, "mono"));
    tr.appendChild(td(collision.status));
    tr.appendChild(td(collision.resolution_note || "-"));
    tr.appendChild(td(collision.resolved_at || "-"));
    tr.appendChild(td(collision.created_at));
    const actionCell = document.createElement("td");
    if (currentScope === "operator") {
      if (collision.status === "OPEN") {
        const resolveBtn = document.createElement("button");
        resolveBtn.className = "btn";
        resolveBtn.textContent = "Resolve";
        resolveBtn.addEventListener("click", async () => {
          const note = window.prompt("Resolution note for this collision:");
          if (note == null || !note.trim()) return;
          await runAction(
            `/governance/collisions/${collision.id}/resolve`,
            "Collision resolved",
            "POST",
            { resolution_note: note.trim() },
          );
        });
        actionCell.appendChild(resolveBtn);
      } else {
        const reopenBtn = document.createElement("button");
        reopenBtn.className = "btn";
        reopenBtn.textContent = "Reopen";
        reopenBtn.addEventListener("click", async () => {
          const note = window.prompt("Reopen note for this collision:");
          if (note == null || !note.trim()) return;
          await runAction(
            `/governance/collisions/${collision.id}/reopen`,
            "Collision reopened",
            "POST",
            { reopen_note: note.trim() },
          );
        });
        actionCell.appendChild(reopenBtn);
      }
    } else {
      actionCell.textContent = "Read-only";
    }
    tr.appendChild(actionCell);
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

async function loadRelationshipsForSelectedCi() {
  if (!selectedCiId) {
    renderRows("relationshipRows", []);
    return;
  }
  const relationships = await api(`/relationships?ci_id=${encodeURIComponent(selectedCiId)}&limit=50`);
  const rows = relationships.map((rel) => {
    const tr = document.createElement("tr");
    tr.appendChild(td(rel.id));
    tr.appendChild(td(ciLabel(rel.source_ci_id), "mono"));
    tr.appendChild(td(ciLabel(rel.target_ci_id), "mono"));
    tr.appendChild(td(rel.relation_type));
    tr.appendChild(td(rel.source));
    const actionCell = document.createElement("td");
    if (currentScope === "operator") {
      const btn = document.createElement("button");
      btn.className = "btn";
      btn.textContent = "Delete";
      btn.addEventListener("click", async () => {
        await runAction(`/relationships/${rel.id}`, "Relationship deleted", "DELETE", {});
      });
      actionCell.appendChild(btn);
    } else {
      actionCell.textContent = "Read-only";
    }
    tr.appendChild(actionCell);
    return tr;
  });
  renderRows("relationshipRows", rows);
}

async function selectCi(ciId, options = {}) {
  const refreshList = options.refreshList === true;
  selectedCiId = ciId;
  if ([...relSourceSelect.options].some((option) => option.value === ciId)) {
    relSourceSelect.value = ciId;
  }
  const requests = [loadCiDetail(ciId), loadCiDrift(ciId), loadCiGraph(ciId), loadRelationshipsForSelectedCi()];
  if (refreshList) {
    requests.push(loadCis());
  }
  await Promise.all(requests);
}

async function loadCiDetail(ciId) {
  const detail = await api(`/cis/${encodeURIComponent(ciId)}/detail`);
  if (detail?.ci?.id) {
    ciNameById.set(detail.ci.id, formatCiOptionLabel(detail.ci));
  }
  document.getElementById("ciDetail").textContent = JSON.stringify(detail.ci, null, 2);
  document.getElementById("ciIdentities").textContent = JSON.stringify(detail.identities, null, 2);
}

async function loadCiDrift(ciId) {
  const drift = await api(`/cis/${encodeURIComponent(ciId)}/drift`);
  document.getElementById("ciDrift").textContent = JSON.stringify(drift, null, 2);
}

async function loadCiGraph(ciId) {
  const graph = await api(`/cis/${encodeURIComponent(ciId)}/graph`);
  const upstream = Array.isArray(graph.upstream) ? graph.upstream : [];
  const downstream = Array.isArray(graph.downstream) ? graph.downstream : [];
  ciGraphSummary.textContent = `CI ${ciLabel(ciId)} has ${upstream.length} upstream and ${downstream.length} downstream relationships.`;
  renderGraphList(ciGraphUpstream, upstream);
  renderGraphList(ciGraphDownstream, downstream);
}

function selectedDriftFields() {
  const fields = [];
  if (driftFieldName.checked) fields.push("name");
  if (driftFieldType.checked) fields.push("ci_type");
  if (driftFieldOwner.checked) fields.push("owner");
  return fields;
}

async function applyCiFilters(options = {}) {
  syncCiFilterInputsToState();
  if (options.resetOffset !== false) {
    ciQueryState.offset = 0;
  }
  await loadCis();
}

async function authFetch(path) {
  const token = getToken();
  if (!token) {
    throw new Error("Missing service token. Add it above first.");
  }
  const response = await fetch(path, {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${body}`);
  }
  return response;
}

function timestampToken() {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

async function downloadExport(path, filename, asPrettyJson = false) {
  const response = await authFetch(path);
  let blob;
  if (asPrettyJson) {
    const payload = await response.json();
    blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  } else {
    blob = await response.blob();
  }
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(objectUrl);
}

async function refreshAll() {
  try {
    const hadSelectedCi = Boolean(selectedCiId);
    await loadAuthMe();
    await loadCiOptions();
    await Promise.all([loadSummary(), loadJobs(), loadCollisions(), loadActivity(), loadCis()]);
    if (selectedCiId && hadSelectedCi) {
      await Promise.all([
        loadCiDetail(selectedCiId),
        loadCiDrift(selectedCiId),
        loadCiGraph(selectedCiId),
        loadRelationshipsForSelectedCi(),
      ]);
    }
    showFlash("Portal refreshed.");
  } catch (error) {
    showFlash(error.message, true);
  }
}

async function runAction(path, message, method = "POST", body = null) {
  try {
    const result = await api(path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
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
if (applyCiFiltersBtn) {
  applyCiFiltersBtn.addEventListener("click", () => {
    applyCiFilters().catch((error) => showFlash(error.message, true));
  });
}
if (resetCiFiltersBtn) {
  resetCiFiltersBtn.addEventListener("click", () => {
    resetCiFilterState();
    applyCiFilters().catch((error) => showFlash(error.message, true));
  });
}
if (ciPrevPageBtn) {
  ciPrevPageBtn.addEventListener("click", () => {
    ciQueryState.offset = Math.max(0, ciQueryState.offset - ciQueryState.limit);
    loadCis().catch((error) => showFlash(error.message, true));
  });
}
if (ciNextPageBtn) {
  ciNextPageBtn.addEventListener("click", () => {
    ciQueryState.offset += ciQueryState.limit;
    loadCis().catch((error) => showFlash(error.message, true));
  });
}
[ciFilterQInput, ciFilterOwnerInput, ciFilterEnvironmentInput].forEach((input) => {
  if (!input) return;
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      applyCiFilters().catch((error) => showFlash(error.message, true));
    }
  });
});
[ciFilterSourceSelect, ciFilterStatusSelect, ciPageLimitSelect].forEach((control) => {
  if (!control) return;
  control.addEventListener("change", () => {
    applyCiFilters().catch((error) => showFlash(error.message, true));
  });
});
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
if (exportAuditBtn) {
  exportAuditBtn.addEventListener("click", async () => {
    try {
      const limit = Number(exportLimitInput?.value || 1000);
      await downloadExport(`/audit/export?limit=${limit}`, `cmdb-audit-${timestampToken()}.ndjson`);
      showFlash("Audit export downloaded.");
    } catch (error) {
      showFlash(error.message, true);
    }
  });
}
if (exportNetboxBtn) {
  exportNetboxBtn.addEventListener("click", async () => {
    try {
      const limit = Number(exportLimitInput?.value || 1000);
      await downloadExport(`/integrations/netbox/export?limit=${limit}`, `cmdb-netbox-${timestampToken()}.json`, true);
      showFlash("NetBox export downloaded.");
    } catch (error) {
      showFlash(error.message, true);
    }
  });
}
if (refreshCollisionsBtn) {
  refreshCollisionsBtn.addEventListener("click", () => {
    loadCollisions().catch((error) => showFlash(error.message, true));
  });
}
if (collisionStatusFilter) {
  collisionStatusFilter.addEventListener("change", () => {
    loadCollisions().catch((error) => showFlash(error.message, true));
  });
}

createRelationshipBtn.addEventListener("click", async () => {
  const sourceCi = relSourceSelect.value;
  const targetCi = relTargetSelect.value;
  const relationType = relTypeInput.value.trim();
  if (!sourceCi || !targetCi || !relationType) {
    showFlash("Source CI, Target CI, and Relation Type are required.", true);
    return;
  }
  await runAction("/relationships", "Relationship created", "POST", {
    source_ci_id: sourceCi,
    target_ci_id: targetCi,
    relation_type: relationType,
    source: "portal",
  });
});

resolveDriftBtn.addEventListener("click", async () => {
  if (!selectedCiId) {
    showFlash("Select a CI first.", true);
    return;
  }
  const fields = selectedDriftFields();
  if (!fields.length) {
    showFlash("Select at least one field to resolve.", true);
    return;
  }

  await runAction(
    `/cis/${encodeURIComponent(selectedCiId)}/drift/resolve`,
    "Drift resolution applied",
    "POST",
    {
      source: driftSourceSelect.value,
      fields,
    },
  );
});

tokenInput.value = "";
resetCiFilterState();
if (getToken()) {
  refreshAll();
} else {
  showFlash("Add a service token to load secured CMDB data.");
}
