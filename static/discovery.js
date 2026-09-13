/* Requested radar tabs. Reuse the existing theme, cards and navigation. */
"use strict";
let RADAR = null;
let radarLoading = false;
const radarBaseSwitch = switchTab;
switchTab = function (tab) {
  radarBaseSwitch(tab);
  for (const name of ["crowd", "events"]) el("tab-" + name)?.classList.toggle("hidden", name !== tab);
  if (["crowd", "events"].includes(tab) && !RADAR && !radarLoading) loadRadar();
};
function radarLink(url) {
  try { const parsed = new URL(url); return parsed.protocol === "https:" ? escapeHtml(parsed.href) : "#"; }
  catch { return "#"; }
}
function radarCover(item) {
  const image = radarLink(item.image || item.header_img || "");
  const name = escapeHtml(item.name || "Conteúdo");
  return `<div class="free-cover radar-cover"><span class="radar-noimg"${image !== "#" ? ' hidden' : ""}>Prévia indisponível<span>${name}</span></span>${image !== "#" ? `<img src="${image}" alt="Prévia de ${name}" loading="lazy" decoding="async" data-radar-image>` : ""}</div>`;
}
function radarDescription(text) {
  const value = String(text || "");
  if (!value) return "";
  return value.length > 180
    ? `<details class="free-sub radar-description"><summary>${escapeHtml(value.slice(0, 160).trim())}… <span>ler descrição completa</span></summary><p>${escapeHtml(value)}</p></details>`
    : `<p class="free-sub radar-description">${escapeHtml(value)}</p>`;
}
document.addEventListener("error", event => {
  const image = event.target;
  if (!(image instanceof HTMLImageElement) || !image.hasAttribute("data-radar-image")) return;
  image.hidden = true;
  image.closest(".radar-cover")?.querySelector(".radar-noimg")?.removeAttribute("hidden");
}, true);
function radarDate(value) {
  if (!value) return "não informado";
  const date = new Date(value.length === 10 ? value + "T12:00:00Z" : value);
  return Number.isNaN(date.getTime()) ? "não informado" : date.toLocaleDateString("pt-BR", {timeZone:"America/Sao_Paulo"});
}
const radarNumber = value => Number(value || 0).toLocaleString("pt-BR", {maximumFractionDigits:1});
const radarNormalize = value => String(value || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
function radarSources() {
  return [...(RADAR.sources || []), ...(RADAR.extra_sources || [])].map(s =>
    `<a href="${radarLink(s.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(s.name || s.id)}</a>: ${s.status === "ok" ? "coletado" : s.status === "directory" ? "consulta manual" : "indisponível"}`).join(" · ");
}
function renderRadar() {
  if (!RADAR) return;
  const age = `Última coleta: ${radarDate(RADAR.updated_at)}. ${RADAR.stale ? "Dados vencidos: campanhas e indies ocultados até nova coleta." : ""}`;
  el("radar-status").textContent = age;
  el("events-status").textContent = age;
  el("radar-sources").innerHTML = radarSources();
  el("radar-coverage").textContent = RADAR.coverage || "Cobertura parcial das fontes públicas.";
  el("radar-methodology").textContent = RADAR.methodology || "";
  const kind = el("crowd-kind").value;
  const brazil = el("crowd-br").checked;
  const text = radarNormalize(el("crowd-search").value);
  const days = Number(el("crowd-days").value);
  const campaigns = (RADAR.campaigns || []).filter(c => (!kind || c.kind === kind) &&
    (!brazil || c.region === "BR") && (!days || c.days_left <= days) &&
    radarNormalize(c.name + " " + (c.tags || []).join(" ")).includes(text));
  el("crowd-count").textContent = `${campaigns.length} campanhas com tração verificada`;
  el("crowd-root").innerHTML = campaigns.length ? `<div class="free-grid radar-grid">${campaigns.map(c =>
    `<article class="free-card radar-card">${radarCover(c)}<div class="free-body"><h2 class="free-title">${escapeHtml(c.name)}</h2>
      <div class="free-sub">${escapeHtml(c.source)} · ${c.region === "BR" ? "Brasil" : "Internacional"} · ${escapeHtml(c.kind)}</div>
      <p>${radarNumber(c.funded_pct)}% da meta · ${radarNumber(c.backers)} apoiadores</p>
      <p class="free-meta">Encerra ${radarDate(c.end_date)} · tração ${radarNumber(c.score)}/100</p>
      ${radarDescription(c.description)}
      <p class="free-sub">${escapeHtml(c.brazil_note || "Entrega e frete para o Brasil não confirmados.")}</p>
      <p class="free-sub">Verificado ${radarDate(c.verified_at)} · ${(c.tags || []).map(escapeHtml).join(" · ")}</p>
      <a class="free-btn" href="${radarLink(c.url)}" target="_blank" rel="noopener noreferrer">Ver campanha e condições</a>
    </div></article>`).join("")}</div>` : '<p class="empty-tier">Nenhuma campanha verificada com esses filtros. Consulte o estado das fontes abaixo.</p>';
  const showIndies = (!kind || kind === "indie") && !brazil && !days;
  el("indie-section").classList.toggle("hidden", !showIndies);
  const indies = (RADAR.indie_games || []).filter(g => radarNormalize(g.name + " " + (g.tags || []).join(" ")).includes(text));
  el("indie-methodology").textContent = RADAR.indie_methodology || "Jogos já disponíveis, separados das campanhas de financiamento.";
  el("indie-root").innerHTML = indies.length ? `<div class="free-grid radar-grid">${indies.map(g =>
    `<article class="free-card radar-card">${radarCover(g)}<div class="free-body"><h3 class="free-title">${escapeHtml(g.name)}</h3>
      <p class="free-meta">${radarNumber(g.rating)}/5 · ${radarNumber(g.reviews)} avaliações · nota ajustada ${radarNumber(g.score)}/100</p>
      ${radarDescription(g.description)}<p class="free-sub">${(g.tags || []).map(escapeHtml).join(" · ")}</p>
      <p class="free-sub">${escapeHtml(g.note || "Confira preço, idioma e plataformas na página do criador.")}</p>
      <a class="free-btn" href="${radarLink(g.url)}" target="_blank" rel="noopener noreferrer">Conhecer no itch.io</a>
    </div></article>`).join("")}</div>` : '<p class="empty-tier">Nenhum indie verificado com esses filtros.</p>';
  const state = el("event-state").value, city = radarNormalize(el("event-city").value);
  const tag = el("event-tag").value, from = el("event-from").value, until = el("event-until").value;
  const events = (RADAR.events || []).filter(e => (!state || e.state === state) && radarNormalize(e.city).includes(city) &&
    (!tag || (e.tags || []).includes(tag)) && (!from || e.end_date.slice(0,10) >= from) && (!until || e.start_date.slice(0,10) <= until));
  el("event-count").textContent = `${events.length} eventos encontrados`;
  el("events-root").innerHTML = events.length ? `<div class="free-grid radar-grid">${events.map(e =>
    `<article class="free-card radar-card">${radarCover(e)}<div class="free-body"><h2 class="free-title">${escapeHtml(e.name)}</h2>
      ${e.image_kind?.includes("logo") ? `<p class="free-sub">${escapeHtml(e.image_caption || "Marca do evento; não representa a arte da edição.")}</p>` : ""}
      <p class="free-meta">${radarDate(e.start_date)}${e.start_date !== e.end_date ? " a " + radarDate(e.end_date) : ""}</p>
      <p>${escapeHtml(e.city)} · ${escapeHtml(e.state || "UF não informada")}<br>${escapeHtml(e.venue || "Local a confirmar")}</p>
      <p class="free-sub">${(e.tags || []).map(escapeHtml).join(" · ")}</p>
      <p class="free-sub">${e.stale ? "Informação antiga: confirmar programação. " : ""}${escapeHtml(e.note || "")}</p>
      <p class="free-sub">${e.collection === "aggregated" ? "Calendário público" : "Curadoria"} · verificado ${radarDate(e.verified_at)}</p>
      <a class="free-sub" href="${radarLink(e.source_url)}" target="_blank" rel="noopener noreferrer">Fonte da informação</a>
      <a class="free-btn" href="${radarLink(e.url || e.source_url)}" target="_blank" rel="noopener noreferrer">Ver evento e ingressos</a>
    </div></article>`).join("")}</div>` : '<p class="empty-tier">Nenhum evento com esses filtros. A cobertura é parcial; isso não significa que não existam eventos na região.</p>';
}
async function loadRadar() {
  radarLoading = true;
  for (const id of ["radar-status", "events-status"]) el(id).textContent = "Carregando fontes verificadas…";
  try {
    const response = await fetch("/api/discovery");
    if (!response.ok) throw new Error("Radar ainda indisponível. Tente atualizar novamente.");
    RADAR = await response.json();
    renderRadar();
  } catch (error) {
    for (const id of ["radar-status", "events-status"]) el(id).textContent = error.message || "Não foi possível carregar o radar.";
  } finally { radarLoading = false; }
}
document.addEventListener("DOMContentLoaded", () => {
  const nav = document.querySelector("nav.tabs");
  for (const [tab, title] of [["crowd", "🎲 Financiamento & Indies"], ["events", "📅 Eventos Brasil"]]) {
    const button = document.createElement("button");
    button.className = "tab-btn"; button.dataset.tab = tab; button.textContent = title;
    button.addEventListener("click", () => switchTab(tab)); nav.append(button);
  }
  const host = document.createElement("div");
  host.innerHTML = `<section id="tab-crowd" class="hidden">
    <p class="free-intro">Campanhas abertas com meta atingida e apoiadores suficientes. Tração não é avaliação do jogo nem garantia de entrega. Confira frete, impostos e idioma antes de apoiar.</p>
    <p id="radar-status" class="sub" role="status"></p><button class="btn-primary" id="radar-retry">Atualizar radar</button>
    <div class="filters"><input id="crowd-search" type="search" aria-label="Buscar campanha ou indie" placeholder="Buscar campanha ou indie…">
      <select id="crowd-kind" aria-label="Tipo de financiamento"><option value="">Todos os tipos</option><option value="boardgame">Boardgames</option><option value="indie">Indies digitais</option><option value="rpg">RPG de mesa</option></select>
      <select id="crowd-days" aria-label="Prazo da campanha"><option value="0">Qualquer prazo</option><option value="7">Encerra em até 7 dias</option><option value="30">Encerra em até 30 dias</option></select>
      <label><input id="crowd-br" type="checkbox"> Campanhas brasileiras</label></div>
    <p id="crowd-count" role="status"></p><div id="crowd-root"></div>
    <section id="indie-section"><h2 class="free-h2">Indies já disponíveis · itch.io</h2><p id="indie-methodology" class="free-intro"></p><div id="indie-root"></div></section>
    <details class="free-intro"><summary>Critérios e cobertura das fontes</summary><p id="radar-methodology"></p><p id="radar-coverage"></p><p id="radar-sources"></p></details>
  </section>
  <section id="tab-events" class="hidden"><p class="free-intro">Agenda de games, anime, boardgames e TCG no Brasil. Datas podem mudar: confira a fonte antes de comprar ingressos ou organizar a viagem.</p>
    <p id="events-status" class="sub" role="status"></p><button class="btn-primary" id="events-retry">Atualizar agenda</button>
    <div class="filters"><select id="event-state" aria-label="Estado"><option value="">Todo o Brasil</option>${"AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split(" ").map(uf=>`<option>${uf}</option>`).join("")}</select>
      <input id="event-city" type="search" aria-label="Cidade" placeholder="Cidade…">
      <select id="event-tag" aria-label="Tipo de evento"><option value="">Todos os eventos</option><option value="games">Games</option><option value="anime">Anime</option><option value="boardgame">Boardgames</option><option value="tcg">TCG</option></select>
      <label>De <input id="event-from" type="date" aria-label="Eventos a partir de"></label><label>Até <input id="event-until" type="date" aria-label="Eventos até"></label>
      <button class="secondary" id="event-clear">Limpar filtros</button></div>
    <p id="event-count" role="status"></p><div id="events-root"></div>
  </section>`;
  document.querySelector("footer").before(host);
  for (const id of ["crowd-search", "crowd-kind", "crowd-days", "crowd-br", "event-state", "event-city", "event-tag", "event-from", "event-until"])
    el(id).addEventListener("input", renderRadar);
  el("event-clear").onclick = () => { for (const id of ["event-state", "event-city", "event-tag", "event-from", "event-until"]) el(id).value = ""; renderRadar(); };
  el("radar-retry").onclick = el("events-retry").onclick = () => { if (!radarLoading) loadRadar(); };
});
