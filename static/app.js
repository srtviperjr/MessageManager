const state = {
  category: "all",
  query: "",
  allThreads: [],
  threads: [],
  counts: { business: 0, personal: 0, uncategorized: 0 },
  selectedId: null,
  selected: null,
  messagesRequestId: 0,
  flyoutChatId: null,
  hasLoaded: false,
  availableThreads: null,
  settings: {
    apple_intelligence_enabled: false,
    apple_intelligence_shortcut: "MessageManager Summarize",
    summary_days: 30,
    thread_limit: 50,
  },
  appleIntelligence: null,
  platform: null,
  logs: null,
  busy: false,
};

const els = {
  search: document.getElementById("search"),
  filters: document.querySelectorAll(".filter"),
  threadList: document.getElementById("thread-list"),
  accessBanner: document.getElementById("access-banner"),
  emptyState: document.getElementById("empty-state"),
  threadView: document.getElementById("thread-view"),
  threadTitle: document.getElementById("thread-title"),
  threadMeta: document.getElementById("thread-meta"),
  threadCategoryLabel: document.getElementById("thread-category-label"),
  categoryFlyout: document.getElementById("category-flyout"),
  threadLimitMaxLabel: document.getElementById("thread-limit-max-label"),
  categoryButtons: document.querySelectorAll("[data-set-category]"),
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
  countAll: document.getElementById("count-all"),
  countBusiness: document.getElementById("count-business"),
  countPersonal: document.getElementById("count-personal"),
  countUncategorized: document.getElementById("count-uncategorized"),
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
};

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
  return "Uncategorized";
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
  const value = currentThreadLimit();
  if (els.threadLimitValue) els.threadLimitValue.textContent = String(value);
  if (els.threadLimit) els.threadLimit.value = String(value);
}

function applyLocalFilters() {
  const counts = { business: 0, personal: 0, uncategorized: 0 };
  for (const t of state.allThreads) {
    counts[t.category] = (counts[t.category] || 0) + 1;
  }
  state.counts = counts;

  let list = state.allThreads.slice();
  if (state.category && state.category !== "all") {
    list = list.filter((t) => t.category === state.category);
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
  renderCounts();
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

function renderCounts() {
  const { counts } = state;
  const total = (counts.business || 0) + (counts.personal || 0) + (counts.uncategorized || 0);
  els.countAll.textContent = String(total);
  els.countBusiness.textContent = String(counts.business || 0);
  els.countPersonal.textContent = String(counts.personal || 0);
  els.countUncategorized.textContent = String(counts.uncategorized || 0);
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
    els.threadList.innerHTML = `<p class="loading">Choose how many threads to load, then press Start loading.</p>`;
    return;
  }
  if (!threads.length) {
    els.threadList.innerHTML = `<p class="loading">No threads match this filter.</p>`;
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
      const badgeClickable = cat === "uncategorized" ? "clickable" : "";
      return `
        <button class="thread-item ${active}" data-id="${t.id}" role="listitem">
          <div class="top">
            <span class="name">${escapeHtml(t.display_name || "Untitled")}</span>
            <span class="when">${escapeHtml(formatWhen(t.last_message_at))}</span>
          </div>
          <p class="preview">${escapeHtml(subtitle)}</p>
          <span
            class="badge ${cat} ${badgeClickable}"
            data-category-badge="${t.id}"
            data-category="${cat}"
            title="${cat === "uncategorized" ? "Click to set Business or Personal" : ""}"
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
      const cat = badge.dataset.category || "uncategorized";
      if (!Number.isFinite(chatId)) return;
      // selectThread re-renders the list and destroys this badge node, so
      // capture its screen position first, then re-find the new badge.
      const clickRect = badge.getBoundingClientRect();
      selectThread(chatId);
      if (cat === "uncategorized") {
        const nextBadge = els.threadList.querySelector(
          `[data-category-badge="${chatId}"]`
        );
        openCategoryFlyout(nextBadge, chatId, clickRect);
      } else {
        hideCategoryFlyout();
      }
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
  els.categoryButtons.forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.setCategory === cat);
  });
  if (!els.threadCategoryLabel) return;
  els.threadCategoryLabel.textContent = categoryLabel(cat);
  const canQuickSet = cat === "uncategorized";
  els.threadCategoryLabel.classList.toggle("clickable", canQuickSet);
  els.threadCategoryLabel.title = canQuickSet
    ? "Click to set Business or Personal"
    : "";
  if (!canQuickSet) hideCategoryFlyout();
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
  const limit = currentThreadLimit();
  syncThreadLimitLabel();
  persistSettingsPatch({ thread_limit: limit });

  const params = new URLSearchParams({
    category: "all",
    limit: String(limit),
  });

  els.loadThreadsBtn.disabled = true;
  els.loadThreadsBtn.textContent = "Loading…";
  els.threadList.innerHTML = `<p class="loading">Loading ${limit} most recent threads…</p>`;
  setStatus(`Loading ${limit} most recent threads…`, 2, { busy: true });

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
    if (state.selectedId) {
      const still = state.allThreads.find((t) => t.id === state.selectedId);
      if (still) {
        state.selected = still;
        showSelectedThread(still, { clearSummary: false });
        loadRecentMessages(still.id);
      }
    }
    const note = streamError ? " · recovered after stream error" : "";
    clearStatus(`Ready · ${state.allThreads.length} threads loaded${note}`);
  } catch (err) {
    els.accessBanner.textContent = err.message;
    els.accessBanner.classList.remove("hidden");
    els.threadList.innerHTML = `<p class="loading">Unable to load threads.<br><small>${escapeHtml(
      err.message
    )}</small></p>`;
    clearStatus(`Failed to load threads: ${err.message}`);
  } finally {
    els.loadThreadsBtn.disabled = false;
    els.loadThreadsBtn.textContent = state.hasLoaded ? "Reload threads" : "Start loading";
  }
}

function clearSummaryPanel() {
  els.summaryPanel.classList.add("hidden");
  els.summaryMeta.textContent = "";
  els.summaryText.textContent = "";
  els.summaryTopics.innerHTML = "";
  els.summaryHighlights.innerHTML = "";
}

function renderMessages(messages) {
  if (!els.messagesList) return;
  if (!messages.length) {
    els.messagesCount.textContent = "Latest 10";
    els.messagesList.innerHTML =
      '<p class="messages-empty">No text messages found in this thread.</p>';
    return;
  }
  els.messagesCount.textContent = `${messages.length} recent`;
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

async function loadRecentMessages(chatId) {
  const requestId = ++state.messagesRequestId;
  if (els.messagesList) {
    els.messagesCount.textContent = "Latest 10";
    els.messagesList.innerHTML =
      '<p class="messages-empty">Loading recent messages…</p>';
  }
  try {
    const data = await api(`/api/threads/${chatId}/messages?limit=10`);
    if (requestId !== state.messagesRequestId || state.selectedId !== chatId) {
      return;
    }
    renderMessages(data.messages || []);
  } catch (err) {
    if (requestId !== state.messagesRequestId || state.selectedId !== chatId) {
      return;
    }
    els.messagesList.innerHTML = `<p class="messages-empty">${escapeHtml(
      err.message || "Could not load messages"
    )}</p>`;
  }
}

function showSelectedThread(thread, { clearSummary = true } = {}) {
  els.emptyState.classList.add("hidden");
  els.threadView.classList.remove("hidden");
  if (clearSummary) clearSummaryPanel();
  els.threadTitle.textContent = thread.display_name || "Thread";
  const people = thread.participant_names || thread.participants || [];
  const parts = [
    `${(thread.message_count || 0).toLocaleString()} messages in thread`,
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
  renderThreadList();
  showSelectedThread(thread, { clearSummary: switched });
  loadRecentMessages(id);
  clearStatus(`Selected ${thread.display_name || "thread"} · categorize or summarize`);
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

function bindEvents() {
  els.filters.forEach((btn) => {
    btn.addEventListener("click", () => {
      els.filters.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.category = btn.dataset.category;
      if (state.hasLoaded) applyLocalFilters();
    });
  });

  let searchTimer;
  els.search.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.query = els.search.value.trim();
      if (state.hasLoaded) applyLocalFilters();
    }, 200);
  });

  els.categoryButtons.forEach((btn) => {
    btn.addEventListener("click", () => setCategory(btn.dataset.setCategory));
  });

  els.threadCategoryLabel?.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    const cat = state.selected?.category || "uncategorized";
    if (cat !== "uncategorized" || !state.selectedId) return;
    const open = !els.categoryFlyout?.classList.contains("hidden")
      && state.flyoutChatId === state.selectedId;
    if (open) {
      hideCategoryFlyout();
    } else {
      openCategoryFlyout(els.threadCategoryLabel, state.selectedId);
    }
  });

  els.categoryFlyout?.querySelectorAll("[data-flyout-category]").forEach((btn) => {
    btn.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      const chatId = state.flyoutChatId || state.selectedId;
      const category = btn.dataset.flyoutCategory;
      hideCategoryFlyout();
      if (!chatId || !category) return;
      if (state.selectedId !== chatId) {
        selectThread(chatId);
      }
      await setCategory(category);
    });
  });

  document.addEventListener("click", () => hideCategoryFlyout());
  window.addEventListener("resize", () => hideCategoryFlyout());
  els.threadList?.addEventListener("scroll", () => hideCategoryFlyout(), { passive: true });

  els.summarizeBtn.addEventListener("click", summarizeSelected);

  els.aiToggle.addEventListener("change", () => {
    setAppleIntelligenceEnabled(els.aiToggle.checked);
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
  setStatus("Ready — choose a thread count and press Start loading");
  try {
    const health = await api("/api/health");
    state.settings = health.settings || state.settings;
    state.appleIntelligence = health.apple_intelligence || null;
    state.platform = health.platform || null;
    state.logs = health.logs || null;
    els.summaryDays.value = String(state.settings.summary_days || 30);
    if (health.messages?.available_threads != null) {
      setAvailableThreads(health.messages.available_threads);
    }
    await refreshAvailableThreads();
    const preferred = state.settings.thread_limit || 50;
    els.threadLimit.value = String(Math.min(preferred, maxThreadLimit()));
    syncThreadLimitLabel();
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
  } catch (err) {
    els.aiStatus.textContent = err.message;
    els.aiStatus.className = "ai-status warn";
    clearStatus("Could not reach server");
    renderThreadList();
  }
}

init();
