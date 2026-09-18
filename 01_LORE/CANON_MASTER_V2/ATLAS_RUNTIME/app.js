import {
  canView, decodeState, encodeState, filterEntities, mapBounds, project2d, projectGlobe, related, searchEntities,
} from "./atlas-core.mjs";

const $ = (selector, parent = document) => parent.querySelector(selector);
const $$ = (selector, parent = document) => [...parent.querySelectorAll(selector)];
const NS = "http://www.w3.org/2000/svg";
const MAP_W = 1000;
const MAP_H = 660;

let dataset;
let bounds;
let state;
let drag = null;
let selectedId = null;
let toastTimer;

const el = {
  search: $("#search-input"), domain: $("#domain-filter"), territory: $("#territory-filter"), biome: $("#biome-filter"), spoiler: $("#spoiler-filter"),
  layers: $("#layer-list"), map: $("#stellar-map"), mapFrame: $("#map-frame"), mapStatus: $("#map-status"), mapCoverage: $("#map-coverage"), mapEmpty: $("#map-empty"), tooltip: $("#map-tooltip"),
  card: $("#entity-card"), relations: $("#relation-list"), relationCount: $("#relation-count"), results: $("#dock-results"), timeline: $("#dock-timeline"), flows: $("#dock-flows"),
  resultCount: $("#result-count"), timelineCount: $("#timeline-count"), flowCount: $("#flow-count"), layerCount: $("#layer-count"), mode: $("#view-mode"), rotationControl: $("#rotation-control"), rotation: $("#rotation-slider"), toast: $("#toast"),
};

function svg(tag, attrs = {}) {
  const node = document.createElementNS(NS, tag);
  Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, String(value)));
  return node;
}

function addOption(select, value, label) {
  const option = document.createElement("option");
  option.value = value; option.textContent = label; select.append(option);
}

function unique(values) { return [...new Set(values.filter(Boolean))]; }

function toast(message) {
  el.toast.textContent = message;
  el.toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.toast.hidden = true; }, 2600);
}

function persist() {
  state.filters = { query: el.search.value, domain: el.domain.value, territory: el.territory.value, biome: el.biome.value };
  const compact = { mode: state.mode, layers: [...state.layers], spoilerMax: state.spoilerMax, transform: state.transform, rotation: state.rotation, filters: state.filters };
  localStorage.setItem("andromeda-atlas-preferences", JSON.stringify(compact));
  history.replaceState({}, "", encodeState({ entity: selectedId, mode: state.mode, layers: [...state.layers], spoilerMax: state.spoilerMax }));
}

function visibleEntity(entity) {
  return canView(entity, state.spoilerMax);
}

function currentFilters() {
  return { query: el.search.value, domain: el.domain.value, territory: el.territory.value, biome: el.biome.value, spoilerMax: state.spoilerMax };
}

function mapEligible(entity) {
  if (!visibleEntity(entity)) return false;
  const filters = currentFilters();
  if (filters.domain && entity.domain !== filters.domain) return false;
  if (filters.territory && !(entity.territory_refs || []).includes(filters.territory)) return false;
  if (filters.biome && !(entity.biome_refs || []).includes(filters.biome)) return false;
  if (filters.query && !searchEntities(dataset, filters.query, state.spoilerMax, 500).some(row => row.id === entity.id)) return false;
  return true;
}

function selected(entityId) { return entityId === selectedId; }

function pointFor(coord) {
  return project2d(coord, bounds, MAP_W, MAP_H);
}

function addClick(node, id, title) {
  node.setAttribute("tabindex", "0");
  node.setAttribute("role", "button");
  node.setAttribute("aria-label", title || id);
  node.addEventListener("click", () => selectEntity(id));
  node.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectEntity(id); } });
}

function clearMap() {
  el.map.replaceChildren();
}

function renderMap2d() {
  clearMap();
  const root = svg("g", { transform: `translate(${state.transform.x} ${state.transform.y}) scale(${state.transform.k})` });
  const visibleLayers = state.layers;
  if (visibleLayers.has("TERRITORIES")) {
    for (const envelope of dataset.territory_envelopes) {
      const points = envelope.polygon.map(([longitude, latitude]) => pointFor({ longitude, latitude }));
      const polygon = svg("polygon", { points: points.map(p => `${p.x},${p.y}`).join(" "), class: "territory-envelope" });
      polygon.setAttribute("aria-label", `${envelope.territory_id}: envoltória de apresentação`);
      root.append(polygon);
    }
  }
  if (visibleLayers.has("ROUTES") || visibleLayers.has("TRANSPORT")) {
    for (const route of dataset.routes) {
      if (route.geometry_status !== "RENDERABLE") continue;
      const origin = pointFor(route.origin_coordinate); const destination = pointFor(route.destination_coordinate);
      const line = svg("path", { d: `M ${origin.x} ${origin.y} L ${destination.x} ${destination.y}`, class: `route-line${selected(route.id) ? " selected" : ""}` });
      addClick(line, route.id, `${route.name}: ${route.origin_id} para ${route.destination_id}`);
      line.addEventListener("pointerenter", event => showTooltip(event, route.name));
      line.addEventListener("pointerleave", hideTooltip);
      root.append(line);
    }
  }
  const markerLayer = svg("g", { class: "markers" });
  const positions = [];
  for (const location of dataset.locations) {
    const entity = entityById(location.id);
    if (!entity || !mapEligible(entity)) continue;
    const shouldShow = visibleLayers.has("POI") || visibleLayers.has("CITIES") || (entity.layer_refs || []).some(layer => visibleLayers.has(layer));
    if (!shouldShow) continue;
    const point = pointFor(location.coordinate);
    positions.push({ location, entity, point });
  }
  for (const { location, entity, point } of positions) {
    const type = entity.type === "cidade" || entity.type === "CITY" || entity.type === "metrópole" ? "city" : "poi";
    const circle = svg("circle", { cx: point.x, cy: point.y, r: selected(entity.id) ? 8 : (type === "city" ? 6 : 4.6), class: `map-marker ${type}${selected(entity.id) ? " selected" : ""}` });
    addClick(circle, entity.id, `${entity.name} — ${entity.type}`);
    circle.addEventListener("pointerenter", event => showTooltip(event, `${entity.name} · ${entity.type}`));
    circle.addEventListener("pointerleave", hideTooltip);
    markerLayer.append(circle);
    if (selected(entity.id) || state.transform.k >= 1.45) {
      const label = svg("text", { x: point.x + 8, y: point.y - 8, class: "map-label" }); label.textContent = entity.name; markerLayer.append(label);
    }
  }
  root.append(markerLayer);
  el.map.append(root);
  el.mapEmpty.hidden = positions.length > 0;
  el.mapStatus.textContent = `${positions.length} pontos ativos · ${dataset.routes.filter(r => r.geometry_status === "RENDERABLE").length} rotas renderizáveis`;
}

function renderGlobe() {
  clearMap();
  const globe = svg("g");
  globe.append(svg("circle", { cx: 500, cy: 330, r: 264, class: "globe-shell" }));
  for (let lat = -60; lat <= 60; lat += 30) {
    const y = 330 - (lat / 90) * 250;
    const rx = Math.sqrt(Math.max(0, 1 - (lat / 90) ** 2)) * 260;
    globe.append(svg("ellipse", { cx: 500, cy: y, rx, ry: Math.max(8, rx * .09), class: "globe-lat" }));
  }
  for (let lon = -90; lon <= 90; lon += 45) globe.append(svg("ellipse", { cx: 500, cy: 330, rx: Math.abs(Math.sin((lon * Math.PI) / 180)) * 260, ry: 260, class: "globe-lon" }));
  const positioned = new Map();
  for (const location of dataset.locations) {
    const entity = entityById(location.id);
    if (!entity || !mapEligible(entity)) continue;
    const shouldShow = state.layers.has("POI") || state.layers.has("CITIES") || (entity.layer_refs || []).some(layer => state.layers.has(layer));
    if (!shouldShow) continue;
    const p = projectGlobe(location.coordinate, state.rotation);
    if (p.visible) positioned.set(location.id, { entity, p });
  }
  if (state.layers.has("ROUTES") || state.layers.has("TRANSPORT")) {
    for (const route of dataset.routes) {
      if (route.geometry_status !== "RENDERABLE") continue;
      const a = projectGlobe(route.origin_coordinate, state.rotation); const b = projectGlobe(route.destination_coordinate, state.rotation);
      if (!a.visible || !b.visible) continue;
      const path = svg("path", { d: `M ${a.x} ${a.y} L ${b.x} ${b.y}`, class: `route-line${selected(route.id) ? " selected" : ""}` });
      addClick(path, route.id, route.name); globe.append(path);
    }
  }
  for (const [id, { entity, p }] of positioned) {
    const marker = svg("circle", { cx: p.x, cy: p.y, r: selected(id) ? 8 : 4.8 + Math.max(0, p.depth) * 2, class: `map-marker poi${selected(id) ? " selected" : ""}`, opacity: Math.max(.45, .55 + p.depth * .45) });
    addClick(marker, id, `${entity.name} — ${entity.type}`); globe.append(marker);
    if (selected(id)) { const label = svg("text", { x: p.x + 9, y: p.y - 8, class: "map-label" }); label.textContent = entity.name; globe.append(label); }
  }
  el.map.append(globe);
  el.mapEmpty.hidden = positioned.size > 0;
  el.mapStatus.textContent = `${positioned.size} marcadores no modo orbital · rotação ${state.rotation}°`;
}

function renderMap() {
  if (!dataset) return;
  if (state.mode === "globe") renderGlobe(); else renderMap2d();
  const mode = state.mode === "globe" ? "Orbital" : "2D";
  el.mapCoverage.textContent = `${mode} · cobertura aplicável 100%`;
}

function showTooltip(event, text) {
  const rect = el.mapFrame.getBoundingClientRect();
  el.tooltip.textContent = text; el.tooltip.hidden = false;
  el.tooltip.style.left = `${Math.min(rect.width - 220, Math.max(8, event.clientX - rect.left + 10))}px`;
  el.tooltip.style.top = `${Math.min(rect.height - 48, Math.max(8, event.clientY - rect.top + 10))}px`;
}
function hideTooltip() { el.tooltip.hidden = true; }
function entityById(id) { return dataset.entities.find(entity => entity.id === id); }

function factNode(list, term, value) {
  if (value === undefined || value === null || value === "" || (Array.isArray(value) && !value.length)) return;
  const dt = document.createElement("dt"); dt.textContent = term;
  const dd = document.createElement("dd"); dd.textContent = Array.isArray(value) ? value.join(", ") : (typeof value === "object" ? JSON.stringify(value) : value);
  list.append(dt, dd);
}

function renderCard() {
  const entity = entityById(selectedId);
  if (!entity || !visibleEntity(entity)) {
    el.card.innerHTML = '<div class="empty-card"><span class="empty-symbol">✦</span><h2>Selecione uma entidade</h2><p>Abra um marcador, resultado de busca, rota ou item da lista para consultar sua ficha canônica.</p></div>';
    return;
  }
  const fragment = $("#card-template").content.cloneNode(true);
  $(".entity-domain", fragment).textContent = entity.domain;
  $(".entity-status", fragment).textContent = entity.canonical_status;
  $(".entity-name", fragment).textContent = entity.name;
  $(".entity-id", fragment).textContent = entity.id;
  $(".entity-summary", fragment).textContent = entity.summary || "Sem resumo adicional no índice.";
  const facts = $(".entity-facts", fragment);
  factNode(facts, "Tipo", entity.type);
  factNode(facts, "Aliases", entity.aliases);
  factNode(facts, "Território", entity.territory_refs);
  factNode(facts, "Biomas", entity.biome_refs);
  factNode(facts, "Rotas", entity.route_refs);
  factNode(facts, "Representação", entity.representation_type);
  factNode(facts, "Visibilidade", `${entity.atlas_visibility} · spoiler ${entity.spoiler_level}`);
  const cardData = entity.card_data || {};
  factNode(facts, "Categoria", cardData.category || cardData.sector);
  factNode(facts, "Instituição", cardData.institution_id);
  const codex = $(".codex-link", fragment);
  codex.addEventListener("click", () => { navigator.clipboard?.writeText(entity.description_ref); toast(`Referência Códex copiada: ${entity.id}`); });
  const copy = $(".copy-link", fragment);
  copy.addEventListener("click", () => { navigator.clipboard?.writeText(`${location.origin}${location.pathname}${encodeState({ entity: entity.id, mode: state.mode, layers: [...state.layers], spoilerMax: state.spoilerMax })}`); toast("Link do Atlas copiado."); });
  el.card.replaceChildren(fragment);
}

function renderRelations() {
  const entity = entityById(selectedId);
  el.relations.replaceChildren();
  if (!entity || !visibleEntity(entity)) { el.relations.innerHTML = '<p class="muted">Selecione uma entidade para explorar vínculos.</p>'; el.relationCount.textContent = "0"; return; }
  const rows = related(dataset, entity.id, 1, state.spoilerMax).slice(0, 60);
  el.relationCount.textContent = String(rows.length);
  if (!rows.length) { el.relations.innerHTML = '<p class="muted">Nenhuma relação visível neste nível de acesso.</p>'; return; }
  for (const row of rows) {
    const button = document.createElement("button"); button.className = "relation-row"; button.type = "button";
    const text = document.createElement("span"); const name = document.createElement("strong"); const small = document.createElement("small");
    name.textContent = row.entity.name; small.textContent = `${row.direction === "out" ? row.type : `← ${row.type}`} · ${row.entity.id}`;
    text.append(name, small); const arrow = document.createElement("b"); arrow.textContent = "→"; button.append(text, arrow);
    button.addEventListener("click", () => selectEntity(row.entity.id)); el.relations.append(button);
  }
}

function resultButton(entity) {
  const button = document.createElement("button"); button.className = "result-row"; button.type = "button";
  const name = document.createElement("strong"); name.textContent = entity.name;
  const details = document.createElement("small"); details.textContent = `${entity.id} · ${entity.domain} · ${entity.type}`;
  button.append(name, details); button.addEventListener("click", () => selectEntity(entity.id)); return button;
}

function renderResults() {
  const rows = filterEntities(dataset, currentFilters()).slice(0, 80);
  el.results.replaceChildren();
  const grid = document.createElement("div"); grid.className = "result-grid";
  rows.forEach(entity => grid.append(resultButton(entity)));
  if (!rows.length) grid.innerHTML = '<p class="muted">Nenhuma entidade visível corresponde à consulta.</p>';
  el.results.append(grid); el.resultCount.textContent = String(rows.length);
}

function renderTimeline() {
  el.timeline.replaceChildren();
  const list = document.createElement("div"); list.className = "timeline-list";
  const rows = dataset.timeline.filter(item => Number(item.spoiler_level || 0) <= state.spoilerMax && Number(item.spoiler_level || 0) < 4).slice(0, 100);
  for (const item of rows) {
    const button = document.createElement("button"); button.className = "timeline-row"; button.type = "button";
    const name = document.createElement("strong"); name.textContent = item.name;
    const info = document.createElement("small"); info.textContent = `${item.kind} · ${item.date || item.date_status || "sem data explícita"}`;
    button.append(name, info); button.addEventListener("click", () => selectEntity(item.entity_id || item.id)); list.append(button);
  }
  if (!rows.length) list.innerHTML = '<p class="muted">Nenhum evento visível neste nível de acesso.</p>';
  el.timeline.append(list); el.timelineCount.textContent = String(rows.length);
}

function renderFlows() {
  el.flows.replaceChildren();
  const flows = dataset.entities.filter(entity => entity.type === "ECONOMIC_FLOW" && visibleEntity(entity));
  const list = document.createElement("div"); list.className = "flow-list";
  for (const flow of flows) {
    const button = document.createElement("button"); button.className = "flow-row"; button.type = "button";
    const name = document.createElement("strong"); name.textContent = flow.name;
    const info = document.createElement("small"); info.textContent = flow.summary;
    button.append(name, info); button.addEventListener("click", () => selectEntity(flow.id)); list.append(button);
  }
  if (!flows.length) list.innerHTML = '<p class="muted">Nenhum fluxo econômico visível.</p>';
  el.flows.append(list); el.flowCount.textContent = String(flows.length);
}

function renderAll() { renderMap(); renderCard(); renderRelations(); renderResults(); renderTimeline(); renderFlows(); persist(); }

function selectEntity(id) {
  const entity = entityById(id);
  if (!entity || !visibleEntity(entity)) { toast("Essa entidade não está disponível neste nível de acesso."); return; }
  selectedId = id;
  renderAll();
}

function populateFilters() {
  unique(dataset.entities.map(entity => entity.domain)).sort((a, b) => a.localeCompare(b, "pt-BR")).forEach(value => addOption(el.domain, value, value));
  unique(dataset.entities.flatMap(entity => entity.territory_refs || [])).sort().forEach(value => addOption(el.territory, value, value));
  unique(dataset.entities.flatMap(entity => entity.biome_refs || [])).sort().forEach(value => addOption(el.biome, value, value));
  for (const layer of dataset.layers) {
    const label = document.createElement("label"); label.className = "layer-row";
    const checkbox = document.createElement("input"); checkbox.type = "checkbox"; checkbox.value = layer.id; checkbox.checked = state.layers.has(layer.id);
    checkbox.addEventListener("change", () => { checkbox.checked ? state.layers.add(layer.id) : state.layers.delete(layer.id); renderAll(); });
    const title = document.createElement("span"); title.textContent = layer.name;
    const count = document.createElement("small"); count.textContent = layer.entity_count;
    label.append(checkbox, title, count); el.layers.append(label);
  }
  el.layerCount.textContent = `${dataset.layers.length}`;
}

function syncControls() {
  el.search.value = state.filters?.query || "";
  el.domain.value = state.filters?.domain || ""; el.territory.value = state.filters?.territory || ""; el.biome.value = state.filters?.biome || "";
  el.spoiler.value = String(state.spoilerMax); el.rotation.value = String(state.rotation);
  el.mode.textContent = state.mode === "globe" ? "◑ Modo 2D" : "◐ Modo orbital";
  el.mode.setAttribute("aria-pressed", String(state.mode === "globe")); el.rotationControl.hidden = state.mode !== "globe";
}

function setTab(tab) {
  $$(".dock-tab").forEach(button => { const active = button.dataset.tab === tab; button.classList.toggle("active", active); button.setAttribute("aria-selected", String(active)); });
  [["results", el.results], ["timeline", el.timeline], ["flows", el.flows]].forEach(([id, node]) => { node.hidden = id !== tab; });
}

function bindInteractions() {
  [el.search, el.domain, el.territory, el.biome].forEach(node => node.addEventListener("input", renderAll));
  el.spoiler.addEventListener("change", () => { state.spoilerMax = Number(el.spoiler.value); if (selectedId && !visibleEntity(entityById(selectedId))) selectedId = null; renderAll(); });
  $("#clear-filters").addEventListener("click", () => { el.search.value = ""; el.domain.value = ""; el.territory.value = ""; el.biome.value = ""; state.spoilerMax = 0; renderAll(); });
  $("#zoom-in").addEventListener("click", () => { state.transform.k = Math.min(4, +(state.transform.k * 1.22).toFixed(2)); renderAll(); });
  $("#zoom-out").addEventListener("click", () => { state.transform.k = Math.max(.65, +(state.transform.k / 1.22).toFixed(2)); renderAll(); });
  $("#reset-view").addEventListener("click", () => { state.transform = { x: 0, y: 0, k: 1 }; state.rotation = 0; renderAll(); });
  el.mode.addEventListener("click", () => { state.mode = state.mode === "globe" ? "map2d" : "globe"; syncControls(); renderAll(); });
  el.rotation.addEventListener("input", () => { state.rotation = Number(el.rotation.value); renderMap(); persist(); });
  $$(".dock-tab").forEach(button => button.addEventListener("click", () => setTab(button.dataset.tab)));
  window.addEventListener("keydown", event => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); el.search.focus(); }
    if (event.key === "Escape") { el.search.value = ""; renderAll(); }
  });
  el.mapFrame.addEventListener("wheel", event => { if (state.mode !== "map2d") return; event.preventDefault(); const factor = event.deltaY < 0 ? 1.13 : .88; state.transform.k = Math.max(.65, Math.min(4, +(state.transform.k * factor).toFixed(2))); renderAll(); }, { passive: false });
  el.mapFrame.addEventListener("pointerdown", event => { if (state.mode !== "map2d" || event.target.closest("[role=button]")) return; drag = { x: event.clientX, y: event.clientY, startX: state.transform.x, startY: state.transform.y }; el.mapFrame.setPointerCapture?.(event.pointerId); });
  el.mapFrame.addEventListener("pointermove", event => { if (!drag) return; state.transform.x = drag.startX + (event.clientX - drag.x); state.transform.y = drag.startY + (event.clientY - drag.y); renderMap(); });
  el.mapFrame.addEventListener("pointerup", () => { if (!drag) return; drag = null; persist(); });
}

async function start() {
  try {
    const response = await fetch("data/atlas-data.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`dataset HTTP ${response.status}`);
    dataset = await response.json();
    const saved = JSON.parse(localStorage.getItem("andromeda-atlas-preferences") || "{}");
    const urlState = decodeState(location.search, saved);
    const defaults = dataset.layers.filter(layer => layer.visible_default).map(layer => layer.id);
    state = {
      mode: urlState.mode || "map2d", layers: new Set(urlState.layers?.length ? urlState.layers : (saved.layers || defaults)), spoilerMax: Number(urlState.spoilerMax ?? saved.spoilerMax ?? 0),
      transform: saved.transform || { x: 0, y: 0, k: 1 }, rotation: Number(saved.rotation || 0), filters: saved.filters || { query: "", domain: "", territory: "", biome: "" },
    };
    selectedId = urlState.entity || null;
    bounds = mapBounds(dataset.locations.map(location => location.coordinate));
    populateFilters(); syncControls(); bindInteractions(); renderAll();
    el.mapStatus.textContent = `Atlas pronto · ${dataset.metadata.canonical_entity_count} entidades canônicas representadas`;
  } catch (error) {
    el.mapStatus.textContent = "Não foi possível carregar o dataset do Atlas.";
    el.mapEmpty.hidden = false; el.mapEmpty.textContent = "Falha de carregamento. Consulte o log local do Atlas.";
    console.error("ATLAS_LOAD_ERROR", error);
  }
}

start();
