/* AI Chronicle — frontend preview */
/* All dates displayed and matched in Indian Standard Time (IST = GMT+5:30) */

const TZ_IST = "Asia/Kolkata";

let DATA = { articles: [], milestones: [] };

// The front page is deliberately narrower than the archive. It shows
// publisher-owned announcements and established editorial outlets, rather than
// treating every arXiv preprint as news. Research remains searchable below.
const FRONT_PAGE_SOURCES = new Set([
  "OpenAI News",
  "Anthropic News",
  "Google DeepMind",
  "Google AI Blog",
  "Hugging Face Blog",
  "TechCrunch AI",
  "MIT Technology Review AI",
  "The Verge AI",
  "VentureBeat AI",
  "MarkTechPost",
  "The Decoder",
  "AI News",
]);

function frontPageArticles() {
  return (DATA.articles || []).filter((a) => FRONT_PAGE_SOURCES.has(a.source));
}

// Entries dated 2026 in the original import have not been independently
// verified against an official publisher or established newsroom. They are not
// rendered. These additions use the original company announcement directly.
const CONFIRMED_2025_MILESTONES = [
  {
    date: "2025-01-20",
    title: "DeepSeek releases DeepSeek-R1",
    desc: "Company announcement for an open reasoning-model release. Capability claims are attributed to DeepSeek.",
    importance: "high",
    category: "company",
    source: "DeepSeek",
    link: "https://github.com/deepseek-ai/DeepSeek-R1",
  },
  {
    date: "2025-01-29",
    title: "Alibaba announces Qwen2.5-Max",
    desc: "Official Qwen release announcement. The timeline does not substitute unverified model names or price comparisons.",
    importance: "high",
    category: "company",
    source: "Qwen",
    link: "https://qwenlm.github.io/blog/qwen2.5-max/",
  },
  {
    date: "2025-02-14",
    title: "Perplexity introduces Deep Research",
    desc: "Official product announcement for Perplexity's research workflow; product claims are attributed to the company.",
    importance: "high",
    category: "company",
    source: "Perplexity",
    link: "https://www.perplexity.ai/hub/blog/introducing-perplexity-deep-research",
  },
  {
    date: "2025-02-24",
    title: "Anthropic launches Claude 3.7 Sonnet",
    desc: "Anthropic announces its hybrid reasoning model and Claude Code research preview.",
    importance: "high",
    category: "company",
    source: "Anthropic",
    link: "https://www.anthropic.com/news/claude-3-7-sonnet",
  },
  {
    date: "2025-04-05",
    title: "Meta announces the Llama 4 family",
    desc: "Official release announcement for Meta's multimodal Llama 4 models.",
    importance: "high",
    category: "company",
    source: "Meta AI",
    link: "https://ai.meta.com/blog/llama-4-multimodal-intelligence/",
  },
  {
    date: "2025-04-16",
    title: "OpenAI launches o3 and o4-mini",
    desc: "OpenAI's official announcement for its reasoning-model releases; performance claims remain attributed to OpenAI.",
    importance: "high",
    category: "company",
    source: "OpenAI",
    link: "https://openai.com/index/introducing-o3-and-o4-mini/",
  },
];

function timelineMilestones() {
  const vetted = (DATA.milestones || []).filter((m) => String(m.date || "") < "2026-01-01");
  return [...vetted, ...CONFIRMED_2025_MILESTONES].sort((a, b) => String(a.date).localeCompare(String(b.date)));
}

async function loadData() {
  try {
    const res = await fetch("data.json");
    DATA = await res.json();
  } catch (e) {
    console.error("Failed to load data.json", e);
    document.getElementById("main").innerHTML =
      "<p style='padding:2rem;color:#f88'>Could not load data.json. Open this folder via a local server (e.g. <code>python -m http.server</code>).</p>";
    return;
  }
  init();
}

function init() {
  const gen = DATA.generated_at
    ? new Date(DATA.generated_at).toLocaleString("en-GB", {
        timeZone: TZ_IST,
        day: "numeric",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }) + " IST"
    : "";
  document.getElementById("data-stamp").textContent = gen
    ? "Data generated " + gen
    : "";

  renderMilestones();
  renderHome();
  renderToday();
  renderTimeline();
  setupCalendar();
  setupSearch();
  setupNav();
}

/* ---------- Nav ---------- */
function setupNav() {
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      showView(btn.dataset.view);
    });
  });
}

function showView(name) {
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  document.querySelectorAll(".nav-btn").forEach((b) => b.classList.remove("active"));
  const view = document.getElementById("view-" + name);
  if (view) view.classList.add("active");
  const btn = document.querySelector(`.nav-btn[data-view="${name}"]`);
  if (btn) btn.classList.add("active");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

/* ---------- Helpers (all times in IST = Asia/Kolkata, GMT+5:30) ---------- */

/** Format any ISO / date string as e.g. "30 Nov 2022" in IST. */
function fmtDate(iso) {
  if (!iso) return "—";
  try {
    // Pure calendar dates like "2022-11-30" → treat as that calendar day
    if (/^\d{4}-\d{2}-\d{2}$/.test(String(iso).trim())) {
      const [y, m, d] = iso.split("-").map(Number);
      const dt = new Date(Date.UTC(y, m - 1, d, 6, 30)); // noon-ish IST-safe
      return dt.toLocaleDateString("en-GB", {
        day: "numeric",
        month: "short",
        year: "numeric",
        timeZone: TZ_IST,
      });
    }
    const d = new Date(iso);
    return d.toLocaleDateString("en-GB", {
      day: "numeric",
      month: "short",
      year: "numeric",
      timeZone: TZ_IST,
    });
  } catch {
    return String(iso).slice(0, 10);
  }
}

/** YYYY-MM-DD calendar key in IST for an article timestamp. */
function dateKey(iso) {
  if (!iso) return "";
  // Already a pure date
  if (/^\d{4}-\d{2}-\d{2}$/.test(String(iso).trim())) {
    return String(iso).trim().slice(0, 10);
  }
  try {
    const d = new Date(iso);
    // en-CA gives YYYY-MM-DD
    return d.toLocaleDateString("en-CA", { timeZone: TZ_IST });
  } catch {
    return String(iso).slice(0, 10);
  }
}

/** Current calendar date in IST as YYYY-MM-DD. */
function todayIST() {
  return new Date().toLocaleDateString("en-CA", { timeZone: TZ_IST });
}

/** Format a Date object as YYYY-MM-DD using IST calendar parts. */
function toLocalDateKey(d) {
  if (!(d instanceof Date) || isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-CA", { timeZone: TZ_IST });
}

function badge(importance, category) {
  let html = "";
  if (importance === "high") html += `<span class="badge high">Important</span>`;
  if (category) html += `<span class="badge ${category}">${category}</span>`;
  return html;
}

function sourceType(a) {
  if (["OpenAI News", "Anthropic News", "Google DeepMind", "Google AI Blog", "Hugging Face Blog"].includes(a.source)) {
    return "Company announcement";
  }
  if (a.source === "arXiv cs.AI") return "Research preprint";
  if (["VentureBeat AI", "MarkTechPost", "The Decoder", "AI News"].includes(a.source)) {
    return "Secondary AI reporting";
  }
  return "Reported news";
}

function cardHTML(a) {
  const snippet = a.summary || a.body_preview || "";
  return `
    <article class="card">
      <div class="meta">
        <span>${fmtDate(a.published_at)}</span>
        <span>·</span>
        <span>${escapeHtml(a.source || "")}</span>
        <span>(${sourceType(a)})</span>
        ${badge(a.importance, a.category)}
      </div>
      <h3><a href="${escapeAttr(a.link)}" target="_blank" rel="noopener">${escapeHtml(a.title)}</a></h3>
      ${snippet ? `<p class="snippet">${escapeHtml(snippet)}</p>` : ""}
    </article>`;
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
function escapeAttr(s) {
  return escapeHtml(s).replace(/'/g, "&#39;");
}

/* ---------- Sidebar milestones ---------- */
function milestoneTitleHTML(m) {
  const title = escapeHtml(m.title);
  if (m.link) {
    return `<a href="${escapeAttr(m.link)}" target="_blank" rel="noopener">${title}</a>`;
  }
  return title;
}

function renderMilestones() {
  const ul = document.getElementById("milestone-list");
  ul.innerHTML = timelineMilestones()
    .slice()
    .reverse()
    .map(
      (m) => `
    <li>
      <div class="m-date">${fmtDate(m.date)}</div>
      <div class="m-title">${milestoneTitleHTML(m)}</div>
      <div class="m-desc">${escapeHtml(m.desc || "")}${
        m.source && m.link
          ? ` · <a href="${escapeAttr(m.link)}" target="_blank" rel="noopener">${escapeHtml(m.source)}</a>`
          : ""
      }</div>
    </li>`
    )
    .join("");
}

/* ---------- Home ---------- */
function renderHome() {
  const arts = frontPageArticles();
  // Week track: last 7–10 items
  const week = arts.slice(0, 10);
  document.getElementById("week-track").innerHTML = week
    .map(
      (a) => `
    <div class="week-card">
      <div class="meta">
        <span>${fmtDate(a.published_at)}</span>
        <span>${escapeHtml(a.source || "")}</span>
      </div>
      <h3><a href="${escapeAttr(a.link)}" target="_blank" rel="noopener">${escapeHtml(a.title)}</a></h3>
      <p class="snippet">${escapeHtml(a.summary || a.body_preview || "")}</p>
    </div>`
    )
    .join("");

  document.getElementById("home-latest").innerHTML = arts
    .slice(0, 8)
    .map(cardHTML)
    .join("");

  const important = arts.filter((a) => a.importance === "high").slice(0, 8);
  document.getElementById("home-important").innerHTML = important.length
    ? important.map(cardHTML).join("")
    : "<p class='empty-hint'>No high-importance items in the recent feed.</p>";
}

/* ---------- Today ---------- */
function renderToday() {
  const today = todayIST(); // IST calendar date
  document.getElementById("today-date-label").textContent =
    "Showing items for " + fmtDate(today) + " IST (or latest if none).";

  const arts = frontPageArticles();
  let list = arts.filter((a) => dateKey(a.published_at) === today);
  const empty = document.getElementById("today-empty");
  if (list.length === 0) {
    list = arts.slice(0, 12);
    empty.hidden = false;
  } else {
    empty.hidden = true;
  }
  document.getElementById("today-list").innerHTML = list.map(cardHTML).join("");
}

/* ---------- Timeline ---------- */
function renderTimeline() {
  const el = document.getElementById("timeline");
  el.innerHTML = timelineMilestones()
    .map(
      (m) => `
    <div class="tl-item">
      <div class="tl-date">${fmtDate(m.date)}</div>
      <h3>${milestoneTitleHTML(m)}</h3>
      <p>${escapeHtml(m.desc || "")}${
        m.source && m.link
          ? ` · <a href="${escapeAttr(m.link)}" target="_blank" rel="noopener">Read coverage → ${escapeHtml(m.source)}</a>`
          : ""
      }</p>
    </div>`
    )
    .join("");
}

/* ---------- Calendar ---------- */
/** Try to parse free-text dates like "20 November 2022", "20th Nov 2022", "2022-11-20". */
function parseFlexibleDate(raw) {
  if (!raw) return null;
  let s = raw.trim().toLowerCase();
  // strip ordinals: 1st, 2nd, 3rd, 4th, 20th, etc.
  s = s.replace(/(\d+)(st|nd|rd|th)/g, "$1");
  // normalize common separators
  s = s.replace(/[.,]/g, " ").replace(/\s+/g, " ").trim();

  // already ISO-like?
  const iso = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (iso) {
    const d = new Date(Number(iso[1]), Number(iso[2]) - 1, Number(iso[3]));
    return isNaN(d.getTime()) ? null : d;
  }

  // "20 november 2022" / "november 20 2022" / "20 nov 2022"
  const months = {
    january: 0, jan: 0, february: 1, feb: 1, march: 2, mar: 2,
    april: 3, apr: 3, may: 4, june: 5, jun: 5, july: 6, jul: 6,
    august: 7, aug: 7, september: 8, sep: 8, sept: 8,
    october: 9, oct: 9, november: 10, nov: 10, december: 11, dec: 11,
  };

  const parts = s.split(" ");
  let day = null, month = null, year = null;
  for (const p of parts) {
    if (months[p] !== undefined) month = months[p];
    else if (/^\d{4}$/.test(p)) year = Number(p);
    else if (/^\d{1,2}$/.test(p)) {
      const n = Number(p);
      if (day === null && n >= 1 && n <= 31) day = n;
      else if (year === null && n > 31) year = n;
    }
  }
  if (day !== null && month !== null && year !== null) {
    const d = new Date(year, month, day);
    if (d.getFullYear() === year && d.getMonth() === month && d.getDate() === day) {
      return d;
    }
  }

  // last resort: native parse, then re-build with local parts
  const d = new Date(raw);
  if (!isNaN(d.getTime())) return d;
  return null;
}

function setupCalendar() {
  const dateInput = document.getElementById("cal-date");
  const textInput = document.getElementById("cal-text");
  const go = document.getElementById("cal-go");

  // default to a recent article date if available
  const first = (DATA.articles || [])[0];
  if (first && first.published_at) {
    dateInput.value = first.published_at.slice(0, 10);
  }

  function run() {
    let key = dateInput.value;
    const raw = textInput.value.trim();
    if (raw) {
      const d = parseFlexibleDate(raw);
      if (d) {
        // Use local Y-M-D so timezone never shifts the calendar day
        key = toLocalDateKey(d);
        dateInput.value = key;
      }
    }
    if (!key) return;

    const matches = (DATA.articles || []).filter(
      (a) => dateKey(a.published_at) === key
    );
    // also match milestones
    const miles = timelineMilestones().filter((m) => m.date === key);

    const results = document.getElementById("cal-results");
    const empty = document.getElementById("cal-empty");

    let html = "";
    if (miles.length) {
      html += miles
        .map(
          (m) => `
        <article class="card">
          <div class="meta">
            <span class="badge high">Milestone</span>
            ${fmtDate(m.date)}
            ${m.source ? ` · ${escapeHtml(m.source)}` : ""}
          </div>
          <h3>${milestoneTitleHTML(m)}</h3>
          <p class="snippet">${escapeHtml(m.desc || "")}${
            m.link
              ? ` <a href="${escapeAttr(m.link)}" target="_blank" rel="noopener">Read original coverage →</a>`
              : ""
          }</p>
        </article>`
        )
        .join("");
    }
    html += matches.map(cardHTML).join("");

    results.innerHTML = html;
    empty.hidden = html.length > 0;
  }

  go.addEventListener("click", run);
  dateInput.addEventListener("change", run);
  textInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") run();
  });
}

/* ---------- Search ---------- */
function setupSearch() {
  const input = document.getElementById("search-input");
  const srcSel = document.getElementById("filter-source");
  const catSel = document.getElementById("filter-category");
  const impSel = document.getElementById("filter-importance");
  const results = document.getElementById("search-results");

  // populate filters
  const sources = [...new Set((DATA.articles || []).map((a) => a.source).filter(Boolean))].sort();
  const cats = [...new Set((DATA.articles || []).map((a) => a.category).filter(Boolean))].sort();
  sources.forEach((s) => {
    const o = document.createElement("option");
    o.value = s;
    o.textContent = s;
    srcSel.appendChild(o);
  });
  cats.forEach((c) => {
    const o = document.createElement("option");
    o.value = c;
    o.textContent = c;
    catSel.appendChild(o);
  });

  function run() {
    const q = input.value.trim().toLowerCase();
    const src = srcSel.value;
    const cat = catSel.value;
    const imp = impSel.value;

    let list = DATA.articles || [];
    if (q) {
      list = list.filter(
        (a) =>
          (a.title || "").toLowerCase().includes(q) ||
          (a.summary || "").toLowerCase().includes(q) ||
          (a.source || "").toLowerCase().includes(q)
      );
    }
    if (src) list = list.filter((a) => a.source === src);
    if (cat) list = list.filter((a) => a.category === cat);
    if (imp) list = list.filter((a) => a.importance === imp);

    results.innerHTML =
      list.length === 0
        ? "<p class='empty-hint'>No matches.</p>"
        : list.slice(0, 40).map(cardHTML).join("");
  }

  input.addEventListener("input", run);
  srcSel.addEventListener("change", run);
  catSel.addEventListener("change", run);
  impSel.addEventListener("change", run);
  run(); // initial
}

/* boot */
loadData().then(() => {
  const params = new URLSearchParams(location.search);
  const v = params.get("view");
  if (v) showView(v);
});
