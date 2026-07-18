const BUILTIN_CATEGORY_KEYS = ["business", "personal", "uncategorized", "ignore"];

const state = {
  category: "all",
  query: "",
  allThreads: [],
  threads: [],
  counts: { business: 0, personal: 0, uncategorized: 0, ignore: 0 },
  selectedId: null,
  selected: null,
  messagesRequestId: 0,
  messagesLimit: 10,
  messagesHasMore: false,
  flyoutChatId: null,
  hasLoaded: false,
  loadCardCollapsed: false,
  availableThreads: null,
  loadMode: "count",
  settingsDraftCustom: [],
  settings: {
    apple_intelligence_enabled: false,
    apple_intelligence_shortcut: "MessageManager Summarize",
    summary_days: 30,
    thread_limit: 50,
    thread_load_mode: "count",
    thread_activity_value: 6,
    thread_activity_unit: "months",
    auto_load_on_start: false,
    default_message_limit: 10,
    custom_categories: [],
    enabled_categories: [...BUILTIN_CATEGORY_KEYS],
    hidden_from_default: ["ignore"],
  },
  appleIntelligence: null,
  platform: null,
  logs: null,
  busy: false,
};

const els = {
  search: document.getElementById("search"),
  categorySummary: document.getElementById("category-summary"),
  threadList: document.getElementById("thread-list"),
  accessBanner: document.getElementById("access-banner"),
  emptyState: document.getElementById("empty-state"),
  threadView: document.getElementById("thread-view"),
  threadTitle: document.getElementById("thread-title"),
  threadMeta: document.getElementById("thread-meta"),
  threadCategoryLabel: document.getElementById("thread-category-label"),
  categoryFlyout: document.getElementById("category-flyout"),
  categorySegmented: document.getElementById("category-segmented"),
  threadLimitMaxLabel: document.getElementById("thread-limit-max-label"),
  summarizeBtn: document.getElementById("summarize-btn"),
  summaryDays: document.getElementById("summary-days"),
  summaryPanel: document.getElementById("summary-panel"),
  summaryText: document.getElementById("summary-text"),
  summaryMeta: document.getElementById("summary-meta"),
  summaryTopics: document.getElementById("summary-topics"),
  summaryHighlights: document.getElementById("summary-highlights"),
  summaryMethod: document.getElementById("summary-method"),
  messagesPanel: document.getElementById("messages-panel"),
  messagesList: document.getElementById("messages-list"),
  messagesCount: document.getElementById("messages-count"),
  messagesLoadFlyout: document.getElementById("messages-load-flyout"),
  aiToggle: document.getElementById("ai-toggle"),
  aiStatus: document.getElementById("ai-status"),
  statusBar: document.getElementById("status-bar"),
  statusPlatform: document.getElementById("status-platform"),
  statusText: document.getElementById("status-text"),
  statusPercent: document.getElementById("status-percent"),
  statusProgressWrap: document.getElementById("status-progress-wrap"),
  statusProgress: document.getElementById("status-progress"),
  openLogsBtn: document.getElementById("open-logs-btn"),
  quitAppBtn: document.getElementById("quit-app-btn"),
  threadLimit: document.getElementById("thread-limit"),
  threadLimitValue: document.getElementById("thread-limit-value"),
  loadThreadsBtn: document.getElementById("load-threads-btn"),
  loadCard: document.getElementById("load-card"),
  loadCardToggle: document.getElementById("load-card-toggle"),
  loadCountControls: document.getElementById("load-count-controls"),
  loadActivityControls: document.getElementById("load-activity-controls"),
  threadActivityValue: document.getElementById("thread-activity-value"),
  threadActivityUnit: document.getElementById("thread-activity-unit"),
  settingsBtn: document.getElementById("settings-btn"),
  settingsModal: document.getElementById("settings-modal"),
  settingsForm: document.getElementById("settings-form"),
  settingAutoLoad: document.getElementById("setting-auto-load"),
  settingThreadLimit: document.getElementById("setting-thread-limit"),
  settingMessageLimit: document.getElementById("setting-message-limit"),
  settingSummaryDays: document.getElementById("setting-summary-days"),
  settingAiShortcut: document.getElementById("setting-ai-shortcut"),
  settingActivityValue: document.getElementById("setting-activity-value"),
  settingActivityUnit: document.getElementById("setting-activity-unit"),
  settingCountFields: document.getElementById("setting-count-fields"),
  settingActivityFields: document.getElementById("setting-activity-fields"),
  settingEnabledCategories: document.getElementById("setting-enabled-categories"),
  settingHiddenCategories: document.getElementById("setting-hidden-categories"),
  settingCustomCategories: document.getElementById("setting-custom-categories"),
  settingNewCategory: document.getElementById("setting-new-category"),
  settingAddCategory: document.getElementById("setting-add-category"),
  appVersionLabel: document.getElementById("app-version-label"),
  settingsCurrentVersion: document.getElementById("settings-current-version"),
  permissionsCard: document.getElementById("permissions-card"),
  permissionsText: document.getElementById("permissions-text"),
  openPrivacyBtn: document.getElementById("open-privacy-btn"),
  recheckPermissionsBtn: document.getElementById("recheck-permissions-btn"),
  updateBanner: document.getElementById("update-banner"),
  updateBannerText: document.getElementById("update-banner-text"),
  updateBannerBtn: document.getElementById("update-banner-btn"),
  updateStatus: document.getElementById("update-status"),
  checkUpdatesBtn: document.getElementById("check-updates-btn"),
  installUpdateBtn: document.getElementById("install-update-btn"),
};

state.appVersion = "1.0.4";
state.updateInfo = null;

function formatWhen(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function categoryLabel(cat) {
  if (cat === "business") return "Business";
  if (cat === "personal") return "Personal";
  if (cat === "ignore") return "Ignore";
  if (cat === "uncategorized" || !cat) return "Uncategorized";
  const custom = (state.settings.custom_categories || []).find((c) => c.id === cat);
  if (custom?.label) return custom.label;
  return String(cat)
    .replace(/_/g, " ")
    .replace(/\b\w/g, (ch) => ch.toUpperCase());
}

function knownCategoryIds() {
  const custom = (state.settings.custom_categories || []).map((c) => c.id);
  return new Set([...BUILTIN_CATEGORY_KEYS, ...custom]);
}

function allCategoryDefs() {
  const custom = state.settingsDraftCustom.length
    ? state.settingsDraftCustom
    : state.settings.custom_categories || [];
  return [
    ...BUILTIN_CATEGORY_KEYS.map((id) => ({
      id,
      label: categoryLabel(id),
      builtin: true,
    })),
    ...custom.map((c) => ({ id: c.id, label: c.label, builtin: false })),
  ];
}

function enabledCategories() {
  const known = knownCategoryIds();
  const list = state.settings.enabled_categories;
  const picked = Array.isArray(list) ? list.filter((c) => known.has(c)) : [];
  const out = picked.length ? picked : [...BUILTIN_CATEGORY_KEYS];
  if (!out.includes("uncategorized")) out.unshift("uncategorized");
  return out;
}

function activityToDays(value, unit) {
  const n = Math.max(1, Math.min(100, Math.round(Number(value) || 1)));
  return unit === "years" ? n * 365 : n * 30;
}

function syncLoadModeUI(mode = state.loadMode) {
  state.loadMode = mode === "activity" ? "activity" : "count";
  document.querySelectorAll("[data-load-mode]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.loadMode === state.loadMode);
  });
  els.loadCountControls?.classList.toggle("hidden", state.loadMode !== "count");
  els.loadActivityControls?.classList.toggle("hidden", state.loadMode !== "activity");
  syncThreadLimitLabel();
}

function syncSettingsLoadModeUI(mode) {
  const m = mode === "activity" ? "activity" : "count";
  document.querySelectorAll("[data-setting-load-mode]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.settingLoadMode === m);
  });
  els.settingCountFields?.classList.toggle("hidden", m !== "count");
  els.settingActivityFields?.classList.toggle("hidden", m !== "activity");
}

function hiddenFromDefault() {
  const enabled = new Set(enabledCategories());
  const list = state.settings.hidden_from_default || [];
  return (Array.isArray(list) ? list : []).filter((c) => enabled.has(c));
}

function defaultMessageLimit() {
  const raw = Number(state.settings.default_message_limit);
  if (!Number.isFinite(raw)) return 10;
  return Math.max(1, Math.min(500, Math.round(raw)));
}

function currentSummaryDays() {
  const raw = Number(els.summaryDays?.value);
  if (!Number.isFinite(raw)) return state.settings.summary_days || 30;
  return Math.max(1, Math.min(3650, Math.round(raw)));
}

function maxThreadLimit() {
  const available = Number(state.availableThreads);
  if (Number.isFinite(available) && available > 0) {
    return Math.round(available);
  }
  return 50;
}

function minThreadLimit() {
  return Math.min(5, maxThreadLimit());
}

function currentThreadLimit() {
  const raw = Number(els.threadLimit?.value);
  const min = minThreadLimit();
  const max = maxThreadLimit();
  if (!Number.isFinite(raw)) {
    return Math.max(min, Math.min(state.settings.thread_limit || 50, max));
  }
  return Math.max(min, Math.min(max, Math.round(raw)));
}

function syncThreadLimitBounds() {
  const min = minThreadLimit();
  const max = maxThreadLimit();
  if (!els.threadLimit) return;
  els.threadLimit.min = String(min);
  els.threadLimit.max = String(max);
  if (els.threadLimitMaxLabel) {
    els.threadLimitMaxLabel.textContent = String(max);
  }
  const value = currentThreadLimit();
  els.threadLimit.value = String(value);
  syncThreadLimitLabel();
}

function setAvailableThreads(count) {
  const n = Number(count);
  if (!Number.isFinite(n) || n < 0) return;
  state.availableThreads = Math.round(n);
  syncThreadLimitBounds();
}

function syncThreadLimitLabel() {
  if (state.loadMode === "activity") {
    const value = Math.max(1, Number(els.threadActivityValue?.value) || 6);
    const unit = els.threadActivityUnit?.value === "years" ? "y" : "mo";
    if (els.threadLimitValue) els.threadLimitValue.textContent = `${value}${unit}`;
    return;
  }
  const value = currentThreadLimit();
  if (els.threadLimitValue) els.threadLimitValue.textContent = String(value);
  if (els.threadLimit) els.threadLimit.value = String(value);
}

function applyLocalFilters() {
  const counts = { business: 0, personal: 0, uncategorized: 0, ignore: 0 };
  for (const t of state.allThreads) {
    const cat = t.category || "uncategorized";
    counts[cat] = (counts[cat] || 0) + 1;
  }
  state.counts = counts;

  let list = state.allThreads.slice();
  const hidden = new Set(hiddenFromDefault());
  if (state.category && state.category !== "all") {
    list = list.filter((t) => (t.category || "uncategorized") === state.category);
  } else if (hidden.size) {
    list = list.filter((t) => !hidden.has(t.category || "uncategorized"));
  }
  if (state.query) {
    const needle = state.query.toLowerCase();
    list = list.filter(
      (t) =>
        (t.display_name || "").toLowerCase().includes(needle) ||
        (t.chat_identifier || "").toLowerCase().includes(needle) ||
        (t.preview || "").toLowerCase().includes(needle) ||
        (t.participants || []).some((p) => (p || "").toLowerCase().includes(needle)) ||
        (t.participant_names || []).some((p) => (p || "").toLowerCase().includes(needle))
    );
  }
  state.threads = list;
  renderCategorySummary();
  renderThreadList();
}

function setStatus(message, percent = null, { busy = false } = {}) {
  state.busy = busy;
  els.statusBar.classList.toggle("busy", busy);
  els.statusText.textContent = message || "Ready";

  if (busy && percent != null) {
    const pct = Math.max(0, Math.min(100, Number(percent) || 0));
    els.statusProgressWrap.classList.remove("hidden");
    els.statusPercent.classList.remove("hidden");
    els.statusProgress.style.width = `${pct}%`;
    els.statusPercent.textContent = `${Math.round(pct)}%`;
  } else if (busy) {
    els.statusProgressWrap.classList.remove("hidden");
    els.statusPercent.classList.add("hidden");
    els.statusProgress.style.width = "35%";
  } else {
    els.statusProgressWrap.classList.add("hidden");
    els.statusPercent.classList.add("hidden");
    els.statusProgress.style.width = "0%";
  }
}

function clearStatus(message = "Ready") {
  setStatus(message, null, { busy: false });
}

async function api(path, options) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options?.headers || {}) },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail || res.statusText || "Request failed";
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

function readSse(url, { onProgress } = {}) {
  return new Promise(async (resolve, reject) => {
    try {
      const res = await fetch(url);
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        const detail = data.detail || res.statusText || "Request failed";
        throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      }
      if (!res.body) {
        throw new Error("Streaming is not supported in this browser.");
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let splitAt;
        while ((splitAt = buffer.indexOf("\n\n")) >= 0) {
          const chunk = buffer.slice(0, splitAt);
          buffer = buffer.slice(splitAt + 2);
          const line = chunk
            .split("\n")
            .map((l) => l.trim())
            .find((l) => l.startsWith("data:"));
          if (!line) continue;
          const payload = JSON.parse(line.slice(5).trim());
          if (payload.type === "progress") {
            onProgress?.(payload.message || "Working…", payload.percent);
          } else if (payload.type === "result") {
            resolve(payload);
            return;
          } else if (payload.type === "error") {
            throw new Error(payload.detail || "Request failed");
          }
        }
      }
      reject(new Error("Stream ended before a result was received."));
    } catch (err) {
      reject(err);
    }
  });
}

function renderCategorySummary() {
  if (!els.categorySummary) return;
  const enabled = enabledCategories();
  const { counts } = state;
  const visibleTotal = enabled.reduce((sum, key) => sum + (counts[key] || 0), 0);
  const chips = [
    { key: "all", label: "All", count: visibleTotal },
    ...enabled.map((key) => ({
      key,
      label: key === "uncategorized" ? "Unset" : categoryLabel(key),
      count: counts[key] || 0,
    })),
  ];
  els.categorySummary.innerHTML = chips
    .map(
      (chip) => `
      <button class="filter ${state.category === chip.key ? "active" : ""}" data-category="${chip.key}">
        ${escapeHtml(chip.label)} <span>${chip.count}</span>
      </button>`
    )
    .join("");
  els.categorySummary.querySelectorAll(".filter").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.category = btn.dataset.category || "all";
      if (state.hasLoaded) applyLocalFilters();
      else renderCategorySummary();
    });
  });
}

function renderCategoryControls() {
  const enabled = enabledCategories();
  if (els.categorySegmented) {
    els.categorySegmented.innerHTML = enabled
      .map(
        (key) =>
          `<button type="button" data-set-category="${key}">${escapeHtml(
            key === "uncategorized" ? "Unset" : categoryLabel(key)
          )}</button>`
      )
      .join("");
    els.categorySegmented.querySelectorAll("[data-set-category]").forEach((btn) => {
      btn.addEventListener("click", () => setCategory(btn.dataset.setCategory));
    });
  }
  if (els.categoryFlyout) {
    els.categoryFlyout.innerHTML = enabled
      .map(
        (key) =>
          `<button type="button" data-flyout-category="${key}" role="menuitem">${escapeHtml(
            key === "uncategorized" ? "Unset" : categoryLabel(key)
          )}</button>`
      )
      .join("");
    els.categoryFlyout.querySelectorAll("[data-flyout-category]").forEach((btn) => {
      btn.addEventListener("click", async (event) => {
        event.preventDefault();
        event.stopPropagation();
        const chatId = state.flyoutChatId || state.selectedId;
        const category = btn.dataset.flyoutCategory;
        hideCategoryFlyout();
        if (!chatId || !category) return;
        if (state.selectedId !== chatId) selectThread(chatId);
        await setCategory(category);
      });
    });
  }
  if (state.selected) syncCategoryButtons(state.selected.category || "uncategorized");
}

function renderPlatformChip() {
  const platform = state.platform;
  if (!platform) {
    els.statusPlatform.textContent = "Detecting Mac…";
    els.statusPlatform.className = "status-chip";
    return;
  }
  const mode = platform.apple_silicon
    ? state.settings.apple_intelligence_enabled
      ? "Apple Intelligence"
      : "Extractive"
    : "Extractive";
  els.statusPlatform.textContent = `${platform.label} · ${mode}`;
  els.statusPlatform.className = `status-chip ${platform.apple_silicon ? "silicon" : "intel"}`;
  els.statusPlatform.title = platform.chip || "";
}

function renderAiStatus() {
  const ai = state.appleIntelligence;
  const platform = state.platform;
  const enabled = !!state.settings.apple_intelligence_enabled;
  const silicon = !!platform?.apple_silicon;

  els.aiToggle.checked = enabled && silicon;
  els.aiToggle.disabled = !silicon;

  if (!ai || !platform) {
    els.aiStatus.textContent = "Checking this Mac…";
    els.aiStatus.className = "ai-status";
    return;
  }

  if (!silicon) {
    els.aiStatus.textContent =
      "Intel Mac detected — summaries use local extractive mode.";
    els.aiStatus.className = "ai-status warn";
    return;
  }

  if (enabled && ai.available) {
    els.aiStatus.textContent = `On · Apple Silicon will use Shortcut “${ai.shortcut_name}”`;
    els.aiStatus.className = "ai-status ready";
    return;
  }

  if (enabled && !ai.shortcut_installed) {
    els.aiStatus.textContent = `On · create Shortcut “${ai.shortcut_name}” (Text → Summarize → Stop and output)`;
    els.aiStatus.className = "ai-status warn";
    return;
  }

  if (!enabled) {
    els.aiStatus.textContent = ai.available
      ? "Off · Apple Silicon will use local extractive mode"
      : `Off · Apple Silicon ready; install Shortcut “${ai.shortcut_name}” for AI`;
    els.aiStatus.className = "ai-status";
    return;
  }

  els.aiStatus.textContent = (ai.reasons && ai.reasons[0]) || "Apple Intelligence unavailable.";
  els.aiStatus.className = "ai-status warn";
}

function renderThreadList() {
  const { threads, selectedId, hasLoaded } = state;
  if (!hasLoaded) {
    els.threadList.innerHTML = `<p class="loading">Choose how many conversations to load, then press Start loading.</p>`;
    return;
  }
  if (!threads.length) {
    els.threadList.innerHTML = `<p class="loading">No conversations match this filter.</p>`;
    return;
  }

  els.threadList.innerHTML = threads
    .map((t) => {
      const active = t.id === selectedId ? "active" : "";
      const preview = (t.preview || "").trim();
      const count = t.message_count || 0;
      const subtitle = preview
        ? preview
        : `${count.toLocaleString()} messages`;
      const cat = t.category || "uncategorized";
      return `
        <button class="thread-item ${active}" data-id="${t.id}" role="listitem">
          <div class="top">
            <span class="name">${escapeHtml(t.display_name || "Untitled")}</span>
            <span class="when">${escapeHtml(formatWhen(t.last_message_at))}</span>
          </div>
          <p class="preview">${escapeHtml(subtitle)}</p>
          <span
            class="badge ${cat} clickable"
            data-category-badge="${t.id}"
            data-category="${cat}"
            title="Click to change category"
          >${categoryLabel(cat)}</span>
        </button>
      `;
    })
    .join("");

  els.threadList.querySelectorAll(".thread-item").forEach((btn) => {
    btn.addEventListener("click", () => selectThread(Number(btn.dataset.id)));
  });
  els.threadList.querySelectorAll("[data-category-badge]").forEach((badge) => {
    badge.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const chatId = Number(badge.dataset.categoryBadge);
      if (!Number.isFinite(chatId)) return;
      // selectThread re-renders the list and destroys this badge node, so
      // capture its screen position first, then re-find the new badge.
      const clickRect = badge.getBoundingClientRect();
      selectThread(chatId);
      const nextBadge = els.threadList.querySelector(
        `[data-category-badge="${chatId}"]`
      );
      openCategoryFlyout(nextBadge, chatId, clickRect);
    });
  });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function hideCategoryFlyout() {
  if (!els.categoryFlyout) return;
  els.categoryFlyout.classList.add("hidden");
  state.flyoutChatId = null;
  if (els.threadCategoryLabel) {
    els.threadCategoryLabel.setAttribute("aria-expanded", "false");
  }
}

function positionCategoryFlyout(rect) {
  if (!els.categoryFlyout || !rect) return;
  const pad = 8;
  const menuWidth = els.categoryFlyout.offsetWidth || 200;
  const menuHeight = els.categoryFlyout.offsetHeight || 40;
  let left = rect.left;
  if (left + menuWidth > window.innerWidth - pad) {
    left = Math.max(pad, window.innerWidth - menuWidth - pad);
  }
  let top = rect.bottom + 6;
  if (top + menuHeight > window.innerHeight - pad) {
    top = Math.max(pad, rect.top - menuHeight - 6);
  }
  els.categoryFlyout.style.left = `${Math.max(pad, left)}px`;
  els.categoryFlyout.style.top = `${Math.max(pad, top)}px`;
}

function openCategoryFlyout(anchor, chatId, fallbackRect = null) {
  if (!els.categoryFlyout) return;
  state.flyoutChatId = chatId;
  // Measure before showing can return 0×0; show first, then position.
  els.categoryFlyout.classList.remove("hidden");
  const rect =
    (anchor && document.contains(anchor) && anchor.getBoundingClientRect()) ||
    fallbackRect;
  if (rect && (rect.width || rect.height || rect.top || rect.left)) {
    positionCategoryFlyout(rect);
  }
  if (els.threadCategoryLabel) {
    els.threadCategoryLabel.setAttribute(
      "aria-expanded",
      chatId === state.selectedId ? "true" : "false"
    );
  }
}

function syncCategoryButtons(category) {
  const cat = category || "uncategorized";
  els.categorySegmented?.querySelectorAll("[data-set-category]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.setCategory === cat);
  });
  if (!els.threadCategoryLabel) return;
  els.threadCategoryLabel.textContent = categoryLabel(cat);
  els.threadCategoryLabel.classList.add("clickable");
  els.threadCategoryLabel.title = "Click to change category";
}

async function refreshAvailableThreads() {
  try {
    const data = await api("/api/threads/available");
    if (data.available_threads != null) {
      setAvailableThreads(data.available_threads);
      return data.available_threads;
    }
  } catch (_) {
    /* fall through */
  }
  return state.availableThreads;
}

async function setAppleIntelligenceEnabled(enabled) {
  els.aiToggle.disabled = true;
  try {
    const data = await api("/api/settings", {
      method: "PUT",
      body: JSON.stringify({ apple_intelligence_enabled: enabled }),
    });
    state.settings = data.settings || state.settings;
    state.appleIntelligence = data.apple_intelligence || null;
    state.platform = data.platform || state.platform;
    renderAiStatus();
    renderPlatformChip();
  } catch (err) {
    els.aiToggle.checked = !!state.settings.apple_intelligence_enabled;
    els.aiStatus.textContent = err.message;
    els.aiStatus.className = "ai-status warn";
  } finally {
    els.aiToggle.disabled = !state.platform?.apple_silicon;
  }
}

async function persistSettingsPatch(patch) {
  try {
    const data = await api("/api/settings", {
      method: "PUT",
      body: JSON.stringify(patch),
    });
    state.settings = data.settings || state.settings;
  } catch (_) {
    /* non-blocking */
  }
}

async function persistSummaryDays(days) {
  await persistSettingsPatch({ summary_days: days });
}

async function loadThreads() {
  const params = new URLSearchParams({ category: "all" });
  let statusMsg = "";
  if (state.loadMode === "activity") {
    const value = Math.max(1, Math.min(100, Number(els.threadActivityValue?.value) || 6));
    const unit = els.threadActivityUnit?.value === "years" ? "years" : "months";
    if (els.threadActivityValue) els.threadActivityValue.value = String(value);
    const days = activityToDays(value, unit);
    params.set("activity_days", String(days));
    params.set("limit", "100000");
    persistSettingsPatch({
      thread_load_mode: "activity",
      thread_activity_value: value,
      thread_activity_unit: unit,
    });
    statusMsg = `Loading conversations active in the last ${value} ${unit}…`;
  } else {
    const limit = currentThreadLimit();
    syncThreadLimitLabel();
    params.set("limit", String(limit));
    persistSettingsPatch({ thread_load_mode: "count", thread_limit: limit });
    statusMsg = `Loading ${limit} most recent conversations…`;
  }
  syncThreadLimitLabel();

  els.loadThreadsBtn.disabled = true;
  els.loadThreadsBtn.textContent = "Loading…";
  els.threadList.innerHTML = `<p class="loading">${escapeHtml(statusMsg)}</p>`;
  setStatus(statusMsg, 2, { busy: true });

  try {
    let data;
    let streamError = null;
    try {
      data = await readSse(`/api/threads/stream?${params}`, {
        onProgress: (message, percent) => {
          setStatus(message, percent, { busy: true });
          if (
            message &&
            (message.startsWith("Loading preview") ||
              message.startsWith("Loading Contacts") ||
              message.startsWith("Contacts"))
          ) {
            els.threadList.innerHTML = `<p class="loading">${escapeHtml(message)}</p>`;
          }
        },
      });
    } catch (err) {
      streamError = err;
      setStatus(`Stream failed (${err.message}). Trying direct load…`, 45, { busy: true });
      data = await api(`/api/threads?${params}`);
    }
    state.allThreads = data.threads || [];
    state.hasLoaded = true;
    if (data.available_threads != null) setAvailableThreads(data.available_threads);
    els.accessBanner.classList.add("hidden");
    applyLocalFilters();
    setLoadCardCollapsed(true);
    if (state.selectedId) {
      const still = state.allThreads.find((t) => t.id === state.selectedId);
      if (still) {
        state.selected = still;
        showSelectedThread(still, { clearSummary: false });
        loadRecentMessages(still.id, { limit: state.messagesLimit });
      }
    }
    const note = streamError ? " · recovered after stream error" : "";
    clearStatus(`Ready · ${state.allThreads.length} conversations loaded${note}`);
  } catch (err) {
    els.accessBanner.textContent = err.message;
    els.accessBanner.classList.remove("hidden");
    els.threadList.innerHTML = `<p class="loading">Unable to load conversations.<br><small>${escapeHtml(
      err.message
    )}</small></p>`;
    clearStatus(`Failed to load conversations: ${err.message}`);
  } finally {
    els.loadThreadsBtn.disabled = false;
    els.loadThreadsBtn.textContent = state.hasLoaded ? "Reload conversations" : "Start loading";
  }
}

function clearSummaryPanel() {
  els.summaryPanel.classList.add("hidden");
  els.summaryMeta.textContent = "";
  els.summaryText.textContent = "";
  els.summaryTopics.innerHTML = "";
  els.summaryHighlights.innerHTML = "";
}

function hideMessagesLoadFlyout() {
  if (!els.messagesLoadFlyout) return;
  els.messagesLoadFlyout.classList.add("hidden");
  if (els.messagesCount) {
    els.messagesCount.setAttribute("aria-expanded", "false");
  }
}

function openMessagesLoadFlyout() {
  if (!els.messagesLoadFlyout || !els.messagesCount) return;
  if (!state.selectedId || !state.messagesHasMore) return;
  const rect = els.messagesCount.getBoundingClientRect();
  els.messagesLoadFlyout.classList.remove("hidden");
  const width = els.messagesLoadFlyout.offsetWidth || 170;
  let left = rect.right - width;
  left = Math.max(8, Math.min(left, window.innerWidth - width - 8));
  let top = rect.bottom + 6;
  els.messagesLoadFlyout.style.left = `${left}px`;
  els.messagesLoadFlyout.style.top = `${top}px`;
  els.messagesCount.setAttribute("aria-expanded", "true");
}

function syncMessagesCountButton(count) {
  if (!els.messagesCount) return;
  const n = Number(count) || 0;
  if (!n) {
    els.messagesCount.textContent = "Latest 10";
  } else if (state.messagesHasMore) {
    els.messagesCount.textContent = `${n} recent ▾`;
  } else {
    els.messagesCount.textContent = n === 1 ? "1 message" : `${n} messages`;
  }
  els.messagesCount.disabled = !state.selectedId || !state.messagesHasMore;
  els.messagesCount.title = state.messagesHasMore
    ? "Click to load more messages"
    : "All available messages are loaded";
}

function renderMessages(messages) {
  if (!els.messagesList) return;
  if (!messages.length) {
    syncMessagesCountButton(0);
    els.messagesList.innerHTML =
      '<p class="messages-empty">No text messages found in this conversation.</p>';
    return;
  }
  syncMessagesCountButton(messages.length);
  els.messagesList.innerHTML = messages
    .map((m) => {
      const fromMe = !!m.is_from_me;
      const who = fromMe ? "You" : m.sender_name || m.sender || "Unknown";
      const when = formatWhen(m.sent_at);
      const text = (m.text || "").trim();
      const body = text
        ? escapeHtml(text)
        : m.has_attachments
          ? "Attachment"
          : "(no text)";
      const emptyClass = text ? "" : " attachment-only";
      return `
        <article class="message-row ${fromMe ? "from-me" : "from-them"}">
          <div class="message-meta">${escapeHtml(who)}${when ? ` · ${escapeHtml(when)}` : ""}</div>
          <div class="message-bubble${emptyClass}">${body}</div>
        </article>
      `;
    })
    .join("");
  // Keep the newest messages in view.
  els.messagesList.scrollTop = els.messagesList.scrollHeight;
}

async function loadRecentMessages(chatId, { limit = state.messagesLimit } = {}) {
  const requestId = ++state.messagesRequestId;
  const requested = Math.max(1, Math.min(20_000, Math.round(Number(limit) || 10)));
  state.messagesLimit = requested;
  if (els.messagesList) {
    els.messagesCount.textContent = "Loading…";
    els.messagesList.innerHTML =
      '<p class="messages-empty">Loading recent messages…</p>';
  }
  try {
    const data = await api(
      `/api/threads/${chatId}/messages?limit=${encodeURIComponent(String(requested))}`
    );
    if (requestId !== state.messagesRequestId || state.selectedId !== chatId) {
      return;
    }
    const messages = data.messages || [];
    const knownTotal = Number(state.selected?.message_count) || 0;
    if (knownTotal > 0) {
      state.messagesHasMore = messages.length < knownTotal;
    } else {
      state.messagesHasMore = messages.length >= requested;
    }
    renderMessages(messages);
  } catch (err) {
    if (requestId !== state.messagesRequestId || state.selectedId !== chatId) {
      return;
    }
    state.messagesHasMore = false;
    syncMessagesCountButton(0);
    els.messagesList.innerHTML = `<p class="messages-empty">${escapeHtml(
      err.message || "Could not load messages"
    )}</p>`;
  }
}

function setLoadCardCollapsed(collapsed) {
  state.loadCardCollapsed = !!collapsed;
  if (!els.loadCard || !els.loadCardToggle) return;
  els.loadCard.classList.toggle("collapsed", state.loadCardCollapsed);
  els.loadCardToggle.setAttribute(
    "aria-expanded",
    state.loadCardCollapsed ? "false" : "true"
  );
}

function showSelectedThread(thread, { clearSummary = true } = {}) {
  els.emptyState.classList.add("hidden");
  els.threadView.classList.remove("hidden");
  if (clearSummary) clearSummaryPanel();
  els.threadTitle.textContent = thread.display_name || "Conversation";
  const people = thread.participant_names || thread.participants || [];
  const parts = [
    `${(thread.message_count || 0).toLocaleString()} messages in conversation`,
    ...people.slice(0, 3),
  ];
  if (thread.last_message_at) {
    parts.push(`last activity ${formatWhen(thread.last_message_at)}`);
  }
  els.threadMeta.textContent = parts.join(" · ");
  syncCategoryButtons(thread.category || "uncategorized");
}

function selectThread(id) {
  const thread =
    state.threads.find((t) => t.id === id) ||
    state.allThreads.find((t) => t.id === id);
  if (!thread) return;
  const switched = state.selectedId !== id;
  state.selectedId = id;
  state.selected = thread;
  if (switched) {
    state.messagesLimit = defaultMessageLimit();
    state.messagesHasMore = true;
    hideMessagesLoadFlyout();
  }
  renderThreadList();
  showSelectedThread(thread, { clearSummary: switched });
  loadRecentMessages(id, { limit: state.messagesLimit });
  clearStatus(`Selected ${thread.display_name || "conversation"} · categorize or summarize`);
}

async function setCategory(category) {
  if (!state.selectedId || !state.selected) return;
  setStatus("Saving category…", null, { busy: true });
  try {
    const updated = await api(`/api/threads/${state.selectedId}/category`, {
      method: "PUT",
      body: JSON.stringify({
        category,
        chat_guid: state.selected.guid,
      }),
    });
    state.selected.category = updated.category;
    const listed = state.allThreads.find((t) => t.id === state.selectedId);
    if (listed) listed.category = updated.category;

    syncCategoryButtons(updated.category);
    applyLocalFilters();
    clearStatus(`Marked as ${categoryLabel(updated.category)}`);
  } catch (err) {
    clearStatus(err.message || "Failed to save category");
  }
}

function methodLabel(result) {
  if (result.method === "apple_intelligence" || result.used_apple_intelligence) {
    return "Apple Intelligence";
  }
  return "Local extractive";
}

async function summarizeSelected() {
  if (!state.selectedId) return;
  const days = currentSummaryDays();
  els.summaryDays.value = String(days);
  persistSummaryDays(days);

  const wantAi =
    !!state.platform?.apple_silicon && !!state.settings.apple_intelligence_enabled;
  els.summarizeBtn.disabled = true;
  els.summarizeBtn.textContent = wantAi ? "Asking Apple Intelligence…" : "Summarizing…";
  setStatus(`Loading messages from the last ${days} days…`, 5, { busy: true });

  try {
    const params = new URLSearchParams({
      days: String(days),
      max_messages: "500",
      max_sentences: "5",
    });
    if (wantAi) params.set("use_apple_intelligence", "true");
    else params.set("use_apple_intelligence", "false");

    const data = await readSse(
      `/api/threads/${state.selectedId}/summary/stream?${params}`,
      {
        onProgress: (message, percent) => setStatus(message, percent, { busy: true }),
      }
    );
    const result = data.summary || data;
    els.summaryMethod.textContent = methodLabel(result);
    const msgCount = result.message_count ?? 0;
    els.summaryMeta.textContent = `Based on ${msgCount} message${
      msgCount === 1 ? "" : "s"
    } from the last ${result.days || days} days.`;
    els.summaryText.textContent = result.summary || "";
    els.summaryTopics.innerHTML = (result.topics || [])
      .map((t) => `<li>${escapeHtml(t)}</li>`)
      .join("");
    els.summaryHighlights.innerHTML = (result.highlights || [])
      .map((h) => `<li>${escapeHtml(h)}</li>`)
      .join("");
    els.summaryPanel.classList.remove("hidden");
    clearStatus(
      result.used_apple_intelligence
        ? `Summary ready · last ${result.days || days} days · Apple Intelligence`
        : `Summary ready · last ${result.days || days} days · Extractive`
    );
  } catch (err) {
    els.summaryMethod.textContent = wantAi ? "Apple Intelligence" : "Local extractive";
    els.summaryMeta.textContent = "";
    els.summaryText.textContent = err.message;
    els.summaryTopics.innerHTML = "";
    els.summaryHighlights.innerHTML = "";
    els.summaryPanel.classList.remove("hidden");
    clearStatus("Summary failed");
  } finally {
    els.summarizeBtn.disabled = false;
    els.summarizeBtn.textContent = "Summarize";
  }
}

function renderPermissions(permissions, messages, contacts) {
  const needs = !!permissions?.needs_attention || messages?.readable === false;
  if (!els.permissionsCard) return;
  els.permissionsCard.classList.toggle("hidden", !needs);
  if (!needs) return;
  const parts = [];
  if (!messages?.readable) {
    parts.push(
      "Messages database is not readable yet. Enable Full Disk Access for MessageManager AND Python, then quit and reopen."
    );
  }
  if (contacts && contacts.available === false) {
    parts.push("Contacts lookup is limited until Full Disk Access is granted.");
  }
  if (permissions?.fda_target) {
    parts.push(`Python to add: ${permissions.fda_target}`);
  }
  if (permissions?.guidance) parts.push(permissions.guidance);
  if (els.permissionsText) {
    els.permissionsText.textContent = parts.join(" ");
  }
}

function renderUpdateBanner(info) {
  state.updateInfo = info;
  const available = !!info?.update_available && !!info?.installer?.url;
  if (els.updateBanner) els.updateBanner.classList.toggle("hidden", !available);
  if (els.updateBannerText && available) {
    els.updateBannerText.textContent = `Update ${info.latest_version} available`;
  }
  if (els.updateStatus) {
    if (!info?.ok) {
      els.updateStatus.textContent = info?.detail || "Could not check for updates.";
    } else if (available) {
      els.updateStatus.textContent = `Version ${info.latest_version} is available (you have ${info.current_version}).`;
    } else {
      els.updateStatus.textContent = `You're on the latest version (${info.current_version}).`;
    }
  }
  if (els.installUpdateBtn) {
    els.installUpdateBtn.classList.toggle("hidden", !available);
  }
}

async function checkForUpdates({ quiet = false } = {}) {
  if (!quiet && els.updateStatus) els.updateStatus.textContent = "Checking for updates…";
  try {
    const info = await api("/api/updates/check");
    renderUpdateBanner(info);
    if (!quiet && info.update_available) {
      clearStatus(`Update ${info.latest_version} available`);
    }
    return info;
  } catch (err) {
    renderUpdateBanner({
      ok: false,
      update_available: false,
      current_version: state.appVersion,
      detail: err.message,
    });
    return null;
  }
}

async function promptInstallUpdate(info, { force = false } = {}) {
  if (!info?.update_available || !info?.installer?.url) return false;
  const latest = info.latest_version || "a newer version";
  const current = info.current_version || state.appVersion;
  const key = `mm-update-prompted-${latest}`;
  if (!force && sessionStorage.getItem(key) === "dismissed") return false;
  const install = confirm(
    `MessageManager ${latest} is available (you have ${current}).\n\nDownload and install the update now?`
  );
  if (!install) {
    sessionStorage.setItem(key, "dismissed");
    clearStatus(`Update ${latest} available — install anytime from Settings`);
    return false;
  }
  await downloadAndInstallUpdate();
  return true;
}

async function downloadAndInstallUpdate() {
  const url = state.updateInfo?.installer?.url;
  if (!url) return;
  if (els.installUpdateBtn) {
    els.installUpdateBtn.disabled = true;
    els.installUpdateBtn.textContent = "Downloading…";
  }
  if (els.updateBannerBtn) {
    els.updateBannerBtn.disabled = true;
    els.updateBannerBtn.textContent = "Downloading…";
  }
  setStatus("Downloading update…", null, { busy: true });
  try {
    const result = await api("/api/updates/download", {
      method: "POST",
      body: JSON.stringify({ url }),
    });
    clearStatus(`Installer saved to ${result.path || "Downloads"} — complete the installer, then reopen MessageManager`);
    if (els.updateStatus) {
      els.updateStatus.textContent =
        "Installer opened. Finish the package install, then quit and reopen MessageManager so migrations can run.";
    }
  } catch (err) {
    clearStatus(err.message || "Update download failed");
  } finally {
    if (els.installUpdateBtn) {
      els.installUpdateBtn.disabled = false;
      els.installUpdateBtn.textContent = "Download & install update";
    }
    if (els.updateBannerBtn) {
      els.updateBannerBtn.disabled = false;
      els.updateBannerBtn.textContent = "Install";
    }
  }
}

function openSettingsModal() {
  if (!els.settingsModal) return;
  fillSettingsForm();
  if (els.settingsCurrentVersion) {
    els.settingsCurrentVersion.textContent = state.appVersion;
  }
  checkForUpdates({ quiet: true });
  els.settingsModal.classList.remove("hidden");
}

function closeSettingsModal() {
  els.settingsModal?.classList.add("hidden");
}

function renderSettingsCategoryLists() {
  const defs = allCategoryDefs();
  const enabled = new Set(
    (state.settings.enabled_categories || []).filter((id) =>
      defs.some((d) => d.id === id)
    )
  );
  if (!enabled.size) BUILTIN_CATEGORY_KEYS.forEach((id) => enabled.add(id));
  enabled.add("uncategorized");
  const hidden = new Set(state.settings.hidden_from_default || []);

  if (els.settingEnabledCategories) {
    els.settingEnabledCategories.innerHTML = defs
      .map((def) => {
        const locked = def.id === "uncategorized";
        return `
        <label class="settings-check">
          <input type="checkbox" data-enabled-cat="${def.id}" ${
            enabled.has(def.id) ? "checked" : ""
          } ${locked ? "disabled" : ""} />
          <span>${escapeHtml(def.label)}${locked ? " (always on)" : ""}</span>
        </label>`;
      })
      .join("");
  }
  if (els.settingHiddenCategories) {
    els.settingHiddenCategories.innerHTML = defs
      .map(
        (def) => `
        <label class="settings-check">
          <input type="checkbox" data-hidden-cat="${def.id}" ${
            hidden.has(def.id) ? "checked" : ""
          } />
          <span>Hide ${escapeHtml(def.label)} from All</span>
        </label>`
      )
      .join("");
  }
  if (els.settingCustomCategories) {
    const custom = state.settingsDraftCustom;
    els.settingCustomCategories.innerHTML = custom.length
      ? custom
          .map(
            (c, idx) => `
          <div class="custom-cat-row">
            <span>${escapeHtml(c.label)}</span>
            <button type="button" data-remove-custom="${idx}">Remove</button>
          </div>`
          )
          .join("")
      : `<p class="settings-help">No custom categories yet.</p>`;
    els.settingCustomCategories.querySelectorAll("[data-remove-custom]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const idx = Number(btn.dataset.removeCustom);
        state.settingsDraftCustom = state.settingsDraftCustom.filter((_, i) => i !== idx);
        renderSettingsCategoryLists();
      });
    });
  }
}

function fillSettingsForm() {
  const s = state.settings;
  state.settingsDraftCustom = (s.custom_categories || []).map((c) => ({ ...c }));
  if (els.settingAutoLoad) els.settingAutoLoad.checked = !!s.auto_load_on_start;
  if (els.settingThreadLimit) {
    els.settingThreadLimit.value = String(s.thread_limit || 50);
  }
  if (els.settingMessageLimit) {
    els.settingMessageLimit.value = String(s.default_message_limit || 10);
  }
  if (els.settingSummaryDays) {
    els.settingSummaryDays.value = String(s.summary_days || 30);
  }
  if (els.settingAiShortcut) {
    els.settingAiShortcut.value = s.apple_intelligence_shortcut || "MessageManager Summarize";
  }
  if (els.settingActivityValue) {
    els.settingActivityValue.value = String(s.thread_activity_value || 6);
  }
  if (els.settingActivityUnit) {
    els.settingActivityUnit.value = s.thread_activity_unit === "years" ? "years" : "months";
  }
  if (els.aiToggle) {
    els.aiToggle.checked = !!s.apple_intelligence_enabled;
    els.aiToggle.disabled = !state.platform?.apple_silicon;
  }
  syncSettingsLoadModeUI(s.thread_load_mode || "count");
  renderAiStatus();
  renderSettingsCategoryLists();
}

function addDraftCustomCategory() {
  const label = (els.settingNewCategory?.value || "").trim();
  if (!label) return;
  const id = label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/^(\d)/, "c_$1")
    .slice(0, 40);
  if (!id) return;
  if (BUILTIN_CATEGORY_KEYS.includes(id) || state.settingsDraftCustom.some((c) => c.id === id)) {
    clearStatus("That category already exists");
    return;
  }
  state.settingsDraftCustom.push({ id, label: label.slice(0, 60) });
  if (els.settingNewCategory) els.settingNewCategory.value = "";
  renderSettingsCategoryLists();
  const enabledBox = els.settingEnabledCategories?.querySelector(
    `[data-enabled-cat="${id}"]`
  );
  if (enabledBox) enabledBox.checked = true;
}

async function saveSettingsFromForm(event) {
  event.preventDefault();
  const defs = allCategoryDefs();
  const enabled = defs
    .map((d) => d.id)
    .filter((key) => {
      if (key === "uncategorized") return true;
      const input = els.settingEnabledCategories?.querySelector(
        `[data-enabled-cat="${key}"]`
      );
      return !!input?.checked;
    });
  const hidden = defs
    .map((d) => d.id)
    .filter((key) => {
      const input = els.settingHiddenCategories?.querySelector(
        `[data-hidden-cat="${key}"]`
      );
      return !!input?.checked && enabled.includes(key);
    });
  const threadLimit = Math.max(
    5,
    Math.min(100_000, Number(els.settingThreadLimit?.value) || 50)
  );
  const messageLimit = Math.max(
    1,
    Math.min(500, Number(els.settingMessageLimit?.value) || 10)
  );
  const summaryDays = Math.max(
    1,
    Math.min(3650, Number(els.settingSummaryDays?.value) || 30)
  );
  const loadMode = document
    .querySelector("[data-setting-load-mode].active")
    ?.dataset.settingLoadMode === "activity"
    ? "activity"
    : "count";
  const activityValue = Math.max(
    1,
    Math.min(100, Number(els.settingActivityValue?.value) || 6)
  );
  const activityUnit =
    els.settingActivityUnit?.value === "years" ? "years" : "months";
  try {
    const data = await api("/api/settings", {
      method: "PUT",
      body: JSON.stringify({
        apple_intelligence_enabled: !!els.aiToggle?.checked,
        apple_intelligence_shortcut:
          els.settingAiShortcut?.value?.trim() || "MessageManager Summarize",
        auto_load_on_start: !!els.settingAutoLoad?.checked,
        thread_limit: threadLimit,
        thread_load_mode: loadMode,
        thread_activity_value: activityValue,
        thread_activity_unit: activityUnit,
        default_message_limit: messageLimit,
        summary_days: summaryDays,
        custom_categories: state.settingsDraftCustom,
        enabled_categories: enabled,
        hidden_from_default: hidden,
      }),
    });
    state.settings = { ...state.settings, ...(data.settings || {}) };
    state.appleIntelligence = data.apple_intelligence || state.appleIntelligence;
    state.platform = data.platform || state.platform;
    state.loadMode = state.settings.thread_load_mode || "count";
    if (els.threadActivityValue) {
      els.threadActivityValue.value = String(state.settings.thread_activity_value || 6);
    }
    if (els.threadActivityUnit) {
      els.threadActivityUnit.value =
        state.settings.thread_activity_unit === "years" ? "years" : "months";
    }
    els.threadLimit.value = String(
      Math.min(state.settings.thread_limit || 50, maxThreadLimit())
    );
    els.summaryDays.value = String(state.settings.summary_days || 30);
    syncLoadModeUI(state.loadMode);
    syncThreadLimitLabel();
    renderCategoryControls();
    renderAiStatus();
    if (state.category !== "all" && !enabledCategories().includes(state.category)) {
      state.category = "all";
    }
    if (state.hasLoaded) applyLocalFilters();
    else renderCategorySummary();
    closeSettingsModal();
    clearStatus("Settings saved");
  } catch (err) {
    clearStatus(err.message || "Could not save settings");
  }
}

function bindEvents() {
  let searchTimer;
  els.search.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.query = els.search.value.trim();
      if (state.hasLoaded) applyLocalFilters();
    }, 200);
  });

  els.threadCategoryLabel?.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (!state.selectedId) return;
    const open =
      !els.categoryFlyout?.classList.contains("hidden") &&
      state.flyoutChatId === state.selectedId;
    if (open) hideCategoryFlyout();
    else openCategoryFlyout(els.threadCategoryLabel, state.selectedId);
  });

  document.addEventListener("click", () => {
    hideCategoryFlyout();
    hideMessagesLoadFlyout();
  });
  window.addEventListener("resize", () => {
    hideCategoryFlyout();
    hideMessagesLoadFlyout();
  });
  els.threadList?.addEventListener(
    "scroll",
    () => {
      hideCategoryFlyout();
      hideMessagesLoadFlyout();
    },
    { passive: true }
  );

  els.loadCardToggle?.addEventListener("click", (event) => {
    event.preventDefault();
    setLoadCardCollapsed(!state.loadCardCollapsed);
  });

  els.messagesCount?.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (!state.selectedId || !state.messagesHasMore) return;
    const open = !els.messagesLoadFlyout?.classList.contains("hidden");
    if (open) hideMessagesLoadFlyout();
    else openMessagesLoadFlyout();
  });

  els.messagesLoadFlyout?.querySelectorAll("[data-load-messages]").forEach((btn) => {
    btn.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      hideMessagesLoadFlyout();
      if (!state.selectedId) return;
      const mode = btn.dataset.loadMessages;
      if (mode === "all") {
        const total = Number(state.selected?.message_count) || 20_000;
        await loadRecentMessages(state.selectedId, {
          limit: Math.min(20_000, Math.max(state.messagesLimit, total)),
        });
      } else {
        await loadRecentMessages(state.selectedId, {
          limit: state.messagesLimit + 100,
        });
      }
    });
  });

  els.summarizeBtn.addEventListener("click", summarizeSelected);

  document.querySelectorAll("[data-load-mode]").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      syncLoadModeUI(btn.dataset.loadMode);
    });
  });
  document.querySelectorAll("[data-setting-load-mode]").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      syncSettingsLoadModeUI(btn.dataset.settingLoadMode);
    });
  });
  els.threadActivityValue?.addEventListener("input", () => syncThreadLimitLabel());
  els.threadActivityUnit?.addEventListener("change", () => syncThreadLimitLabel());
  els.settingAddCategory?.addEventListener("click", (event) => {
    event.preventDefault();
    addDraftCustomCategory();
  });
  els.settingNewCategory?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addDraftCustomCategory();
    }
  });

  let daysTimer;
  els.summaryDays.addEventListener("change", () => {
    const days = currentSummaryDays();
    els.summaryDays.value = String(days);
    persistSummaryDays(days);
  });
  els.summaryDays.addEventListener("input", () => {
    clearTimeout(daysTimer);
    daysTimer = setTimeout(() => {
      const days = currentSummaryDays();
      persistSummaryDays(days);
    }, 400);
  });

  els.threadLimit.addEventListener("input", () => {
    syncThreadLimitLabel();
  });
  els.threadLimit.addEventListener("change", () => {
    const limit = currentThreadLimit();
    syncThreadLimitLabel();
    persistSettingsPatch({ thread_limit: limit });
  });
  els.loadThreadsBtn.addEventListener("click", () => loadThreads());

  els.settingsBtn?.addEventListener("click", (event) => {
    event.preventDefault();
    openSettingsModal();
  });
  els.settingsForm?.addEventListener("submit", saveSettingsFromForm);
  els.settingsModal?.querySelectorAll("[data-close-settings]").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      closeSettingsModal();
    });
  });
  els.openPrivacyBtn?.addEventListener("click", async () => {
    try {
      await api("/api/permissions/open-settings", { method: "POST" });
      clearStatus(
        "Opened Privacy settings — enable Full Disk Access for MessageManager and Python"
      );
    } catch (err) {
      clearStatus(err.message || "Could not open Privacy settings");
    }
  });
  els.recheckPermissionsBtn?.addEventListener("click", async () => {
    try {
      const health = await api("/api/health");
      renderPermissions(health.permissions, health.messages, health.contacts);
      if (health.permissions?.needs_attention) {
        clearStatus("Still missing access — grant Full Disk Access, then recheck");
      } else {
        clearStatus("Permissions look good");
      }
    } catch (err) {
      clearStatus(err.message || "Recheck failed");
    }
  });
  els.checkUpdatesBtn?.addEventListener("click", async () => {
    const info = await checkForUpdates();
    if (info?.update_available) await promptInstallUpdate(info, { force: true });
  });
  els.installUpdateBtn?.addEventListener("click", () => downloadAndInstallUpdate());
  els.updateBannerBtn?.addEventListener("click", async () => {
    if (state.updateInfo?.update_available) {
      await promptInstallUpdate(state.updateInfo, { force: true });
    } else {
      openSettingsModal();
    }
  });

  els.openLogsBtn.addEventListener("click", () => {
    const logs = state.logs || {};
    const lines = [
      "MessageManager log files:",
      logs.app_log || "(app.log path unknown)",
      logs.launch_log || "(launch.log path unknown)",
      "",
      "In Finder: Go → Go to Folder… and paste:",
      logs.log_dir || "~/Library/Application Support/MessageManager/logs",
    ];
    alert(lines.join("\n"));
    clearStatus(`Logs: ${logs.log_dir || "see alert"}`);
  });

  els.quitAppBtn?.addEventListener("click", async () => {
    if (!confirm("Stop MessageManager and close the local server?")) return;
    setStatus("Shutting down…", { busy: true });
    try {
      await api("/api/shutdown", { method: "POST" });
    } catch {
      // Server may close the connection before the response finishes.
    }
    clearStatus("Server stopped — you can close this tab");
  });
}

async function init() {
  bindEvents();
  setStatus("Ready — choose a conversation count and press Start loading");
  try {
    const health = await api("/api/health");
    state.settings = { ...state.settings, ...(health.settings || {}) };
    state.appVersion = health.version || state.appVersion || "1.0.4";
    if (els.appVersionLabel) els.appVersionLabel.textContent = state.appVersion;
    if (els.settingsCurrentVersion) {
      els.settingsCurrentVersion.textContent = state.appVersion;
    }
    state.messagesLimit = defaultMessageLimit();
    state.loadMode = state.settings.thread_load_mode || "count";
    state.appleIntelligence = health.apple_intelligence || null;
    state.platform = health.platform || null;
    state.logs = health.logs || null;
    renderPermissions(health.permissions, health.messages, health.contacts);
    if (health.migration?.upgraded) {
      clearStatus(`Upgraded to ${state.appVersion} — data migrations applied`);
    }
    els.summaryDays.value = String(state.settings.summary_days || 30);
    if (els.threadActivityValue) {
      els.threadActivityValue.value = String(state.settings.thread_activity_value || 6);
    }
    if (els.threadActivityUnit) {
      els.threadActivityUnit.value =
        state.settings.thread_activity_unit === "years" ? "years" : "months";
    }
    if (health.messages?.available_threads != null) {
      setAvailableThreads(health.messages.available_threads);
    }
    await refreshAvailableThreads();
    const preferred = state.settings.thread_limit || 50;
    els.threadLimit.value = String(Math.min(preferred, maxThreadLimit()));
    syncLoadModeUI(state.loadMode);
    syncThreadLimitLabel();
    renderCategoryControls();
    renderCategorySummary();
    renderPlatformChip();
    renderAiStatus();
    renderThreadList();
    if (!health.messages?.readable && health.messages?.error) {
      els.accessBanner.textContent = health.messages.error;
      els.accessBanner.classList.remove("hidden");
    }
    if (els.openLogsBtn && state.logs?.log_dir) {
      els.openLogsBtn.title = state.logs.log_dir;
    }
    if (state.availableThreads != null) {
      clearStatus(
        `Ready — ${state.availableThreads.toLocaleString()} conversations available · default load ${preferred}`
      );
    }
    if (state.settings.auto_load_on_start) {
      await loadThreads();
    }
    // Always check GitHub Releases on launch and prompt when an update exists.
    const updateInfo = await checkForUpdates({ quiet: true });
    if (updateInfo?.update_available) {
      await promptInstallUpdate(updateInfo);
    }
  } catch (err) {
    if (els.aiStatus) {
      els.aiStatus.textContent = err.message;
      els.aiStatus.className = "ai-status warn";
    }
    clearStatus("Could not reach server");
    renderCategorySummary();
    renderThreadList();
  }
}

init();
