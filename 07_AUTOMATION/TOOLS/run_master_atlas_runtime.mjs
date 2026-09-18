import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import path from "node:path";

const root = path.resolve(process.argv[2] || path.join(import.meta.dirname, ".."));
const runtime = path.join(root, "02_ATLAS", "runtime");
const corePath = path.join(runtime, "atlas-core.mjs");
const dataPath = path.join(runtime, "data", "atlas-data.json");
const core = await import(pathToFileURL(corePath).href);
const data = JSON.parse(readFileSync(dataPath, "utf8"));
const html = readFileSync(path.join(runtime, "index.html"), "utf8");
const css = readFileSync(path.join(runtime, "styles.css"), "utf8");
const app = readFileSync(path.join(runtime, "app.js"), "utf8");
const results = [];
const test = (id, condition, evidence = null) => results.push({
  suite: "ATLAS_RUNTIME",
  id,
  status: condition ? "PASS" : "FAIL",
  evidence,
});

const entityIds = new Set(data.entities.map(entity => entity.id));
const layerIds = new Set(data.layers.map(layer => layer.id));
const ids = data.entities.map(entity => entity.id);
test("ENTITY_IDS_UNIQUE", entityIds.size === ids.length, { entities: ids.length, unique: entityIds.size });
test("RELATION_ENDPOINTS", data.relationships.every(rel => entityIds.has(rel.source_id) && entityIds.has(rel.target_id)), { relationships: data.relationships.length });
test("AUTHORIAL_RELATION_COUNT", data.relationships.length === 9429, { relationships: data.relationships.length });
test("LAYER_REFERENCES", data.entities.every(entity => (entity.layer_refs || []).every(id => layerIds.has(id))), { layers: layerIds.size });
test("REQUIRED_LAYER_FLOOR", layerIds.size >= 31, { layers: layerIds.size });
test("SAFE_LAYER_PATCH", ["CULTURE", "JUSTICE", "SECURITY", "SCIENCE", "EDUCATION", "ARCHITECTURE", "ATLAS", "CULINARY", "ASTRONOMY", "MEDICINE", "WATER", "CLIMATE", "SPOILER"].every(id => layerIds.has(id)), "13 definições auxiliares");
test("INVALID_SELF_RELATIONS_REMOVED", !data.relationships.some(rel => rel.source_id === rel.target_id && ["localizado_em", "associado_a_local", "compatível_com_bioma"].includes(rel.type)), "ciclos técnicos");
test("SEARCH_ID", core.searchEntities(data, "WPN-001", 0).some(entity => entity.id === "WPN-001"), "WPN-001");
test("SEARCH_ALIAS", core.searchEntities(data, "Serlis Veyr", 2).some(entity => entity.id === "PER-003"), "PER-003");
test("SEARCH_CANON_DATE", core.searchEntities(data, "Fundação das Árvores Anciãs", 2).some(entity => entity.id === "TIM-004"), "TIM-004");
test("FILTER_COMBINED", core.filterEntities(data, { domain: "Indústria", territory: "TER-002", spoilerMax: 0 }).some(entity => entity.id === "INDN-001"), "TER-002 + Indústria");
test("FILTER_EMPTY", core.filterEntities(data, { domain: "DOMINIO_INEXISTENTE", spoilerMax: 0 }).length === 0, "resultado vazio estável");
test("SPOILER_LEVEL_4", data.entities.filter(entity => Number(entity.spoiler_level) === 4).every(entity => !core.canView(entity, 3)), "nível 4 oculto");
test("MAP_PROJECTION", (() => { const b = core.mapBounds(data.locations.map(item => item.coordinate)); const p = core.project2d(data.locations[0].coordinate, b, 1000, 660); return Number.isFinite(p.x) && Number.isFinite(p.y); })(), "projeção 2D");
test("MAP_CONTROLS", ["stellar-map", "zoom-in", "zoom-out", "view-mode"].every(id => html.includes(`id="${id}"`)), "pan/zoom/modo");
test("QUERY_CONTROLS", ["search-input", "domain-filter", "territory-filter", "biome-filter", "spoiler-filter", "layer-list", "entity-card", "relation-list"].every(id => html.includes(`id="${id}"`)), "busca/filtros/cards/relações");
test("RESPONSIVE", ["1180px", "850px", "560px"].every(token => css.includes(token)), "desktop/notebook/tablet/mobile");
test("ACCESSIBILITY", css.includes("focus-visible") && css.includes("prefers-reduced-motion") && html.includes("aria-label"), "foco/teclado/redução de movimento");
test("ERROR_FALLBACK", app.includes("ATLAS_LOAD_ERROR") && html.includes("fallback neutro"), "tratamento de erro");
test("STATE_PERSISTENCE", app.includes("localStorage.setItem") && app.includes("filters: saved.filters"), "estado navegável");
test("CANON_PROJECTION_DECLARED", data.projection_authority === "READ_ONLY_ATLAS_PROJECTION" && Boolean(data.projection_of?.sha256), data.projection_of);

const failed = results.filter(row => row.status === "FAIL");
const summary = { suites: 1, checks: results.length, passed: results.length - failed.length, failed: failed.length, status: failed.length ? "FAIL" : "PASS" };
console.log(JSON.stringify({ record_id: "MASTER-ATLAS-RUNTIME-TESTS-V2.0.0", version: "V2.0.0", summary, results, failed_checks: failed }, null, 2));
process.exit(failed.length ? 1 : 0);
