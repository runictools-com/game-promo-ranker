/* ═══════════════════════════════════════════════════════════════════════════
   Game Promo Ranker — frontend (v2)
   - fetch('/api/games') → cards ou tabela por bloco, com gauge de score,
     selo de qualidade de preço, sparkline, Steam Deck, gênero e multi-loja
   - favoritos (localStorage) + tema claro/escuro (localStorage)
   - perfil Steam: grifa wishlist e remove owned
   ═══════════════════════════════════════════════════════════════════════════ */
"use strict";

// ─── Estado ─────────────────────────────────────────────────────────────────
let PAYLOAD = null;
let WISHLIST = new Set();
let OWNED = new Set();
let COMPARE_ACTIVE = false;
let TAGS = { fav: false, new: false, hist: false, wish: false };
let FREE_PAYLOAD = null, EPIC_PAYLOAD = null, EPIC_ONLY_CHEAPER = false, GP_PAYLOAD = null;

const SCORE_CUTOFF = 7.0;
const LS = { view: "ssr_view", theme: "ssr_theme", favs: "ssr_favs", tastes: "ssr_tastes_v2" };

let VIEW = "cards";                 // "cards" | "table"
let FAVS = new Set();               // appids favoritados

// ─── Persistência ───────────────────────────────────────────────────────────
function lsGet(k, def) { try { return localStorage.getItem(k) ?? def; } catch { return def; } }
function lsSet(k, v) { try { localStorage.setItem(k, v); } catch {} }
function loadFavs() {
  try { FAVS = new Set(JSON.parse(localStorage.getItem(LS.favs) || "[]").map(String)); }
  catch { FAVS = new Set(); }
}
function saveFavs() { lsSet(LS.favs, JSON.stringify([...FAVS])); }

// ─── Helpers ────────────────────────────────────────────────────────────────
function el(id) { return document.getElementById(id); }
function escapeHtml(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
function setStatus(msg, cls) {
  const n = el("profile-status");
  n.textContent = msg || "";
  n.className = "profile-status " + (cls || "info");
}
// "R$ 1.299,90" → 1299.90 ; vazio → Infinity
function priceNum(s) {
  let t = String(s || "").replace(/[^\d.,]/g, "");
  if (!t) return Infinity;
  t = t.includes(",") ? t.replace(/\./g, "").replace(",", ".") : t;
  const n = parseFloat(t);
  return isNaN(n) ? Infinity : n;
}
function headerImg(g) {
  if (g.header_img) return g.header_img;
  if (g.appid) return `https://cdn.cloudflare.steamstatic.com/steam/apps/${g.appid}/header.jpg`;
  return g.img_url || "";
}
// Banda de cor do score (a..e) — resolve pela variável CSS, então é theme-aware.
function scoreBand(s) {
  s = Number(s) || 0;
  if (s >= 8.5) return "a";
  if (s >= 7.0) return "b";
  if (s >= 5.5) return "c";
  if (s >= 4.0) return "d";
  return "e";
}
function allGames() {
  const o = [];
  for (const b of (PAYLOAD?.blocks || [])) for (const g of b.games) o.push({ g, color: b.color || "#888" });
  return o;
}

// Selo de qualidade do preço (a partir de low_price_brl vs sale_price — já no JSON).
function priceLowHtml(g) {
  const low = g.price_low;
  if (!low || !Number.isInteger(low.price_cents)) return '<span class="price-low muted">Mínima Steam: aguardando preço verificado</span>';
  const price = (low.price_cents/100).toLocaleString('pt-BR', {style:'currency',currency:'BRL'});
  const date = value => value ? new Date(value).toLocaleDateString('pt-BR', {timeZone:'America/Sao_Paulo'}) : '';
  const since = date(low.first_seen);
  if (low.historical) {
    const source = /^https:\/\/isthereanydeal\.com\//.test(low.source_url || '') ? `<a href="${escapeHtml(low.source_url)}" target="_blank" rel="noopener noreferrer">IsThereAnyDeal</a>` : 'IsThereAnyDeal';
    return `<span class="price-low">Baixa histórica Steam: <b>${price}</b>${low.new_low ? ' · nova mínima' : ''}<small>${low.low_at ? `Em ${escapeHtml(date(low.low_at))} · ` : ''}${source} · salvo localmente</small></span>`;
  }
  const status = low.new_low ? ' · nova mínima registrada' : low.observation_days <= 1 ? ' · primeiro registro' : '';
  return `<span class="price-low" title="Histórico externo ainda indisponível; este valor é o menor observado pelo aplicativo.">Menor observado Steam: <b>${price}</b>${status}<small>Baixa histórica: aguardando fonte${since ? ` · desde ${escapeHtml(since)}` : ''}</small></span>`;
}
function steamSnapshotStale() {
  if (!PAYLOAD) return false;
  const raw = PAYLOAD.generated_at || "";
  const stamp = /(?:Z|[+-]\d{2}:\d{2})$/.test(raw) ? Date.parse(raw) : NaN;
  return !Number.isFinite(stamp) || Date.now() - stamp >= 36*3600000 || stamp > Date.now()+300000;
}
function qualityTier(g) {
  if (steamSnapshotStale()) return null;
  const low = g.price_low ? g.price_low.price_cents/100 : priceNum(g.low_price_brl), sale = priceNum(g.sale_price);
  const dates = new Set((g.price_history || []).map(p => p.d));
  const known = g.price_low ? (g.price_low.historical || g.price_low.observation_days >= 2) : g.score_components?.observed_price_proximity != null || dates.size >= 2;
  const reliableLow = g.price_low?.historical || g.low_src === "obs";
  if (!reliableLow || !known || !isFinite(low) || low <= 0 || !isFinite(sale) || sale <= 0) return null;
  const ratio = sale / low;
  return { tier: sale <= low + 0.005 ? "best" : ratio <= 1.10 ? "great" : ratio <= 1.25 ? "good" : "ok",
    label: g.price_low?.historical ? (sale <= low + 0.005 ? "BAIXA HISTÓRICA" : "VS. BAIXA HISTÓRICA") : (sale <= low + 0.005 ? "MENOR OBSERVADO" : "VS. MENOR OBSERVADO"),
    atLow: sale <= low + 0.005, pctAbove: Math.max(0, Math.round((ratio-1)*100)), lowStr: low.toLocaleString('pt-BR', {style:'currency',currency:'BRL'}),
    since: g.low_observed_since ? String(g.low_observed_since).slice(0,10) : "período acompanhado" };
}
function isObservedLow(g) { const q = qualityTier(g); return !!q && q.atLow; }
function historicalPriceState(g) {
  const q = qualityTier(g);
  if (!q || !g.price_low?.historical) return null;
  if (q.atLow) return "historical-low";
  return q.tier === "great" ? "historical-near" : null;
}
function dealPct(g) { return qualityTier(g)?.pctAbove ?? Infinity; }
function qsealHtml(g) {
  const q = qualityTier(g);
  if (!q) return `<span class="muted">${steamSnapshotStale() ? "Oferta pode ter vencido: confira na Steam" : g.price_low ? "Preço registrado; acumulando histórico" : "Histórico BR insuficiente"}</span>`;
  const tip = g.price_low?.historical ? "Mínima Steam Brasil: histórico IsThereAnyDeal e novas mínimas verificadas pelo aplicativo." : `Menor BRL observado desde ${q.since}; somente datas coletadas, não mínimo de todos os tempos.`;
  return `<span class="qseal ${q.tier}" title="${escapeHtml(tip)}">${q.label}<span class="pct">+${q.pctAbove}%</span><span class="qseal-low">↓ ${escapeHtml(q.lowStr)}</span></span>`;
}
function scoreDetails(g) {
  if (g.quality_score == null || g.deal_score == null) return "";
  return `Wilson ${Number(g.quality_score).toFixed(1)} · oferta ${Number(g.deal_score).toFixed(1)} · confiança ${g.confidence === "high" ? "alta" : "moderada"}`;
}

// Steam Deck
const DECK = {
  verified:    { cls: "verified",    ic: "✔", t: "Steam Deck: Verificado" },
  playable:    { cls: "playable",    ic: "◐", t: "Steam Deck: Jogável" },
  unsupported: { cls: "unsupported", ic: "✕", t: "Steam Deck: Não suportado" },
  unknown:     { cls: "unknown",     ic: "?", t: "Steam Deck: Não testado" },
};
function deckPill(g, coverStyle) {
  const d = DECK[g.deck];
  if (!d) return "";
  if (coverStyle && (g.deck === "unsupported" || g.deck === "unknown")) return ""; // só os bons na capa
  return `<span class="deck ${d.cls}" title="${d.t}">${d.ic} Deck</span>`;
}

// Sparkline SVG a partir de price_history [{d,p}, ...]
function sparkline(hist) {
  if (!Array.isArray(hist) || hist.length < 2) return "";
  const w = 92, h = 26, pad = 3, n = hist.length;
  const ps = hist.map((x) => Number(x.p) || 0);
  const min = Math.min(...ps), max = Math.max(...ps), span = (max - min) || 1;
  const pts = hist.map((x, i) => [
    pad + i * (w - 2 * pad) / (n - 1),
    pad + (1 - ((Number(x.p) || 0) - min) / span) * (h - 2 * pad),
  ]);
  const line = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  const last = pts[n - 1];
  const down = ps[n - 1] <= ps[0];
  const col = down ? "var(--green)" : "var(--accent)";
  const area = `${line} L ${last[0].toFixed(1)} ${h - pad} L ${pad.toFixed(1)} ${h - pad} Z`;
  const tip = `histórico: R$ ${min.toFixed(2)}–${max.toFixed(2)} (${n} pontos)`;
  return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img" aria-label="${escapeHtml(tip)}"><title>${escapeHtml(tip)}</title>
    <path d="${area}" fill="${col}" opacity="0.13"/>
    <path d="${line}" fill="none" stroke="${col}" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>
    <circle cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="2.3" fill="${col}"/></svg>`;
}

// Melhor loja (multi-store). Só destaca quando outra loja é ESTRITAMENTE mais
// barata que a Steam (empate não conta), com o % de economia.
function storeBestHtml(g) {
  const st = g.stores;
  if (!Array.isArray(st) || st.length < 2) return "";
  const steam = st.find((s) => s.store === "Steam");
  const others = st.filter((s) => s.store !== "Steam" && isFinite(s.price_brl) && s.price_brl > 0);
  if (!others.length) return "";
  const cheapest = others.slice().sort((a, b) => a.price_brl - b.price_brl)[0];
  const steamPrice = steam ? Number(steam.price_brl) : Infinity;
  if (!(cheapest.price_brl < steamPrice - 0.01)) return "";
  const save = isFinite(steamPrice) ? Math.round(100 * (steamPrice - cheapest.price_brl) / steamPrice) : 0;
  return `<div class="store-best win" title="Mais barato fora da Steam">🏷️ Melhor:
    <a href="${escapeHtml(cheapest.url || "#")}" target="_blank" rel="noopener">${escapeHtml(cheapest.store)} ${escapeHtml(cheapest.price)}</a>${save > 0 ? ` <span class="save-pct">−${save}%</span>` : ""}</div>`;
}

function gaugeHtml(score) {
  const s = Number(score) || 0;
  const w = Math.max(3, Math.min(100, s * 10));
  const band = scoreBand(s);
  return `<span class="gauge"><i style="width:${w}%;background:var(--sc-${band})"></i></span>
          <span class="score-num" style="color:var(--sc-${band})">${s.toFixed(1)}</span>`;
}

// ─── Card ───────────────────────────────────────────────────────────────────
function itemCard(g, rank, isTail) {
  const appid = String(g.appid || "");
  if (COMPARE_ACTIVE && OWNED.has(Number(appid))) return "";
  const wished = COMPARE_ACTIVE && WISHLIST.has(Number(appid));
  const isFav = FAVS.has(appid);
  const historicalState = historicalPriceState(g);
  const cls = ["card"];
  if (isTail) cls.push("tail-row");
  if (historicalState) cls.push(historicalState);

  const ribbon =
    (g.is_new ? '<span class="chip new">NEW</span>' : "") +
    (historicalState === "historical-low" ? '<span class="chip historical-low">★ baixa histórica</span>' :
      historicalState === "historical-near" ? '<span class="chip historical-near">perto da baixa</span>' :
      isObservedLow(g) ? '<span class="chip hist">★ menor observado</span>' : "") +
    (wished ? '<span class="chip wish">wishlist</span>' : "");

  const tags = (g.tags || g.genres || []).slice(0, 3)
    .map((t) => `<span class="tag">${escapeHtml(t)}</span>`).join("");
  const cover = headerImg(g);
  const coverImg = cover ? `<img src="${escapeHtml(cover)}" alt="" loading="lazy">` : "";
  const spark = sparkline(g.price_history);
  const lowLine = priceLowHtml(g);

  return `
    <div class="${cls.join(" ")}" data-appid="${escapeHtml(appid)}">
      <div class="card-cover">
        ${coverImg}<div class="shade"></div>
        <span class="disc-badge">-${g.discount}%</span>
        <div class="ribbon">${ribbon}</div>
        ${deckPill(g, true) ? `<div class="deck-cover">${deckPill(g, true)}</div>` : ""}
        <button class="fav-btn${isFav ? " on" : ""}" data-fav="${escapeHtml(appid)}" title="${isFav ? "Remover dos favoritos" : "Favoritar"}" aria-pressed="${isFav}">${isFav ? "★" : "☆"}</button>
      </div>
      <div class="card-body">
        <a class="card-title" href="${escapeHtml(g.url || "#")}" target="_blank" rel="noopener"><span class="nm">${escapeHtml(g.name)}</span></a>
        ${tags ? `<div class="tag-row">${tags}</div>` : ""}
        <div class="meta-row"><span class="pos">${g.pct_positive}%</span> positivas · ${escapeHtml(g.reviews_human ?? g.total_reviews)} reviews</div>
        <div class="price-row">
          <span class="price-sale">${escapeHtml(g.sale_price || "")}</span>
          ${g.orig_price ? `<span class="price-orig">${escapeHtml(g.orig_price)}</span>` : ""}
        </div>
        ${qsealHtml(g)}
        ${(spark || lowLine) ? `<div class="spark-row">${spark}${lowLine}</div>` : ""}
        ${storeBestHtml(g)}
        <div class="meta-row" title="${escapeHtml(g.score_rationale || "")}">${escapeHtml(scoreDetails(g))}</div>
        <div class="card-foot">${gaugeHtml(g.score)}</div>
      </div>
    </div>`;
}

// ─── Linha da tabela ────────────────────────────────────────────────────────
function itemRow(g, rank, isTail) {
  const appid = String(g.appid || "");
  if (COMPARE_ACTIVE && OWNED.has(Number(appid))) return "";
  const wished = COMPARE_ACTIVE && WISHLIST.has(Number(appid));
  const isFav = FAVS.has(appid);
  const historicalState = historicalPriceState(g);

  const trCls = [];
  if (isTail) trCls.push("tail-row");
  if (g.is_new) trCls.push("new-row");
  if (historicalState) trCls.push(historicalState);
  else if (isObservedLow(g)) trCls.push("hist-low");
  if (isFav) trCls.push("faved");
  if (wished) trCls.push("wishlisted");

  const badges =
    (g.is_new ? '<span class="badge-inline new">NEW</span>' : "") +
    (historicalState === "historical-low" ? '<span class="badge-inline historical-low">BAIXA HISTÓRICA</span>' :
      historicalState === "historical-near" ? '<span class="badge-inline historical-near">PERTO DA BAIXA</span>' :
      isObservedLow(g) ? '<span class="badge-inline hist">OBSERVADO</span>' : "") +
    (wished ? '<span class="badge-inline wish">WISH</span>' : "");
  const img = g.img_url ? `<img src="${escapeHtml(g.img_url)}" alt="" loading="lazy">` : "";
  const deck = deckPill(g, false);
  const qseal = qsealHtml(g);
  const lowCell = priceLowHtml(g);

  return `
    <tr${trCls.length ? ` class="${trCls.join(" ")}"` : ""} data-appid="${escapeHtml(appid)}">
      <td class="fav"><button class="fav-btn-t${isFav ? " on" : ""}" data-fav="${escapeHtml(appid)}" title="Favoritar" aria-pressed="${isFav}">${isFav ? "★" : "☆"}</button></td>
      <td class="rank">${rank}</td>
      <td class="name"><a href="${escapeHtml(g.url || "#")}" target="_blank" rel="noopener">${img}<span class="t-nm">${escapeHtml(g.name)}${deck ? " " + deck : ""}${badges}</span></a></td>
      <td class="disc">-${g.discount}%</td>
      <td class="pct">${g.pct_positive}%</td>
      <td class="reviews">${escapeHtml(g.reviews_human ?? g.total_reviews)}</td>
      <td class="orig">${escapeHtml(g.orig_price || "")}</td>
      <td class="sale">${escapeHtml(g.sale_price || "")}</td>
      <td class="low-ever">${lowCell}</td>
      <td class="score-cell" title="${escapeHtml(scoreDetails(g))}"><span class="sc-wrap">${gaugeHtml(g.score)}</span></td>
    </tr>`;
}

function tableHead(sort) {
  const arrow = (key) => `<span class="arrow">${sort === key ? "▼" : "⇅"}</span>`;
  const cls = (key) => `sortable${sort === key ? " sorted" : ""}`;
  return `<thead><tr>
    <th></th><th>#</th><th>Nome</th>
    <th class="${cls("discount")}" data-sort="discount">Desc ${arrow("discount")}</th>
    <th class="${cls("pct")}" data-sort="pct">Rev% ${arrow("pct")}</th>
    <th class="col-reviews ${cls("reviews")}" data-sort="reviews">Reviews ${arrow("reviews")}</th>
    <th class="col-orig">Original</th>
    <th class="${cls("price")}" data-sort="price">Promo ${arrow("price")}</th>
    <th class="${cls("deal")}" data-sort="deal">Baixa histórica ${arrow("deal")}</th>
    <th class="${cls("score")}" data-sort="score">Score ${arrow("score")}</th>
  </tr></thead>`;
}

// ─── Contêineres (bloco / lista plana) ──────────────────────────────────────
function blockContainer(block, sort) {
  const color = block.color || "#888";
  let top = "", tail = "", topN = 0, tailN = 0, rank = 0;
  for (const g of block.games) {
    rank += 1;
    const isTail = Number(g.score) < SCORE_CUTOFF;
    const r = VIEW === "cards" ? itemCard(g, rank, isTail) : itemRow(g, rank, isTail);
    if (!r) continue;
    if (isTail) { tail += r; tailN += 1; } else { top += r; topN += 1; }
  }
  const total = topN + tailN;
  if (!total) return "";
  const collapsed = tailN > 0 ? " tail-collapsed" : "";
  const toggle = tailN > 0
    ? `<button class="tail-toggle" data-count="${tailN}" aria-expanded="false">▸ Ver mais ${tailN} jogos (score abaixo de ${SCORE_CUTOFF})</button>` : "";

  const header = `<div class="block-header"><span class="block-dot" style="background:${color}"></span>
      <span class="block-name">${escapeHtml(block.name)}</span><span class="block-count">${total} jogos</span></div>`;

  const body = VIEW === "cards"
    ? `<div class="cards-grid">${top}${tail}</div>`
    : `<div class="table-scroll"><table>${tableHead(sort)}<tbody>${top}${tail}</tbody></table></div>`;
  return `<div class="block${collapsed}">${header}${body}${toggle}</div>`;
}

function flatContainer(items, label, sort) {
  let body = "", rank = 0;
  for (const it of items) {
    const r = VIEW === "cards" ? itemCard(it.g, rank + 1, false) : itemRow(it.g, rank + 1, false);
    if (r) { body += r; rank += 1; }
  }
  if (!rank) return "";
  const header = `<div class="block-header"><span class="block-dot" style="background:var(--accent)"></span>
      <span class="block-name">${escapeHtml(label)}</span><span class="block-count">${rank} jogos</span></div>`;
  const inner = VIEW === "cards"
    ? `<div class="cards-grid">${body}</div>`
    : `<div class="table-scroll"><table>${tableHead(sort)}<tbody>${body}</tbody></table></div>`;
  return `<div class="block">${header}${inner}</div>`;
}

// ─── Filtros ────────────────────────────────────────────────────────────────
function filterState() {
  return {
    q: (((el("f-search") || {}).value) || "").trim().toLowerCase(),
    genre: el("f-genre")?.value || "",
    includeTags: selectedValues("f-tags-include"), excludeTags: selectedValues("f-tags-exclude"),
    category: el("f-category")?.value || "", budget: Number(el("f-budget")?.value || 0),
    gems: !!el("f-gems")?.checked,
    minDisc: Number(((el("f-discount") || {}).value) || 0),
    minPct: Number(((el("f-review") || {}).value) || 0),
    sort: ((el("f-sort") || {}).value) || "score",
    tagFav: TAGS.fav, tagNew: TAGS.new, tagHist: TAGS.hist, tagWish: TAGS.wish,
  };
}
function filtersActive(f) {
  return f.includeTags.length > 0 || f.excludeTags.length > 0 || !!f.category || f.budget > 0 || f.gems || !!f.q || !!f.genre || f.minDisc > 0 || f.minPct > 0 || f.sort !== "score" ||
    f.tagFav || f.tagNew || f.tagHist || f.tagWish;
}
function passesFilter(g, f) {
  if (f.q && !String(g.name || "").toLowerCase().includes(f.q)) return false;
  if (f.genre) {
    const pool = (g.genres || []).map((x) => String(x).toLowerCase());
    if (!pool.includes(f.genre.toLowerCase())) return false;
  }
  const gameTags = new Set(g.tags || []);
  if (f.includeTags.some(t => !gameTags.has(t)) || f.excludeTags.some(t => gameTags.has(t))) return false;
  if (f.category && !(g.categories || []).includes(f.category)) return false;
  if (f.budget > 0 && priceNum(g.sale_price) > f.budget) return false;
  if (f.gems && !g.hidden_gem) return false;
  if (f.minDisc && Number(g.discount) < f.minDisc) return false;
  if (f.minPct && Number(g.pct_positive) < f.minPct) return false;
  if (f.tagFav && !FAVS.has(String(g.appid))) return false;
  if (f.tagNew && !g.is_new) return false;
  if (f.tagHist && historicalPriceState(g) !== "historical-low") return false;
  if (f.tagWish && !(COMPARE_ACTIVE && WISHLIST.has(Number(g.appid)))) return false;
  return true;
}
function flatLabel(f) {
  const onlyTag = !f.q && !f.genre && !f.minDisc && !f.minPct;
  const tags = [f.tagFav && "fav", f.tagNew && "new", f.tagHist && "hist", f.tagWish && "wish"].filter(Boolean);
  if (onlyTag && tags.length === 1)
    return { fav: "★ Seus favoritos", new: "Novidades de hoje", hist: "Menores preços observados", wish: "Sua wishlist em promoção" }[tags[0]];
  return "Resultado dos filtros";
}
function sortGames(arr, sort) {
  const cmp = {
    score: (a, b) => b.g.score - a.g.score,
    discount: (a, b) => b.g.discount - a.g.discount,
    deal: (a, b) => dealPct(a.g) - dealPct(b.g),
    reviews: (a, b) => b.g.total_reviews - a.g.total_reviews,
    pct: (a, b) => (b.g.pct_positive - a.g.pct_positive) || (b.g.total_reviews - a.g.total_reviews),
    price: (a, b) => priceNum(a.g.sale_price) - priceNum(b.g.sale_price),
  }[sort] || ((a, b) => b.g.score - a.g.score);
  arr.sort(cmp);
}

// ─── Render principal ───────────────────────────────────────────────────────
function renderGames() {
  if (!PAYLOAD) return;
  const root = el("games-root");
  const f = filterState();
  const active = filtersActive(f);
  const fc = el("f-clear");
  if (fc) fc.classList.toggle("hidden", !active);

  const items = allGames().filter(({ g }) => !(COMPARE_ACTIVE && OWNED.has(Number(g.appid))) && passesFilter(g, f));
  sortGames(items, f.sort);
  root.innerHTML = flatContainer(items, active ? flatLabel(f) : "Ranking geral de oportunidades", f.sort) ||
    '<div class="empty-tier">Nenhum jogo com esses filtros.</div>';
  wireDynamic();
}

// Liga os controles renderizados dinamicamente (tail toggles + sort headers).
function wireDynamic() {
  el("games-root").querySelectorAll(".tail-toggle").forEach((btn) => btn.addEventListener("click", toggleTail));
  el("games-root").querySelectorAll("th.sortable").forEach((th) => th.addEventListener("click", () => {
    const sel = el("f-sort"); if (sel) { sel.value = th.dataset.sort; renderGames(); }
  }));
}
function toggleTail(e) {
  const btn = e.currentTarget, block = btn.closest(".block");
  if (!block) return;
  const opened = block.classList.toggle("tail-collapsed") === false;
  btn.setAttribute("aria-expanded", String(opened));
  const n = btn.dataset.count || "";
  btn.textContent = opened
    ? `▾ Ocultar os ${n} jogos com score abaixo de ${SCORE_CUTOFF}`
    : `▸ Ver mais ${n} jogos (score abaixo de ${SCORE_CUTOFF})`;
}

// ─── Hero: stats ao vivo + gênero ───────────────────────────────────────────
function renderSubtitle() {
  if (!PAYLOAD) return;
  const stamp = new Date(PAYLOAD.generated_at);
  const when = Number.isNaN(stamp.getTime()) ? "data não informada" : stamp.toLocaleString("pt-BR", {timeZone:"America/Sao_Paulo"});
  const total = PAYLOAD.total_collected != null ? PAYLOAD.total_collected : "—";
  const coverage = PAYLOAD.coverage;
  el("subtitle").textContent = `Atualizado em ${when} · ${total} jogos rankeados` +
    (coverage ? ` · amostra de ${coverage.pages_scanned || 0} páginas, não catálogo completo` : "") +
    (steamSnapshotStale() ? " · DADOS VENCIDOS: ofertas podem ter terminado. Confira preço e disponibilidade na Steam." : "");
}
function renderStats() {
  if (!PAYLOAD) return;
  const games = allGames().map((x) => x.g);
  const total = PAYLOAD.total_collected ?? games.length;
  const histLow = games.filter((g) => historicalPriceState(g) === "historical-low").length;
  const favOnSale = games.filter((g) => FAVS.has(String(g.appid)));
  const favLow = favOnSale.filter((g) => historicalPriceState(g) === "historical-low").length;
  let best = games[0] || null;
  for (const g of games) if (!best || g.score > best.score) best = g;

  const tiles = [
    { cls: "", k: total, l: "jogos rankeados" },
    { cls: "is-violet", k: histLow, l: "na <b>baixa histórica</b>" },
    { cls: "is-violet clickable", k: FAVS.size, l: favLow ? `favoritos · <b>${favLow} na baixa histórica</b>` : "favoritos salvos", act: "fav" },
    { cls: "is-green", k: best ? best.score.toFixed(1) : "—", l: best ? `melhor: <b>${escapeHtml(best.name.slice(0, 22))}</b>` : "melhor score" },
  ];
  el("stat-strip").innerHTML = tiles.map((t) =>
    `<div class="stat-tile ${t.cls}"${t.act ? ` data-act="${t.act}" style="cursor:pointer"` : ""}>
      <div class="k">${t.k}</div><div class="l">${t.l}</div></div>`).join("");
  el("stat-strip").querySelectorAll("[data-act='fav']").forEach((n) =>
    n.addEventListener("click", () => toggleTag("fav")));
}
function selectedValues(id) { return Array.from(el(id)?.selectedOptions || [], o => o.value); }
function savedTastes() { try { return JSON.parse(lsGet(LS.tastes, "{}")) || {}; } catch { return {}; } }
function saveTastes() {
  const f = filterState();
  lsSet(LS.tastes, JSON.stringify({genre:f.genre, category:f.category, includeTags:f.includeTags,
    excludeTags:f.excludeTags, budget:f.budget, gems:f.gems}));
}
function populateGenres() {
  const tastes = savedTastes();
  for (const [id, field, key, label] of [["f-genre","genres","genre","Todos os gêneros"],
    ["f-category","categories","category","Todos os recursos"],
    ["f-tags-include","tags","includeTags",null], ["f-tags-exclude","tags","excludeTags",null]]) {
    const node = el(id); if (!node) continue;
    const saved = tastes[key] || (label ? "" : []);
    const choices = new Set(allGames().flatMap(({g}) => g[field] || []));
    for (const v of (Array.isArray(saved) ? saved : [saved])) if(v) choices.add(v);
    node.innerHTML = (label ? `<option value="">${label}</option>` : "") +
      [...choices].sort((a,b)=>a.localeCompare(b)).map(x=>`<option value="${escapeHtml(x)}">${escapeHtml(x)}</option>`).join("");
    for (const option of node.options) option.selected = Array.isArray(saved) ? saved.includes(option.value) : option.value === saved;
  }
  if(el("f-budget")) el("f-budget").value = tastes.budget || "";
  if(el("f-gems")) el("f-gems").checked = !!tastes.gems;
}

// ─── Favoritos ──────────────────────────────────────────────────────────────
function toggleFav(appid) {
  appid = String(appid);
  if (FAVS.has(appid)) FAVS.delete(appid); else FAVS.add(appid);
  saveFavs();
  // atualiza os botões no DOM sem re-render (mantém scroll)
  document.querySelectorAll(`[data-fav="${CSS.escape(appid)}"]`).forEach((btn) => {
    const on = FAVS.has(appid);
    btn.classList.toggle("on", on);
    btn.textContent = on ? "★" : "☆";
    btn.setAttribute("aria-pressed", String(on));
    const card = btn.closest(".card"); if (card) card.classList.toggle("faved-card", on);
    const row = btn.closest("tr"); if (row) row.classList.toggle("faved", on);
  });
  renderStats();
  if (TAGS.fav) renderGames();      // se o filtro de favoritos está ativo, refaz a lista
}

// ─── View toggle + tema ─────────────────────────────────────────────────────
function setView(v) {
  VIEW = v === "table" ? "table" : "cards";
  lsSet(LS.view, VIEW);
  document.querySelectorAll("#view-toggle button").forEach((b) => b.classList.toggle("active", b.dataset.view === VIEW));
  renderGames();
}
function applyTheme(t) {
  document.documentElement.setAttribute("data-theme", t);
  lsSet(LS.theme, t);
  const btn = el("theme-btn");
  if (btn) btn.textContent = t === "light" ? "☀️" : "🌙";
}
function toggleTheme() {
  applyTheme(document.documentElement.getAttribute("data-theme") === "light" ? "dark" : "light");
}

// ─── Tags / limpar ──────────────────────────────────────────────────────────
function toggleTag(tag) {
  if (tag === "wish" && !COMPARE_ACTIVE) { setStatus("Compare seu perfil primeiro para filtrar pela wishlist.", "warn"); return; }
  if (tag === "fav" && FAVS.size === 0 && !TAGS.fav) { setStatus("Você ainda não favoritou nenhum jogo (clique na ★ de um card).", "info"); return; }
  TAGS[tag] = !TAGS[tag];
  syncTagUI();
  renderGames();
}
function syncTagUI() {
  document.querySelectorAll(".legend .legend-item").forEach((n) => n.classList.toggle("active", !!TAGS[n.dataset.tag]));
  const wb = el("wishonly-btn");
  if (wb) { wb.classList.toggle("active", TAGS.wish); wb.textContent = TAGS.wish ? "✕ Ver todos os jogos" : "★ Ver apenas wishlist"; }
}
function clearFilters() {
  ["f-search"].forEach((id) => { if (el(id)) el(id).value = ""; });
  if (el("f-genre")) el("f-genre").value = "";
  if (el("f-discount")) el("f-discount").value = "0";
  if (el("f-review")) el("f-review").value = "0";
  if (el("f-sort")) el("f-sort").value = "score";
  for(const id of ["f-tags-include","f-tags-exclude"]) for(const o of el(id)?.options || []) o.selected=false;
  if(el("f-category")) el("f-category").value="";
  if(el("f-budget")) el("f-budget").value="";
  if(el("f-gems")) el("f-gems").checked=false;
  saveTastes();
  TAGS.fav = TAGS.new = TAGS.hist = TAGS.wish = false;
  syncTagUI(); renderGames();
}

// ─── Abas ───────────────────────────────────────────────────────────────────
function setupTabs() {
  document.querySelectorAll(".tab-btn").forEach((btn) => btn.addEventListener("click", () => switchTab(btn.dataset.tab)));
}
function switchTab(tab) {
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  el("tab-deals").classList.toggle("hidden", tab !== "deals");
  el("tab-epic").classList.toggle("hidden", tab !== "epic");
  el("tab-free").classList.toggle("hidden", tab !== "free");
  el("tab-gamepass").classList.toggle("hidden", tab !== "gamepass");
  if (tab === "free" && FREE_PAYLOAD === null) loadFreeGames();
  if (tab === "epic" && EPIC_PAYLOAD === null) loadEpicGames();
  if (tab === "gamepass" && GP_PAYLOAD === null) loadGamepass();
}
function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "" : d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric" });
}

// ─── Grátis (Epic + PSN) ────────────────────────────────────────────────────
function freeCard(item, kind) {
  const cover = item.cover ? `<img src="${escapeHtml(item.cover)}" alt="" loading="lazy">` : '<div class="free-noimg">🎮</div>';
  const plat = String(item.platform || "epic");
  const platLabel = { epic: "Epic", psn: "PSN", prime: "Prime", gog: "GOG" }[plat] || plat;
  let meta = "";
  if (kind === "current") meta = item.free_until ? "Grátis até " + fmtDate(item.free_until) : "Grátis agora";
  else if (kind === "upcoming") meta = item.free_from ? "Grátis a partir de " + fmtDate(item.free_from) : "Em breve";
  else meta = item.first_seen ? "Foi grátis em " + fmtDate(item.first_seen) : "";
  const orig = item.orig_price ? `<span class="free-orig">${escapeHtml(item.orig_price)}</span>` : "";
  const btnLabel = kind === "current" ? "Resgatar grátis" : "Ver na loja";
  const btnCls = kind === "current" ? "free-btn" : "free-btn soon";
  return `<div class="free-card ${kind}">
      <a class="free-cover" href="${escapeHtml(item.url)}" target="_blank" rel="noopener">${cover}<span class="plat-badge plat-${escapeHtml(plat)}">${escapeHtml(platLabel)}</span></a>
      <div class="free-body"><div class="free-title">${escapeHtml(item.title)}</div>
        <div class="free-sub">${escapeHtml(item.seller || "")} ${orig}</div>
        <div class="free-meta">${escapeHtml(meta)}</div>
        <a class="${btnCls}" href="${escapeHtml(item.url)}" target="_blank" rel="noopener">${btnLabel}</a></div></div>`;
}
function freeSection(title, items, kind) {
  if (!items || !items.length) return "";
  return `<h2 class="free-h2">${title} <span class="free-n">${items.length}</span></h2>
          <div class="free-grid">${items.map((it) => freeCard(it, kind)).join("")}</div>`;
}
function renderFree() {
  if (!FREE_PAYLOAD) return;
  el("free-subtitle").textContent = "Atualizado em " + (FREE_PAYLOAD.generated_at_human || "—");
  const cur = FREE_PAYLOAD.current || [], up = FREE_PAYLOAD.upcoming || [];
  const curTitles = new Set(cur.map((c) => c.title));
  const hist = (FREE_PAYLOAD.history || []).filter((h) => !curTitles.has(h.title));
  el("free-root").innerHTML =
    (freeSection("🎁 Grátis agora", cur, "current") + freeSection("⏳ Em breve", up, "upcoming") +
     freeSection("📜 Histórico — já passou", hist, "history")) ||
    '<div class="empty-tier">Nenhum jogo grátis no momento. Volte amanhã 🙂</div>';
}
async function loadFreeGames() {
  const loading = el("free-loading");
  try {
    const r = await fetch("/api/free-games", { cache: "no-store" });
    if (r.status === 503) { loading.textContent = "Os jogos grátis ainda não foram coletados (aguarde o cron diário)."; return; }
    if (!r.ok) throw new Error("HTTP " + r.status);
    FREE_PAYLOAD = await r.json(); loading.classList.add("hidden"); renderFree();
  } catch (e) { loading.textContent = "Falha ao carregar jogos grátis: " + e.message; }
}

// ─── Promoções Epic ─────────────────────────────────────────────────────────
function epicRow(g, rank) {
  const cover = g.cover ? `<img src="${escapeHtml(g.cover)}" alt="" loading="lazy">` : "";
  const badges =
    (g.cheaper_than_steam ? '<span class="cheaper-badge">MAIS BARATO QUE STEAM</span>' : "") +
    (g.on_steam && !g.cheaper_than_steam ? '<span class="onsteam-badge">também na Steam</span>' : "");
  let steamCell = '<span class="muted">—</span>';
  if (g.on_steam) {
    const cls = g.cheaper_than_steam ? "steam-loses" : "";
    const extra = g.cheaper_than_steam ? ` <span class="save-pct">−${g.steam_save_pct}%</span>` : "";
    steamCell = `<a href="${escapeHtml(g.steam_url || "#")}" target="_blank" rel="noopener" class="${cls}">${escapeHtml(g.steam_price || "")}${extra}</a>`;
  }
  return `<tr${g.cheaper_than_steam ? ' class="cheaper-row"' : ""}>
      <td class="rank">${rank}</td>
      <td class="name"><a href="${escapeHtml(g.url)}" target="_blank" rel="noopener">${cover}<span class="t-nm">${escapeHtml(g.title)}${badges}</span></a></td>
      <td class="disc">-${g.discount}%</td>
      <td class="orig">${escapeHtml(g.orig_price || "")}</td>
      <td class="sale">${escapeHtml(g.sale_price || "")}</td>
      <td class="low-ever">${steamCell}</td></tr>`;
}
function epicSort(arr, mode) {
  const cmp = {
    best: (a, b) => (Number(b.cheaper_than_steam) - Number(a.cheaper_than_steam)) ||
      (Number(b.on_steam) - Number(a.on_steam)) || (b.discount - a.discount) || (a.sale_brl - b.sale_brl),
    discount: (a, b) => b.discount - a.discount,
    price: (a, b) => a.sale_brl - b.sale_brl,
  }[mode] || (() => 0);
  arr.sort(cmp);
}
function renderEpic() {
  if (!EPIC_PAYLOAD) return;
  el("epic-subtitle").textContent = "Atualizado em " + (EPIC_PAYLOAD.generated_at_human || "—") +
    " · " + (EPIC_PAYLOAD.total || 0) + " promoções" +
    (EPIC_PAYLOAD.cheaper_than_steam ? " · " + EPIC_PAYLOAD.cheaper_than_steam + " mais baratas que na Steam" : "");
  const q = ((el("epic-search") || {}).value || "").trim().toLowerCase();
  const sort = ((el("epic-sort") || {}).value) || "best";
  let games = (EPIC_PAYLOAD.games || []).slice();
  if (EPIC_ONLY_CHEAPER) games = games.filter((g) => g.cheaper_than_steam);
  if (q) games = games.filter((g) => String(g.title || "").toLowerCase().includes(q));
  epicSort(games, sort);
  let rows = "", rank = 0;
  for (const g of games) rows += epicRow(g, ++rank);
  el("epic-root").innerHTML = rows ? `<div class="block">
      <div class="block-header"><span class="block-dot" style="background:#f5c518"></span><span class="block-name">Promoções Epic</span><span class="block-count">${rank} jogos</span></div>
      <div class="table-scroll"><table><thead><tr><th>#</th><th>Nome</th><th>Desc</th><th>Original</th><th>Promo</th><th>Steam</th></tr></thead><tbody>${rows}</tbody></table></div></div>`
    : '<div class="empty-tier">Nenhuma promoção com esse filtro.</div>';
}
async function loadEpicGames() {
  const loading = el("epic-loading");
  try {
    const r = await fetch("/api/epic-games", { cache: "no-store" });
    if (r.status === 503) { loading.textContent = "As promoções da Epic ainda não foram coletadas (aguarde o cron diário)."; return; }
    if (!r.ok) throw new Error("HTTP " + r.status);
    EPIC_PAYLOAD = await r.json(); loading.classList.add("hidden"); renderEpic();
  } catch (e) { loading.textContent = "Falha ao carregar promoções da Epic: " + e.message; }
}

// ─── Game Pass ──────────────────────────────────────────────────────────────
function gpCard(g) {
  const cover = g.cover ? `<img src="${escapeHtml(g.cover)}" alt="" loading="lazy">` : '<div class="free-noimg">🎮</div>';
  const money = cents => (cents / 100).toLocaleString('pt-BR', {style:'currency', currency:'BRL'});
  const price = g.steam && Number.isInteger(g.steam.price_cents) ?
    `<a class="gp-steam-price" href="https://store.steampowered.com/app/${escapeHtml(String(g.steam.appid))}/?cc=br" target="_blank" rel="noopener">Steam: ${money(g.steam.price_cents)}</a>` : '<span class="gp-price-unknown">Preço Steam não confirmado</span>';
  const advantage = g.above_subscription ? `<span class="gp-value-label">Mais que 1 mês de PC Game Pass<br>${money(g.difference_cents)} acima da mensalidade</span>` : '';
  return `<article class="gp-card${g.above_subscription ? ' gp-above-subscription' : ''}"><a class="gp-product-link" href="${escapeHtml(g.url)}" target="_blank" rel="noopener" title="${escapeHtml(g.title)}">
      <div class="gp-cover">${cover}</div><div class="gp-title">${escapeHtml(g.title)}</div></a><div class="gp-dev">${escapeHtml(g.dev || "")}</div><div class="gp-price">${price}${advantage}${priceLowHtml(g)}</div></article>`;
}
function gpSection(title, items, cls) {
  if (!items || !items.length) return "";
  return `<h2 class="free-h2 ${cls || ""}">${title} <span class="free-n">${items.length}</span></h2><div class="gp-grid">${items.map(gpCard).join("")}</div>`;
}
function renderGamepass() {
  if (!GP_PAYLOAD) return;
  const membershipDate = !GP_PAYLOAD.membership_stale && GP_PAYLOAD.membership_checked_at ?
    new Date(GP_PAYLOAD.membership_checked_at).toLocaleString('pt-BR', {timeZone:'America/Sao_Paulo'}) : null;
  el("gp-subtitle").textContent = (membershipDate ? "Disponibilidade conferida em " + membershipDate : "Último catálogo: " + (GP_PAYLOAD.generated_at_human || "—")) + " · " + (GP_PAYLOAD.total || 0) + " jogos";
  const sub = GP_PAYLOAD.subscription;
  if (sub && Number.isInteger(sub.monthly_cents)) {
    const monthly = (sub.monthly_cents/100).toLocaleString('pt-BR', {style:'currency',currency:'BRL'});
    const checked = sub.checked_at ? new Date(sub.checked_at).toLocaleDateString('pt-BR', {timeZone:'America/Sao_Paulo'}) : 'não informada';
    el('gp-subscription').innerHTML = `<b>PC Game Pass: ${monthly}/mês</b> · <a href="https://www.xbox.com/pt-BR/games/store/game-pass/CFQ7TTC0KGQ8" target="_blank" rel="noopener">Preço oficial</a> (verificado ${escapeHtml(checked)}).<br>
      Verde = preço atual na Steam maior que uma mensalidade. ${GP_PAYLOAD.priced_count || 0} jogos com preço confirmado; ${GP_PAYLOAD.highlighted_count || 0} destacados.<br>
      A assinatura dá acesso enquanto estiver ativa e o jogo permanecer no catálogo; não equivale à compra na Steam.
      ${sub.stale ? '<br>Mensalidade precisa de nova verificação; destaques suspensos.' : ''}
      ${GP_PAYLOAD.membership_stale ? '<br>Disponibilidade do catálogo precisa de nova verificação; destaques suspensos.' : ''}
      ${GP_PAYLOAD.metadata_stale && !GP_PAYLOAD.membership_stale ? '<br>Disponibilidade conferida na Microsoft; títulos e capas usam o último catálogo disponível.' : ''}`;
    if (GP_PAYLOAD.unresolved_membership_count > 0) el('gp-subscription').append(document.createTextNode(` ${GP_PAYLOAD.unresolved_membership_count} produtos aguardam detalhes da Microsoft.`));
  }
  const q = ((el("gp-search") || {}).value || "").trim().toLowerCase();
  let catalog = GP_PAYLOAD.catalog || [];
  if (q) catalog = catalog.filter((g) => String(g.title || "").toLowerCase().includes(q));
  let html = "";
  if (!q) { html += gpSection("🆕 Chegaram recentemente", GP_PAYLOAD.added, "gp-in"); html += gpSection("👋 Saíram recentemente", GP_PAYLOAD.removed, "gp-out"); }
  html += gpSection(q ? "Resultados da busca" : "📚 Catálogo atual", catalog);
  el("gp-root").innerHTML = html || '<div class="empty-tier">Nenhum jogo encontrado.</div>';
}
async function loadGamepass() {
  const loading = el("gp-loading");
  try {
    const r = await fetch("/api/gamepass", { cache: "no-store" });
    if (r.status === 503) { loading.textContent = "O catálogo do Game Pass ainda não foi coletado (aguarde o cron diário)."; return; }
    if (!r.ok) throw new Error("HTTP " + r.status);
    GP_PAYLOAD = await r.json(); loading.classList.add("hidden"); renderGamepass();
  } catch (e) { loading.textContent = "Falha ao carregar o Game Pass: " + e.message; }
}

// ─── Carga inicial ──────────────────────────────────────────────────────────
function skeleton() {
  return '<div class="skeleton-grid">' + Array.from({ length: 8 }, () =>
    '<div class="sk-card"><div class="sk-cover shimmer"></div><div class="sk-line shimmer"></div><div class="sk-line s shimmer"></div></div>').join("") + "</div>";
}
async function loadGames() {
  el("loading").innerHTML = skeleton();
  try {
    const r = await fetch("/api/games", { cache: "no-store" });
    if (r.status === 503) {
      el("loading").classList.add("hidden");
      const box = el("error-box"); box.classList.remove("hidden");
      box.textContent = "Os dados ainda não foram gerados. Rode o cron: python steam_sale_ranker.py 20 --json data/games.json";
      return;
    }
    if (!r.ok) throw new Error("HTTP " + r.status);
    PAYLOAD = await r.json();
    el("loading").classList.add("hidden");
    renderSubtitle(); renderStats(); populateGenres(); renderGames();
  } catch (e) {
    el("loading").classList.add("hidden");
    const box = el("error-box"); box.classList.remove("hidden");
    box.textContent = "Falha ao carregar /api/games: " + e.message;
  }
}

// ─── Comparação com perfil ──────────────────────────────────────────────────
async function compareProfile() {
  const raw = el("profile-input").value.trim();
  if (!raw) { setStatus("Digite seu perfil Steam primeiro.", "err"); return; }
  const keyInput = el("apikey-input");
  const apiKey = keyInput ? keyInput.value.trim() : "";
  const btn = el("profile-btn"); btn.disabled = true;
  setStatus(apiKey ? "Buscando wishlist e biblioteca…" : "Buscando wishlist…", "info");
  try {
    let url = "/api/steam-user?profile=" + encodeURIComponent(raw);
    if (apiKey) url += "&key=" + encodeURIComponent(apiKey);
    const r = await fetch(url, { cache: "no-store" });
    const data = await r.json();
    if (!data.ok) { setStatus((data.error || "perfil privado ou não encontrado") + " — confira se o perfil está público.", "err"); btn.disabled = false; return; }
    WISHLIST = new Set((data.wishlist || []).map(Number));
    OWNED = new Set((data.owned || []).map(Number));
    COMPARE_ACTIVE = true; TAGS.wish = false; syncTagUI();
    el("clear-btn").classList.remove("hidden");
    el("wishonly-btn").classList.toggle("hidden", WISHLIST.size === 0);
    renderGames();
    let msg = `Wishlist: ${WISHLIST.size} jogos (grifados em azul)`;
    msg += OWNED.size ? ` · Biblioteca: ${OWNED.size} jogos (ocultados da lista).` : ".";
    let cls = "ok";
    if (data.warnings && data.warnings.length) { msg += "  Aviso: " + data.warnings.join("; "); cls = "warn"; }
    if (WISHLIST.size === 0 && OWNED.size === 0) {
      msg = "Wishlist pública vazia (ou ainda privada). Deixe a lista de desejos como Pública em Perfil → Editar perfil → Privacidade."; cls = "warn";
    }
    setStatus(msg, cls);
  } catch (e) { setStatus("Erro ao consultar o perfil: " + e.message, "err"); }
  finally { btn.disabled = false; }
}
function clearProfile() {
  WISHLIST = new Set(); OWNED = new Set(); COMPARE_ACTIVE = false; TAGS.wish = false;
  el("clear-btn").classList.add("hidden"); el("wishonly-btn").classList.add("hidden");
  syncTagUI(); setStatus("", "info"); renderGames();
}

// ─── Wire-up ────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  // estado persistido
  loadFavs();
  applyTheme(lsGet(LS.theme, "dark") === "light" ? "light" : "dark");
  VIEW = lsGet(LS.view, "cards") === "table" ? "table" : "cards";
  document.querySelectorAll("#view-toggle button").forEach((b) => b.classList.toggle("active", b.dataset.view === VIEW));

  el("theme-btn").addEventListener("click", toggleTheme);
  document.querySelectorAll("#view-toggle button").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));

  el("profile-btn").addEventListener("click", compareProfile);
  el("clear-btn").addEventListener("click", clearProfile);
  el("wishonly-btn").addEventListener("click", () => toggleTag("wish"));
  el("profile-input").addEventListener("keydown", (e) => { if (e.key === "Enter") compareProfile(); });

  setupTabs();
  ["f-search", "f-genre", "f-discount", "f-review", "f-sort", "f-tags-include", "f-tags-exclude", "f-category", "f-budget", "f-gems"].forEach((id) => {
    const node = el(id);
    if (node) node.addEventListener(id === "f-search" ? "input" : "change", () => { saveTastes(); renderGames(); });
  });
  if (el("f-clear")) el("f-clear").addEventListener("click", clearFilters);
  document.querySelectorAll(".legend .legend-item").forEach((n) => n.addEventListener("click", () => toggleTag(n.dataset.tag)));

  // favoritos: delegação de evento (cobre cards e tabela)
  document.body.addEventListener("click", (e) => {
    const b = e.target.closest("[data-fav]");
    if (b) { e.preventDefault(); toggleFav(b.dataset.fav); }
  });

  // Epic
  ["epic-search", "epic-sort"].forEach((id) => { const n = el(id); if (n) n.addEventListener(id === "epic-search" ? "input" : "change", renderEpic); });
  const epicToggle = el("epic-cheaper-toggle");
  if (epicToggle) epicToggle.addEventListener("click", () => { EPIC_ONLY_CHEAPER = !EPIC_ONLY_CHEAPER; epicToggle.classList.toggle("active", EPIC_ONLY_CHEAPER); renderEpic(); });
  const gpSearch = el("gp-search"); if (gpSearch) gpSearch.addEventListener("input", renderGamepass);

  loadGames();
});
