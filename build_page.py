"""Build the page (site/index.html) from jobs.json and the daily reports in reports/.

Usage: python3 -I build_page.py   (job_watch.py also calls this after every run; same JOBWATCH_* env as job_watch.py)
"""
import json
import os
from pathlib import Path

HISTORY_DAYS = 30  # daily reports shown in the page's day list

PAGE = r"""<!doctype html>
<html lang="bg">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="robots" content="noindex, nofollow">
<link rel="icon" href="data:,">
<title>Обяви за работа</title>
<style>
  :root {
    --bg: #f7f7f5; --surface: #ffffff; --ink: #1c1d1f; --muted: #5d6066; --faint: #6b6f76;
    --line: #e4e4e0; --accent: #22549e; --accent-soft: #e9eff8; --warn: #8a5300;
    --radius: 8px;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #141517; --surface: #1c1d20; --ink: #ececea; --muted: #a3a6ab; --faint: #959aa1;
      --line: #2e3034; --accent: #8db4ec; --accent-soft: #232c3a; --warn: #e2ad5c;
    }
  }
  * { box-sizing: border-box; }
  html { scroll-behavior: smooth; scroll-padding-top: 16px; }
  @media (prefers-reduced-motion: reduce) { html { scroll-behavior: auto; } }
  body { margin: 0; background: var(--bg); color: var(--ink); font-size: 17px; line-height: 1.5;
         font-family: "Segoe UI", "Ubuntu Sans", system-ui, -apple-system, sans-serif; }
  a { color: var(--accent); }
  a:focus-visible, button:focus-visible, input:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

  .wrap { max-width: 1080px; margin: 0 auto; padding: 32px 24px 64px; }
  .masthead { margin-bottom: 28px; }
  .masthead h1 { font-size: 28px; line-height: 1.2; margin: 0 0 6px; letter-spacing: -0.01em; }
  .masthead p { margin: 0 0 4px; color: var(--muted); max-width: 80ch; }

  .layout { display: grid; grid-template-columns: 200px 1fr; gap: 40px; align-items: start; }

  /* Day navigation */
  .days { position: sticky; top: 24px; }
  .days h2 { font-size: 15px; font-weight: 600; color: var(--muted); margin: 20px 0 8px; }
  .days ol { list-style: none; margin: 0; padding: 0; display: grid; gap: 2px; }
  .days a { display: flex; justify-content: space-between; gap: 12px; padding: 8px 12px; border-radius: var(--radius);
            color: var(--ink); text-decoration: none; }
  .days a:hover { background: var(--accent-soft); }
  .days a[aria-current="page"] { background: var(--accent-soft); color: var(--accent); font-weight: 600; }
  .days .n { color: var(--faint); font-variant-numeric: tabular-nums; }
  .days a[aria-current="page"] .n { color: var(--accent); }

  /* Day header */
  .day-head h2 { font-size: 24px; line-height: 1.25; margin: 0 0 4px; }
  .day-head .summary { margin: 0 0 18px; color: var(--muted); }
  .toolbar { display: flex; flex-wrap: wrap; gap: 8px 24px; align-items: center; padding: 12px 0;
             border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); margin-bottom: 8px; }
  .jump { display: flex; gap: 8px; flex-wrap: wrap; }
  .jump a { padding: 6px 12px; border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface);
            color: var(--ink); text-decoration: none; font-size: 15px; }
  .jump a:hover { border-color: var(--accent); color: var(--accent); }
  .filters { display: flex; gap: 20px; flex-wrap: wrap; margin-left: auto; font-size: 15px; color: var(--muted); }
  .filters label { display: flex; align-items: center; gap: 8px; cursor: pointer; }
  .filters input { width: 18px; height: 18px; accent-color: var(--accent); margin: 0; }

  /* Sections and jobs */
  section { margin-top: 28px; }
  section > h3 { font-size: 19px; margin: 0 0 4px; }
  section > .hint { margin: 0 0 10px; color: var(--muted); font-size: 15px; }
  .jobs { list-style: none; margin: 0; padding: 0; background: var(--surface); border: 1px solid var(--line);
          border-radius: var(--radius); }
  .job { display: grid; grid-template-columns: 1fr auto; gap: 2px 24px; padding: 16px 20px; }
  .job + .job { border-top: 1px solid var(--line); }
  .job .head { min-width: 0; }
  .job .badge { display: inline-block; margin-right: 8px; padding: 1px 8px; border-radius: 999px; font-size: 13px;
                font-weight: 600; vertical-align: 2px; background: var(--accent-soft); color: var(--accent); }
  .job .title { font-size: 18px; font-weight: 600; line-height: 1.35; text-decoration: none; }
  .job .title:hover { text-decoration: underline; }
  .job .salary { font-weight: 600; text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
  .job .where, .job .meta, .job .warn { grid-column: 1 / -1; font-size: 15px; }
  .job .where { color: var(--muted); }
  .job .meta { color: var(--faint); }
  .job .warn { color: var(--warn); }
  .job .easy { color: var(--accent); font-weight: 600; }
  .job .meta strong { color: var(--ink); font-weight: 600; }
  .job.closed { opacity: .5; }
  .empty { margin: 0; padding: 20px; color: var(--muted); background: var(--surface); border: 1px solid var(--line);
           border-radius: var(--radius); }
  .sources { margin-top: 32px; font-size: 14px; color: var(--faint); max-width: 75ch; }
  .sources p { margin: 0 0 4px; }

  @media (max-width: 760px) {
    .wrap { padding: 20px 16px 48px; }
    .layout { grid-template-columns: 1fr; gap: 20px; }
    .days { position: static; }
    .days h2 { margin-top: 12px; }
    .days ol { display: flex; overflow-x: auto; gap: 6px; padding-bottom: 4px; }
    .days a { white-space: nowrap; border: 1px solid var(--line); background: var(--surface); }
    .filters { margin-left: 0; }
    .job { grid-template-columns: 1fr; padding: 14px 16px; }
    .job .salary { text-align: left; order: 2; }
  }
</style>
</head>
<body>
<div class="wrap">
  <header class="masthead">
    <h1>Обяви за работа</h1>
    <p>Дистанционна работа без нужда от специални умения, от България и Европа. Проверява се всяка сутрин<span id="checked"></span>.</p>
    <p>Натиснете заглавието на обява, за да я отворите на сайта, където е публикувана, и кандидатствайте оттам.</p>
  </header>
  <div class="layout">
    <nav class="days" aria-label="Обяви">
      <ol><li><a id="nowLink" href="#now"><span>Актуални обяви</span><span class="n" id="nowCount"></span></a></li></ol>
      <h2>Нови по дни</h2>
      <ol id="dayList"></ol>
    </nav>
    <main id="day" aria-live="polite"></main>
  </div>
</div>
<script id="data" type="application/json">__DATA__</script>
<script>
  const { active, reports } = JSON.parse(document.getElementById("data").textContent);
  const today = new Date().toLocaleDateString("sv-SE");  // local YYYY-MM-DD
  const latest = reports[0];
  const activeKeys = new Set(active.map((j) => j.key));
  const prefs = { hideClosed: true, onlyBg: false };
  const isDate = (h) => /^\d{4}-\d{2}-\d{2}$/.test(h);
  // "now" (jobs still listed) or a report date; section jump links (#s0) leave it as it is.
  const viewOf = (h) => (h === "" || h === "now") ? "now" : isDate(h) ? h : null;
  let currentView = viewOf(location.hash.slice(1)) || "now";
  const HOURS = { part: "непълно или гъвкаво време", freelance: "на свободна практика", full: "пълно работно време" };
  const SECTION_LABELS = ["Търсят български език", "Обяви на английски"];
  const SECTION_HINTS = [
    "Най-добрият шанс: работодателят търси човек с роден български език. Подредени от най-лесните.",
    "Изискват добър английски. Подредени от най-лесните.",
  ];

  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const fmtShort = (d) => d ? d.slice(0, 10).split("-").reverse().join(".") : "";
  const fmtLong = (d) => {
    const t = new Date(d + "T12:00:00").toLocaleDateString("bg-BG", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
    return t.charAt(0).toUpperCase() + t.slice(1);
  };
  const fmtChecked = (c) => {
    const d = new Date(c);
    return d.toLocaleDateString("bg-BG", { weekday: "long", day: "numeric", month: "long" })
      + (c.length > 10 ? ", " + d.toLocaleTimeString("bg-BG", { hour: "2-digit", minute: "2-digit" }) : "");
  };
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  const expired = (j) => j.until && j.until.slice(0, 10) < today;
  const closed = (j) => expired(j) || !activeKeys.has(j.key);
  const byEffort = (a, b) => a.effort - b.effort || a.title.localeCompare(b.title);
  // Ranges use a plain hyphen; "1450-1450" collapses to "1450".
  const salaryText = (s) => (s || "").replace(/–/g, "-").replace(/^(\S+)-(\S+)/, (m, lo, hi) => lo === hi ? lo : m);
  // Long country lists: keep Bulgaria (if present) plus the first others, count the rest.
  const place = (c) => {
    const parts = (c || "").split(/,\s*/).filter(Boolean);
    if (parts.length <= 4) return c || "";
    const shown = [...parts.filter((x) => /bulgaria|българ/i.test(x)), ...parts.filter((x) => !/bulgaria|българ/i.test(x))].slice(0, 3);
    return `${shown.join(", ")} и още ${parts.length - 3}`;
  };
  const flagText = (f) => f.replace(/\s*[—–]\s*/g, ", ");

  function jobHtml(j, sectionIndex, isNow) {
    // "The ad is in English" is information, not a caution: it goes in the details line, and only in the
    // Bulgarian section (in the English section it is implied).
    const english = (j.flags || []).includes("обявата е на английски");
    const flags = (j.flags || []).filter((f) => f !== "обявата е на английски").map(flagText);
    const where = [j.company, place(j.city)].filter(Boolean).map(esc).join(", ");
    const status = expired(j) ? `изтекла на ${fmtShort(j.until)}`
      : !activeKeys.has(j.key) ? "вече не е публикувана"
      : j.until ? `срок до ${fmtShort(j.until)}` : "";
    const details = [
      esc((j.roles || []).join(", ")),
      english && sectionIndex === 0 ? "обявата е на английски" : "",
      status,
      isNow && j.first_seen ? `намерена на ${fmtShort(j.first_seen)}` : "",
      `източник ${esc(j.source)}`,
    ].filter(Boolean).join(", ");
    const effort = [j.level ? `<strong>${esc(j.level)}</strong>` : "", esc(HOURS[j.hours] || "")].filter(Boolean).join(", ");
    const meta = (effort ? effort + ". " : "")
      + (j.no_experience ? `<span class="easy">Без нужда от опит.</span> ` : "")
      + details.charAt(0).toUpperCase() + details.slice(1);
    const isNew = isNow && latest && j.first_seen === latest.date;
    return `<li class="job${closed(j) ? " closed" : ""}">
      <span class="head">${isNew ? `<span class="badge">Нова</span>` : ""}<a class="title" href="${esc(j.url)}" target="_blank" rel="noopener">${esc(j.title)}</a></span>
      <span class="salary">${esc(salaryText(j.salary))}</span>
      ${where ? `<span class="where">${where}</span>` : ""}
      <span class="meta">${meta}.</span>
      ${flags.length ? `<span class="warn">Внимание: ${esc(flags.join("; "))}.</span>` : ""}
    </li>`;
  }

  // A view is either the jobs still listed ("now") or one day's new jobs, split into the two sections.
  function viewData(view) {
    if (view === "now") {
      const jobs = [...active].sort(byEffort);
      return { isNow: true, title: "Актуални обяви", report: latest,
               sections: [jobs.filter((j) => j.bulgarian), jobs.filter((j) => !j.bulgarian)] };
    }
    const r = reports.find((x) => x.date === view) || latest;
    return { isNow: false, title: "Нови на " + fmtLong(r.date).replace(/^./, (c) => c.toLowerCase()), report: r,
             sections: r.sections.map((s) => s.jobs) };
  }

  function renderView(v) {
    const sections = v.sections.map((jobs, i) => ({
      i, id: "s" + i, label: SECTION_LABELS[i], hint: SECTION_HINTS[i],
      jobs: jobs.filter((j) => (!prefs.hideClosed || !closed(j)) && (!prefs.onlyBg || j.bulgarian)),
    }));
    const all = sections.flatMap((s) => s.jobs);
    const easy = all.filter((j) => j.no_experience).length;
    const fresh = v.isNow ? all.filter((j) => j.first_seen === latest.date).length : 0;
    const summary = !all.length
      ? (v.isNow ? "В момента няма подходящи обяви. Проверката продължава всяка сутрин." : "Няма нови обяви за този ден.")
      : [v.isNow ? plural(all.length, "обява, която още е публикувана", "обяви, които още са публикувани")
                 : plural(all.length, "нова обява", "нови обяви"),
         [plural(sections[0].jobs.length, "търси", "търсят") + " български език",
          easy ? `${easy} без нужда от опит` : ""].filter(Boolean).join(", "),
         fresh ? plural(fresh, "е нова от последната проверка", "са нови от последната проверка") : "",
        ].filter(Boolean).join(". ") + ".";
    const r = v.report || {};
    $("day").innerHTML = `
      <div class="day-head">
        <h2>${esc(v.title)}</h2>
        <p class="summary">${summary}</p>
      </div>
      <div class="toolbar">
        <div class="jump">${sections.map((s) => `<a href="#${s.id}">${esc(s.label)} (${s.jobs.length})</a>`).join("")}</div>
        <div class="filters">
          <label><input type="checkbox" id="onlyBg" ${prefs.onlyBg ? "checked" : ""}> Само търсещи български</label>
          <label><input type="checkbox" id="hideClosed" ${prefs.hideClosed ? "checked" : ""}> Скрий затворените</label>
        </div>
      </div>
      ${sections.filter((s) => !(prefs.onlyBg && s.i > 0)).map((s) => `
        <section id="${s.id}" aria-labelledby="${s.id}-h">
          <h3 id="${s.id}-h">${esc(s.label)}</h3>
          <p class="hint">${esc(s.hint)}</p>
          ${s.jobs.length ? `<ul class="jobs">${s.jobs.map((j) => jobHtml(j, s.i, v.isNow)).join("")}</ul>`
                          : `<p class="empty">Няма обяви в тази група.</p>`}
        </section>`).join("")}
      <div class="sources">
        <p>Проверени сайтове: ${Object.entries(r.sources || {}).map(([k, n]) => `${esc(k)} (${n})`).join(", ")}.</p>
        <p>Пропуснати са обяви, които изискват специални или технически умения, или езици освен български и английски.</p>
        <p>Трудността (лесна, средна, по-трудна) е оценка по обявата: колко опит и колко добър английски се изискват, колко
          изисквания и работни програми се изброяват, дали работата е на пълно работно време, нощем или по американско време.</p>
        ${(r.errors || []).length ? `<p>Неуспешни проверки: ${r.errors.slice(0, 3).map(esc).join("; ")}.</p>` : ""}
      </div>`;
    ["onlyBg", "hideClosed"].forEach((id) => $(id).addEventListener("change", (e) => { prefs[id] = e.target.checked; render(); }));
  }

  function render() {
    if (!reports.length) {
      $("day").innerHTML = `<p class="empty">Все още няма проверки. Първите обяви ще се появят тук след сутрешната проверка.</p>`;
      return;
    }
    $("checked").textContent = "; последна проверка: " + fmtChecked(latest.checked || latest.date);
    $("nowCount").textContent = active.filter((j) => !expired(j)).length;
    if (currentView === "now") $("nowLink").setAttribute("aria-current", "page");
    else $("nowLink").removeAttribute("aria-current");
    $("dayList").innerHTML = reports.map((r) => {
      const n = r.sections.reduce((a, s) => a + s.jobs.length, 0);
      return `<li><a href="#${r.date}" ${r.date === currentView ? 'aria-current="page"' : ""}>
        <span>${fmtShort(r.date)}</span><span class="n">${n}</span></a></li>`;
    }).join("");
    renderView(viewData(currentView));
  }

  function $(id) { return document.getElementById(id); }
  window.addEventListener("hashchange", () => {
    const v = viewOf(location.hash.slice(1));
    if (v) { currentView = v; render(); window.scrollTo(0, 0); }
  });
  render();
</script>
</body>
</html>
"""


def build(data_dir, site_dir):
    data_dir, site_dir = Path(data_dir), Path(site_dir)
    reports = [json.loads(p.read_text(encoding="utf-8")) for p in (data_dir / "reports").glob("*.json")]
    reports = sorted(reports, key=lambda r: r["date"], reverse=True)[:HISTORY_DAYS]
    jobs_file = data_dir / "jobs.json"
    active = list(json.loads(jobs_file.read_text(encoding="utf-8")).values()) if jobs_file.exists() else []
    data = json.dumps({"active": active, "reports": reports}, ensure_ascii=False).replace("</", "<\\/")
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "index.html").write_text(PAGE.replace("__DATA__", data), encoding="utf-8")


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    site = Path(os.environ.get("JOBWATCH_SITE") or here / "site")
    build(Path(os.environ.get("JOBWATCH_DATA") or here), site)
    print(site / "index.html")
