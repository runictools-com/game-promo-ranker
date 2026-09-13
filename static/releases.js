/* Steam release agenda: additive tab, existing visual components. */
"use strict";
let RELEASES = null;
let releasesLoading = false;
const releasesBaseSwitch = switchTab;
switchTab = function (tab) {
  releasesBaseSwitch(tab);
  el("tab-releases")?.classList.toggle("hidden", tab !== "releases");
  if (tab === "releases" && !RELEASES && !releasesLoading) loadReleases();
};
function releaseHttps(value) {
  try { const u = new URL(value); return u.protocol === "https:" ? escapeHtml(u.href) : ""; }
  catch { return ""; }
}
function releaseDay(value) {
  const s = String(value || "");
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return "";
  const d = new Date(s + "T12:00:00Z");
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === s ? s : "";
}
function releaseDateLabel(value) {
  const day = releaseDay(value);
  return day ? new Date(day + "T12:00:00Z").toLocaleDateString("pt-BR", {weekday:"long", day:"2-digit", month:"long", year:"numeric", timeZone:"UTC"}) : "Sem data exata";
}
function releaseTags(game) { return Array.isArray(game.tags) ? game.tags.map(String) : []; }
function releaseNormalize(value) { return String(value || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase(); }
function releaseCard(game) {
  const url = releaseHttps(game.url);
  const tags = releaseTags(game).map(t => `<span class="tag">${escapeHtml(t)}</span>`).join("");
  return `<article class="free-card radar-card">${radarCover(game)}<div class="free-body"><h3 class="free-title">${escapeHtml(game.name || "Jogo sem título")}</h3>
    <p class="free-meta">${escapeHtml(game.release_date_raw || releaseDateLabel(game.release_date))}</p>
    ${tags ? `<div class="tag-row">${tags}</div>` : ""}
    ${game.status === "scheduled" ? '<p class="free-sub">Lançamento planejado · data sujeita a alteração</p>' : game.status === "released" ? '<p class="free-sub">Lançado</p>' : ""}
    ${game.stale ? '<p class="free-sub">Informação antiga: confirme a data na Steam.</p>' : ""}
    ${url ? `<a class="free-btn" href="${url}" target="_blank" rel="noopener noreferrer">Ver na Steam</a>` : '<p class="free-sub">Link indisponível</p>'}
    </div></article>`;
}
function renderReleases() {
  if (!RELEASES) return;
  const query = releaseNormalize(el("release-search").value);
  const tag = el("release-tag").value;
  const month = el("release-month").value;
  const dayFilter = el("release-day").value;
  const games = (RELEASES.releases || []).filter(g => releaseNormalize(g.name).includes(query) && (!tag || releaseTags(g).includes(tag)));
  const dated = games.filter(g => { const day = releaseDay(g.release_date); return day && (!month || day.startsWith(month + "-")) && (!dayFilter || day === dayFilter); });
  const tentative = games.filter(g => !releaseDay(g.release_date));
  const groups = new Map();
  for (const game of dated) { const day = releaseDay(game.release_date); if (!groups.has(day)) groups.set(day, []); groups.get(day).push(game); }
  el("release-count").textContent = `${dated.length} lançamentos com data nos filtros · ${tentative.length} previsões sem dia exato`;
  el("release-root").innerHTML = groups.size ? [...groups.keys()].sort().map(day => `<section><h2 class="free-h2">${escapeHtml(releaseDateLabel(day))}</h2><div class="free-grid">${groups.get(day).map(releaseCard).join("")}</div></section>`).join("") : '<p class="empty-tier">Nenhum lançamento com data nesses filtros. A cobertura é parcial; não significa que não existam lançamentos nesse período.</p>';
  el("release-tentative-root").innerHTML = tentative.length ? `<div class="free-grid">${tentative.map(releaseCard).join("")}</div>` : '<p class="empty-tier">Nenhuma previsão sem data exata com os interesses selecionados.</p>';
  const updated = RELEASES.updated_at || RELEASES.generated_at;
  const parsed = updated ? new Date(updated) : null;
  const timestamp = parsed && !Number.isNaN(parsed.getTime()) ? parsed.toLocaleString("pt-BR", {timeZone:"America/Sao_Paulo"}) : "não informada";
  const stale = RELEASES.stale || (RELEASES.sources || []).some(source => source.stale || source.status === "stale") || (RELEASES.releases || []).some(game => game.stale);
  el("release-status").textContent = `Última coleta: ${timestamp}.${stale ? " Há dados antigos: confirme as datas na Steam." : ""}`;
  const coverage = RELEASES.coverage;
  const fallback = "Cobertura parcial da Steam. Datas planejadas podem mudar; previsões por mês, trimestre ou ano permanecem sem dia exato.";
  if (typeof coverage === "string") el("release-coverage").textContent = coverage || fallback;
  else {
    const stats = [];
    if (Number.isFinite(coverage?.count)) stats.push(`${coverage.count.toLocaleString("pt-BR")} jogos coletados`);
    if (Number.isFinite(coverage?.exact_dates)) stats.push(`${coverage.exact_dates.toLocaleString("pt-BR")} com dia exato`);
    el("release-coverage").textContent = [stats.join(" · "), coverage?.note || fallback].filter(Boolean).join(". ");
  }
}
async function loadReleases() {
  if (releasesLoading) return;
  releasesLoading = true;
  el("release-refresh").disabled = true;
  el("release-status").textContent = "Carregando calendário de lançamentos…";
  try {
    const response = await fetch("/api/releases", {cache:"no-store"});
    if (!response.ok) throw new Error("Não foi possível carregar o calendário. Tente atualizar novamente.");
    const payload = await response.json();
    if (!payload || !Array.isArray(payload.releases)) throw new Error("O calendário retornou dados inválidos. Tente novamente.");
    RELEASES = payload;
    const previous = el("release-tag").value;
    const tags = [...new Set(payload.releases.flatMap(releaseTags))].sort((a,b)=>a.localeCompare(b,"pt-BR"));
    el("release-tag").innerHTML = '<option value="">Todas as tags</option>' + tags.map(t=>`<option value="${escapeHtml(t)}">${escapeHtml(t)}</option>`).join("");
    if (tags.includes(previous)) el("release-tag").value = previous;
    renderReleases();
  } catch (error) {
    el("release-status").textContent = `${error.message || "Calendário indisponível."}${RELEASES ? " Exibindo a última resposta recebida, que pode estar desatualizada." : ""}`;
  } finally {
    releasesLoading = false;
    el("release-refresh").disabled = false;
  }
}
document.addEventListener("DOMContentLoaded", () => {
  const button = document.createElement("button");
  button.className = "tab-btn"; button.dataset.tab = "releases"; button.textContent = "🗓️ Lançamentos Steam";
  button.addEventListener("click", () => switchTab("releases"));
  document.querySelector("nav.tabs").append(button);
  const section = document.createElement("section"); section.id = "tab-releases"; section.className = "hidden";
  section.innerHTML = `<p class="free-intro">O que chega à Steam, dia a dia, e o que está planejado. Previsões sem data exata ficam separadas da agenda.</p>
    <p class="sub" id="release-status" role="status" aria-live="polite"></p><button class="btn-primary" id="release-refresh">Atualizar calendário</button>
    <div class="filters"><input id="release-search" type="search" aria-label="Buscar lançamento" placeholder="Buscar jogo…">
      <label>Mês <input id="release-month" type="month" aria-label="Mês dos lançamentos"></label>
      <label>Dia <input id="release-day" type="date" aria-label="Dia dos lançamentos"></label>
      <select id="release-tag" aria-label="Tag dos lançamentos"><option value="">Todas as tags</option></select>
      <button class="secondary" id="release-clear">Limpar filtros</button></div>
    <p id="release-count" role="status"></p><div id="release-root"></div>
    <section><h2 class="free-h2">Sem data exata · planejados</h2><p class="free-intro">Mês, trimestre, ano ou “em breve”, conforme informado pela Steam. Filtros de mês e dia não se aplicam a estas previsões.</p><div id="release-tentative-root"></div></section>
    <p class="free-intro" id="release-coverage"></p>`;
  document.querySelector("footer").before(section);
  const todayParts = new Intl.DateTimeFormat("en", {year:"numeric", month:"2-digit", day:"2-digit", timeZone:"America/Sao_Paulo"}).formatToParts(new Date());
  el("release-month").value = todayParts.find(p => p.type === "year").value + "-" + todayParts.find(p => p.type === "month").value;
  el("release-day").value = el("release-month").value + "-" + todayParts.find(p => p.type === "day").value;
  for (const id of ["release-search", "release-tag"]) el(id).addEventListener("input", renderReleases);
  el("release-day").addEventListener("input", () => { if (el("release-day").value) el("release-month").value = el("release-day").value.slice(0,7); renderReleases(); });
  el("release-month").addEventListener("input", () => { el("release-day").value = ""; renderReleases(); });
  el("release-clear").onclick = () => { for (const id of ["release-search", "release-month", "release-day", "release-tag"]) el(id).value = ""; renderReleases(); };
  el("release-refresh").onclick = loadReleases;
});
