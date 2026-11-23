"use strict";

const byId = (id) => document.getElementById(id);
const keyName = "vidra-snapshot-key";
const incomingKey = new URLSearchParams(location.hash.slice(1)).get("key");
if (incomingKey) {
  sessionStorage.setItem(keyName, incomingKey);
  history.replaceState(null, "", location.pathname);
}
const key = sessionStorage.getItem(keyName);
let entries = [];
let selection = "";
let plan = null;
let retirement = null;
let busy = false;
let lastJob = "";
let catalogLoaded = false;
let repositoryConfigured = false;
const dateFmt = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", year: "numeric" });
const timeFmt = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", timeZoneName: "short" });
const triggerNames = { "manual": "Manual", "pre-upgrade": "Before upgrade", "before-restore": "Before restore", "pre-deploy": "Before deploy", "nightly": "Nightly", "scheduled": "Scheduled" };
const label = (reason) => triggerNames[reason] || reason;
const selected = () => entries.find((entry) => entry.id === selection);

async function api(path, data) {
  const headers = { "X-Vidra-Key": key || "" };
  const options = { headers, cache: "no-store" };
  if (data !== undefined) {
    headers["Content-Type"] = "application/json";
    options.method = "POST";
    options.body = JSON.stringify(data);
  }
  const response = await fetch("/api/" + path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "Operation failed.");
  return result;
}

function notice(message) {
  byId("notice").textContent = message;
  byId("notice").hidden = !message;
}

function fact(list, name, value, mono = false) {
  const row = document.createElement("div");
  const dt = document.createElement("dt");
  const dd = document.createElement("dd");
  dt.textContent = name;
  dd.textContent = value;
  if (mono) dd.className = "mono";
  row.append(dt, dd);
  list.append(row);
}

function renderDetail() {
  const entry = selected();
  byId("detail").hidden = !entry;
  byId("detail-empty").hidden = !!entry;
  byId("create").disabled = busy || !catalogLoaded || !repositoryConfigured;
  if (!entry) return;
  const install = entry.kind === "install";
  const date = new Date(entry.time);
  byId("kind").textContent = install ? "Install snapshot" : "Database archive";
  byId("selected-date").textContent = dateFmt.format(date);
  byId("selected-time").textContent = timeFmt.format(date);
  const facts = byId("facts");
  facts.replaceChildren();
  fact(facts, "Release", entry.release, true);
  fact(facts, "Trigger", label(entry.reason));
  if (install) {
    fact(facts, "Media store", entry.storage === "s3" ? "S3" : "Local volume");
    if (entry.bucket) fact(facts, "Source bucket", entry.bucket, true);
    fact(facts, "Snapshot ID", entry.id.slice(0, 12), true);
  } else {
    fact(facts, "Archive", entry.id, true);
  }
  byId("pins").replaceChildren();
  const componentNames = { core: "Core", user: "Frontend", search: "Search" };
  Object.entries(entry.components || {}).forEach(([name, version]) => fact(byId("pins"), componentNames[name], version, true));
  byId("components").hidden = !byId("pins").childNodes.length;
  byId("legacy-note").hidden = install;
  byId("review").hidden = !install;
  byId("review").disabled = busy;
  byId("retire").hidden = !install;
  byId("retire").disabled = busy;
}

function renderRows() {
  const rows = byId("rows");
  rows.replaceChildren();
  const query = byId("filter").value.trim().toLowerCase();
  const matches = entries.filter((e) => {
    const fields = [e.id, e.release, e.time, e.reason, label(e.reason), e.storage,
      e.kind === "database" ? "database archive" : "install snapshot", dateFmt.format(new Date(e.time))];
    return fields.some((value) => value.toLowerCase().includes(query));
  });
  for (const entry of matches) {
    const tr = document.createElement("tr");
    tr.classList.toggle("selected", entry.id === selection);
    const td = tr.insertCell();
    const button = document.createElement("button");
    button.className = "row-button";
    button.type = "button";
    button.setAttribute("aria-pressed", String(entry.id === selection));
    const date = new Date(entry.time);
    button.textContent = dateFmt.format(date);
    const sub = document.createElement("span");
    sub.textContent = timeFmt.format(date) + (entry.kind === "database" ? " · Database" : "");
    button.append(sub);
    td.append(button);
    const release = tr.insertCell();
    release.className = "mono";
    release.textContent = entry.release;
    tr.insertCell().textContent = label(entry.reason);
    tr.addEventListener("click", () => {
      rows.querySelectorAll(".selected").forEach((previous) => {
        previous.classList.remove("selected");
        previous.querySelector("button").setAttribute("aria-pressed", "false");
      });
      selection = entry.id;
      tr.classList.add("selected");
      button.setAttribute("aria-pressed", "true");
      renderDetail();
    });
    rows.append(tr);
  }
  byId("empty").hidden = !!matches.length;
  byId("empty").textContent = entries.length ? "No backups match this filter." : "Your first snapshot will appear here.";
  renderDetail();
}

async function refresh() {
  byId("refresh").disabled = true;
  try {
    const [list, repository] = await Promise.all([api("snapshots"), api("repository")]);
    repositoryConfigured = repository.configured;
    byId("setup").hidden = repositoryConfigured;
    entries = list.sort((a, b) => Date.parse(b.time) - Date.parse(a.time));
    selection = selected()?.id || entries[0]?.id || "";
    catalogLoaded = true;
    byId("connection").textContent = repositoryConfigured ? "Connected" : "Local archives";
    byId("connection").dataset.state = "ok";
    const full = entries.filter((e) => e.kind === "install").length;
    const db = entries.length - full;
    byId("summary").textContent = full + " install snapshot" + (full === 1 ? "" : "s")
      + " · " + db + " database archive" + (db === 1 ? "" : "s");
    notice("");
    renderRows();
  } catch (error) {
    catalogLoaded = false;
    entries = [];
    selection = "";
    renderRows();
    byId("empty").textContent = "Snapshot history is unavailable.";
    byId("summary").textContent = "Repository unavailable";
    byId("connection").textContent = "Unavailable";
    byId("connection").dataset.state = "error";
    notice(error.message);
  } finally {
    byId("refresh").disabled = false;
  }
}

function elapsed(seconds) {
  const mins = Math.floor(seconds / 60);
  return mins ? mins + "m " + Math.floor(seconds % 60) + "s" : Math.floor(seconds) + "s";
}

async function poll() {
  try {
    const job = await api("status");
    busy = job.state === "running";
    byId("operation").hidden = !job.id;
    if (job.id) {
      byId("operation").dataset.state = job.state;
      const what = { create: "Snapshot", restore: "Rollback", retire: "Retirement" }[job.operation];
      const state = { running: "in progress", failed: "stopped", succeeded: "completed" };
      byId("operation-title").textContent = what + " " + state[job.state];
      byId("operation-message").textContent = job.state === "succeeded" ? "The backup history has been refreshed." : job.events.at(-1);
      const events = job.events.map((message) => {
        const item = document.createElement("li");
        item.textContent = message;
        return item;
      });
      byId("events").replaceChildren(...events);
      byId("elapsed").textContent = elapsed(Math.max(0, (job.ended || Date.now() / 1000) - job.started));
      const current = job.id + job.state;
      if (lastJob !== current && !busy) await refresh();
      lastJob = current;
    }
    renderDetail();
  } catch (error) {
    busy = true;
    renderDetail();
    notice(error.message);
  }
}

function showDialog(id) {
  byId(id).showModal();
  byId(id).querySelector(".cancel").focus();
}

function resetPreview() {
  plan = null;
  byId("confirm-area").hidden = true;
  byId("confirmation").value = "";
  byId("submit-restore").textContent = "Preview rollback";
  byId("submit-restore").disabled = false;
  byId("discard-note").hidden = byId("preserve").checked;
  byId("restore-error").hidden = true;
}

byId("review").onclick = () => {
  const entry = selected();
  byId("target").textContent = "Restore " + entry.release + " from " + dateFmt.format(new Date(entry.time))
    + " at " + timeFmt.format(new Date(entry.time)) + ". The installation will be offline during recovery.";
  byId("bucket-label").hidden = entry.storage !== "s3";
  byId("bucket").required = entry.storage === "s3";
  byId("bucket").value = "";
  byId("preserve").checked = true;
  resetPreview();
  showDialog("restore-dialog");
};
byId("preserve").onchange = resetPreview;
byId("bucket").oninput = resetPreview;
byId("confirmation").oninput = () => {
  byId("submit-restore").disabled = !plan || byId("confirmation").value !== plan.confirmation;
};
byId("create").onclick = () => showDialog("create-dialog");
byId("retire").onclick = () => {
  const entry = selected();
  retirement = null;
  byId("retire-target").textContent = entry.release + " · " + dateFmt.format(new Date(entry.time))
    + " · " + timeFmt.format(new Date(entry.time)) + " · " + entry.id.slice(0, 12);
  byId("retire-confirm-area").hidden = true;
  byId("retire-error").hidden = true;
  byId("retire-confirm").value = "";
  byId("retire-submit").disabled = false;
  byId("retire-submit").textContent = "Preview retirement";
  showDialog("retire-dialog");
};
byId("retire-confirm").oninput = () => {
  byId("retire-submit").disabled = !retirement || byId("retire-confirm").value !== retirement.confirmation;
};
byId("retire-form").onsubmit = async (event) => {
  event.preventDefault();
  const button = byId("retire-submit");
  button.disabled = true;
  try {
    if (retirement) {
      await api("retire", { id: selection, nonce: retirement.nonce, confirmation: byId("retire-confirm").value });
      busy = true;
      byId("retire-dialog").close();
      await poll();
    } else {
      retirement = await api("preview-retire", { id: selection });
      byId("retire-summary").textContent = retirement.summary || "";
      byId("retire-summary").hidden = !retirement.summary;
      byId("retire-phrase").textContent = retirement.confirmation;
      byId("retire-confirm-area").hidden = false;
      byId("retire-error").hidden = true;
      button.textContent = "Retire snapshot";
      byId("retire-confirm").focus();
    }
  } catch (error) {
    retirement = null;
    byId("retire-confirm-area").hidden = true;
    byId("retire-confirm").value = "";
    button.textContent = "Preview retirement";
    byId("retire-error").textContent = error.message;
    byId("retire-error").hidden = false;
  } finally {
    button.disabled = !!retirement && byId("retire-confirm").value !== retirement.confirmation;
  }
};
for (const button of document.querySelectorAll("dialog .close, dialog .cancel")) {
  button.onclick = () => button.closest("dialog").close();
}
byId("create-form").onsubmit = async (event) => {
  event.preventDefault();
  const submit = event.currentTarget.querySelector("button[type=submit]");
  submit.disabled = true;
  try {
    await api("create", {});
    busy = true;
    byId("create-dialog").close();
    await poll();
  } catch (error) {
    byId("create-dialog").close();
    notice(error.message);
  } finally { submit.disabled = false; }
};
byId("restore-form").onsubmit = async (event) => {
  event.preventDefault();
  const button = byId("submit-restore");
  const data = { id: selection, preserve: byId("preserve").checked, bucket: byId("bucket").value.trim() };
  button.disabled = true;
  byId("bucket").disabled = true;
  byId("preserve").disabled = true;
  byId("restore-error").hidden = true;
  try {
    if (plan) {
      await api("restore", { ...data, nonce: plan.nonce, confirmation: byId("confirmation").value });
      busy = true;
      byId("restore-dialog").close();
      await poll();
    } else {
      plan = await api("preview", data);
      byId("restore-summary").textContent = plan.summary || "";
      byId("restore-summary").hidden = !plan.summary;
      byId("phrase").textContent = plan.confirmation;
      byId("confirm-area").hidden = false;
      button.textContent = "Restore snapshot";
      byId("confirmation").focus();
    }
  } catch (error) {
    resetPreview();
    byId("restore-error").textContent = error.message;
    byId("restore-error").hidden = false;
  } finally {
    button.disabled = !!plan && byId("confirmation").value !== plan.confirmation;
    byId("bucket").disabled = false;
    byId("preserve").disabled = false;
  }
};
byId("filter").oninput = renderRows;
byId("refresh").onclick = refresh;
if (!key) {
  notice("Open the private console link printed on the host to access your backups.");
  byId("summary").textContent = "Authentication required";
  byId("connection").textContent = "Locked";
  byId("empty").textContent = "Snapshot history is locked.";
  byId("refresh").disabled = true;
} else {
  refresh();
  (async function updateStatus() {
    await poll();
    setTimeout(updateStatus, busy ? 1500 : 5000);
  })();
}
