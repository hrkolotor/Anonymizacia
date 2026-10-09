"use strict";

(() => {
  // ---------------------------------------------------------------- relácia
  const params = new URLSearchParams(location.search);
  let token = params.get("t") || sessionStorage.getItem("anon-token") || "";
  sessionStorage.setItem("anon-token", token);

  const $ = (id) => document.getElementById(id);
  const el = (tag, attrs = {}, ...kids) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else if (v !== false && v != null) n.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids) if (kid != null) n.append(kid);
    return n;
  };
  const sizeText = (b) => b < 1024 * 1024 ? `${Math.max(1, Math.round(b / 1024))} kB` : `${(b / 1048576).toFixed(1)} MB`;
  const plural = (n, one, few, many) => `${n} ${n === 1 ? one : n >= 2 && n <= 4 ? few : many}`;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  async function api(method, path, body, raw) {
    const opts = { method, headers: { "X-Token": token } };
    if (raw) { opts.body = raw; opts.headers["Content-Type"] = "application/octet-stream"; }
    else if (body !== undefined) { opts.body = JSON.stringify(body); opts.headers["Content-Type"] = "application/json"; }
    let res;
    try { res = await fetch(`/api/${path}`, opts); }
    catch { throw new Error("Aplikácia neodpovedá. Spustite ju znova z ponuky Štart."); }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `Chyba ${res.status}`);
    return data;
  }

  function showError(id, msg) { const e = $(id); e.textContent = msg || ""; e.hidden = !msg; }

  async function poll(job, progressId) {
    for (;;) {
      const st = await api("GET", `jobs/${job}`);
      if (st.state !== "working") return st;
      if (st.progress) $(progressId).textContent = st.progress;
      await sleep(600);
    }
  }

  // ---------------------------------------------------------------- záložky
  const tabs = { anon: $("tab-anon"), restore: $("tab-restore") };
  function selectTab(name) {
    for (const [k, b] of Object.entries(tabs)) {
      b.setAttribute("aria-selected", String(k === name));
      $(`view-${k}`).hidden = k !== name;
    }
  }
  tabs.anon.onclick = () => selectTab("anon");
  tabs.restore.onclick = () => selectTab("restore");

  // ---------------------------------------------------------------- nahrávanie (spoločné)
  async function entriesToFiles(items) {
    const out = [];
    const walk = async (entry) => {
      if (entry.isFile) out.push(await new Promise((res, rej) => entry.file(res, rej)));
      else if (entry.isDirectory) {
        const reader = entry.createReader();
        for (;;) {
          const batch = await new Promise((res, rej) => reader.readEntries(res, rej));
          if (!batch.length) break;
          for (const e of batch) await walk(e);
        }
      }
    };
    for (const it of items) {
      const entry = it.webkitGetAsEntry && it.webkitGetAsEntry();
      if (entry) await walk(entry);
      else if (it.getAsFile()) out.push(it.getAsFile());
    }
    return out;
  }

  function setupDrop(dropId, pickId, onFiles) {
    const drop = $(dropId), pick = $(pickId);
    drop.addEventListener("click", () => pick.click());
    drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick.click(); } });
    pick.addEventListener("change", () => { onFiles([...pick.files]); pick.value = ""; });
    drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
    drop.addEventListener("dragleave", () => drop.classList.remove("over"));
    drop.addEventListener("drop", async (e) => {
      e.preventDefault(); drop.classList.remove("over");
      onFiles(await entriesToFiles([...e.dataTransfer.items]));
    });
  }
  // zabrániť otvoreniu súboru v prehliadači pri minutí zóny
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => e.preventDefault());

  async function upload(jobId, files, errId) {
    const errors = [];
    let status = null;
    for (const f of files) {
      try {
        const res = await api("PUT", `jobs/${jobId}/files?name=${encodeURIComponent(f.name)}`, undefined, await f.arrayBuffer());
        status = res.status;
      } catch (e) { errors.push(e.message); }
    }
    showError(errId, errors.join(" "));
    return status;
  }

  function renderFiles(listId, files, jobId, onChange) {
    const ul = $(listId);
    ul.replaceChildren(...files.map((f) => {
      const ext = f.name.split(".").pop().toUpperCase();
      return el("li", {},
        el("span", { class: "ftype", text: ext }),
        el("span", { class: "fname", text: f.name }),
        el("span", { class: "fsize", text: sizeText(f.size) }),
        el("button", { class: "link", type: "button", text: "Odobrať", "aria-label": `Odobrať ${f.name}`,
          onclick: async () => onChange(await api("DELETE", `jobs/${jobId}/files?name=${encodeURIComponent(f.name)}`)) }));
    }));
  }

  // ---------------------------------------------------------------- anonymizácia
  let anonJob = null;
  let groups = [];
  const excluded = new Set();
  const added = [];

  async function ensureAnonJob() {
    if (!anonJob) anonJob = (await api("POST", "jobs", { kind: "anon" })).id;
    return anonJob;
  }

  function resetReview() {
    $("step-review").hidden = true; $("step-output").hidden = true; $("step-done").hidden = true;
    groups = []; excluded.clear(); added.length = 0; renderAdded();
  }

  function onAnonFiles(status) {
    if (!status) return;
    renderFiles("files-anon", status.files, anonJob, onAnonFiles);
    $("scan").disabled = status.files.length === 0;
    resetReview();
  }

  setupDrop("drop-anon", "pick-anon", async (files) => {
    if (!files.length) return;
    await ensureAnonJob();
    onAnonFiles(await upload(anonJob, files, "err-files"));
  });

  $("scan").onclick = async () => {
    showError("err-scan", ""); showError("err-files", "");
    resetReview();
    $("step-review").hidden = false; $("review").hidden = true; $("scan-working").hidden = false;
    $("scan").disabled = true;
    $("step-review").scrollIntoView({ behavior: "smooth", block: "start" });
    try {
      await api("POST", `jobs/${anonJob}/scan`, {});
      const st = await poll(anonJob, "scan-progress");
      if (st.state === "error") throw new Error(st.error);
      groups = st.groups;
      renderReview(st);
      $("review").hidden = false; $("step-output").hidden = false;
    } catch (e) {
      showError("err-scan", e.message);
    } finally {
      $("scan-working").hidden = true; $("scan").disabled = false;
    }
  };

  let filter = "all";
  document.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => {
    filter = c.dataset.filter;
    document.querySelectorAll(".chip").forEach((x) => x.setAttribute("aria-pressed", String(x === c)));
    renderGroups();
  }));

  function renderReview(st) {
    const files = st.files.length;
    const toCheck = groups.filter((g) => g.check).length;
    $("review-lead").textContent = groups.length
      ? `${plural(groups.length, "údaj", "údaje", "údajov")} na skrytie v ${plural(files, "dokumente", "dokumentoch", "dokumentoch")}`
      : "V dokumentoch sme nenašli žiadne osobné údaje";
    $("chip-check").textContent = `Na overenie (${toCheck})`;
    $("chip-check").hidden = toCheck === 0;
    renderGroups();
    $("warnings-scan").replaceChildren(...st.warnings.map((w) => el("li", { text: w })));
  }

  function context(g) {
    if (!g.context) return null;
    const [before, hit, after] = g.context;
    const clip = (s, left) => (s.length >= 60 ? (left ? "…" + s.slice(-55) : s.slice(0, 55) + "…") : s);
    return el("div", { class: "ctx" }, clip(before.replace(/\s+/g, " "), true), el("mark", { text: hit }),
      clip(after.replace(/\s+/g, " "), false));
  }

  function renderGroups() {
    const byEntity = new Map();
    for (const g of groups) {
      if (filter === "check" && !g.check) continue;
      if (!byEntity.has(g.label)) byEntity.set(g.label, []);
      byEntity.get(g.label).push(g);
    }
    const blocks = [];
    for (const [label, items] of byEntity) {
      const allKept = items.every((g) => excluded.has(g.id));
      blocks.push(el("section", { class: "group" },
        el("h3", {}, el("span", { text: `${label} (${items.length})` }),
          el("button", { class: "link toggle-all", type: "button", text: allKept ? "Skryť všetky" : "Ponechať všetky",
            onclick: () => { items.forEach((g) => (allKept ? excluded.delete(g.id) : excluded.add(g.id))); renderGroups(); } })),
        ...items.map(renderRow)));
    }
    $("groups").replaceChildren(...blocks);
  }

  function renderRow(g) {
    const kept = excluded.has(g.id);
    const id = `cb-${g.id}`;
    const where = g.files.length === 1 ? g.files[0] : `${g.files.length} dokumenty`;
    const box = el("input", { type: "checkbox", id, checked: !kept,
      onchange: (e) => { e.target.checked ? excluded.delete(g.id) : excluded.add(g.id); renderGroups(); document.getElementById(id)?.focus(); } });
    return el("div", { class: kept ? "row kept" : "row" },
      box,
      el("label", { for: id },
        el("span", { class: "value", text: g.text }),
        g.check ? el("span", { class: "flag", text: "overte" }) : null,
        g.others.length ? el("div", { class: "variants", text: `Aj ako: ${g.others.join(", ")}` }) : null,
        el("div", { class: "meta", text: `${plural(g.count, "výskyt", "výskyty", "výskytov")} (${where})` }),
        context(g)),
      el("span", { class: "redact", text: kept ? "ponechá sa" : g.token, "aria-hidden": "true" }));
  }

  function renderAdded() {
    $("added").replaceChildren(...added.map((a, i) => el("li", {},
      el("span", { class: "value", text: a.text }),
      el("span", { class: "redact", text: a.label }),
      el("button", { class: "link", type: "button", text: "Odobrať", onclick: () => { added.splice(i, 1); renderAdded(); } }))));
  }

  $("add-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = $("add-text").value.trim();
    if (!text) return;
    const sel = $("add-entity");
    added.push({ text, entity: sel.value, label: sel.options[sel.selectedIndex].text });
    $("add-text").value = "";
    renderAdded();
  });

  // režim
  document.querySelectorAll('input[name="mode"]').forEach((r) => r.addEventListener("change", () => {
    $("pass").hidden = r.value !== "reversible" || !r.checked;
    showError("err-process", "");
  }));

  $("process").onclick = async () => {
    const mode = document.querySelector('input[name="mode"]:checked')?.value;
    if (!mode) return showError("err-process", "Vyberte, či bude potrebné vrátiť pôvodné údaje.");
    let passphrase = "";
    if (mode === "reversible") {
      passphrase = $("pw1").value;
      if (passphrase.length < 12) return showError("err-process", "Heslo musí mať aspoň 12 znakov.");
      if (passphrase !== $("pw2").value) return showError("err-process", "Heslá sa nezhodujú.");
    }
    showError("err-process", "");
    $("process").disabled = true; $("process-working").hidden = false;
    try {
      await api("POST", `jobs/${anonJob}/process`, {
        mode, passphrase, excluded: [...excluded], added: added.map(({ text, entity }) => ({ text, entity })) });
      const st = await poll(anonJob, "process-progress");
      if (st.state === "error") throw new Error(st.error);
      renderDone(st);
    } catch (e) {
      showError("err-process", e.message);
    } finally {
      $("process").disabled = false; $("process-working").hidden = true;
      $("pw1").value = ""; $("pw2").value = "";
    }
  };

  function renderDone(st) {
    const s = st.summary;
    $("done-lead").textContent = `Nahradených ${plural(s.total, "údaj", "údaje", "údajov")} v ${plural(s.files, "dokumente", "dokumentoch", "dokumentoch")}.`;
    $("tally").replaceChildren(...s.byEntity.map((x) => el("li", {}, `${x.label}: `, el("b", { text: String(x.count) }))));
    $("dl-result").href = `/api/jobs/${anonJob}/download/result?t=${encodeURIComponent(token)}`;
    const rev = s.mode === "reversible";
    $("dl-vault").hidden = !rev; $("vault-note").hidden = !rev;
    if (rev) $("dl-vault").href = `/api/jobs/${anonJob}/download/vault?t=${encodeURIComponent(token)}`;
    $("warnings-done").replaceChildren(...st.warnings.map((w) => el("li", { text: w })));
    $("step-done").hidden = false;
    $("step-done").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  $("again").onclick = async () => {
    if (anonJob) await api("DELETE", `jobs/${anonJob}`).catch(() => {});
    anonJob = null;
    $("files-anon").replaceChildren(); $("scan").disabled = true;
    document.querySelectorAll('input[name="mode"]').forEach((r) => (r.checked = false));
    $("pass").hidden = true;
    resetReview();
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  // ---------------------------------------------------------------- obnova
  let restoreJob = null;
  function onRestoreFiles(status) {
    if (!status) return;
    renderFiles("files-restore", status.files, restoreJob, onRestoreFiles);
    $("vault-state").textContent = status.hasVault ? "Trezor je pridaný." : "Trezor zatiaľ nie je pridaný.";
    $("vault-state").classList.toggle("ok", status.hasVault);
    $("restore").disabled = !(status.hasVault && status.files.length);
    $("restore-done").hidden = true;
  }
  setupDrop("drop-restore", "pick-restore", async (files) => {
    if (!files.length) return;
    if (!restoreJob) restoreJob = (await api("POST", "jobs", { kind: "restore" })).id;
    onRestoreFiles(await upload(restoreJob, files, "err-restore"));
  });

  $("restore").onclick = async () => {
    showError("err-restore", "");
    $("restore").disabled = true; $("restore-working").hidden = false; $("restore-done").hidden = true;
    try {
      await api("POST", `jobs/${restoreJob}/restore`, { passphrase: $("pw-restore").value });
      const st = await poll(restoreJob, "restore-progress");
      if (st.state === "error") throw new Error(st.error);
      $("restore-lead").textContent = `Obnovené: ${plural(st.summary.files, "dokument", "dokumenty", "dokumentov")}.`;
      $("dl-restore").href = `/api/jobs/${restoreJob}/download/result?t=${encodeURIComponent(token)}`;
      $("warnings-restore").replaceChildren(...st.warnings.map((w) => el("li", { text: w })));
      $("restore-done").hidden = false;
    } catch (e) {
      showError("err-restore", e.message);
    } finally {
      $("restore").disabled = false; $("restore-working").hidden = true;
    }
  };

  // ---------------------------------------------------------------- životnosť aplikácie
  const ping = () => api("POST", "ping", {}).catch(() => {});
  ping();
  setInterval(ping, 20000);
  window.addEventListener("pagehide", () => navigator.sendBeacon(`/api/bye?t=${encodeURIComponent(token)}`));
  $("quit").onclick = async () => {
    await api("POST", "quit", {}).catch(() => {});
    $("closed").hidden = false;
  };
})();
