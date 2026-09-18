export const normalize = (value = "") => String(value)
  .normalize("NFD")
  .replace(/[\u0300-\u036f]/g, "")
  .toLocaleLowerCase("pt-BR")
  .trim();

export function canView(entity, spoilerMax = 0) {
  const level = Number(entity?.spoiler_level ?? 0);
  return level <= Math.min(Number(spoilerMax), 3) && level < 4 && entity?.atlas_visibility !== "HIDDEN";
}

export function matchesQuery(entity, rawQuery = "") {
  const query = normalize(rawQuery);
  if (!query) return true;
  const searchable = [
    entity.id, entity.name, entity.domain, entity.type,
    ...(entity.aliases || []), ...(entity.territory_refs || []), ...(entity.biome_refs || []),
  ].map(normalize).join(" ");
  return query.split(/\s+/).every(term => searchable.includes(term));
}

export function filterEntities(dataset, filters = {}) {
  const { query = "", domain = "", territory = "", biome = "", layer = "", spoilerMax = 0 } = filters;
  return dataset.entities.filter(entity => {
    if (!canView(entity, spoilerMax) || !matchesQuery(entity, query)) return false;
    if (domain && entity.domain !== domain) return false;
    if (territory && !(entity.territory_refs || []).includes(territory)) return false;
    if (biome && !(entity.biome_refs || []).includes(biome)) return false;
    if (layer && !(entity.layer_refs || []).includes(layer)) return false;
    return true;
  });
}

export function searchEntities(dataset, query, spoilerMax = 0, limit = 30) {
  const normalized = normalize(query);
  const results = filterEntities(dataset, { query, spoilerMax });
  return results
    .map(entity => {
      const exact = [entity.id, entity.name, ...(entity.aliases || [])].some(value => normalize(value) === normalized);
      const starts = [entity.id, entity.name, ...(entity.aliases || [])].some(value => normalize(value).startsWith(normalized));
      return { entity, score: exact ? 3 : starts ? 2 : 1 };
    })
    .sort((a, b) => b.score - a.score || a.entity.name.localeCompare(b.entity.name, "pt-BR"))
    .slice(0, limit)
    .map(item => item.entity);
}

export function related(dataset, entityId, depth = 1, spoilerMax = 0) {
  const visible = new Map(dataset.entities.filter(entity => canView(entity, spoilerMax)).map(entity => [entity.id, entity]));
  const result = [];
  const queue = [{ id: entityId, depth: 0 }];
  const seen = new Set([entityId]);
  while (queue.length) {
    const current = queue.shift();
    if (current.depth >= depth) continue;
    for (const rel of dataset.relationships) {
      const isOut = rel.source_id === current.id;
      const isIn = rel.target_id === current.id;
      if (!isOut && !isIn) continue;
      const otherId = isOut ? rel.target_id : rel.source_id;
      if (!visible.has(otherId)) continue;
      result.push({ ...rel, direction: isOut ? "out" : "in", entity: visible.get(otherId) });
      if (!seen.has(otherId)) {
        seen.add(otherId);
        queue.push({ id: otherId, depth: current.depth + 1 });
      }
    }
  }
  const deduped = new Map();
  result.forEach(row => deduped.set(`${row.id}:${row.direction}`, row));
  return [...deduped.values()];
}

export function mapBounds(points) {
  const valid = points.filter(point => Number.isFinite(point?.longitude) && Number.isFinite(point?.latitude));
  if (!valid.length) return { minLon: -10, maxLon: 10, minLat: -10, maxLat: 10 };
  const lons = valid.map(point => point.longitude);
  const lats = valid.map(point => point.latitude);
  const padLon = Math.max(1, (Math.max(...lons) - Math.min(...lons)) * 0.12);
  const padLat = Math.max(1, (Math.max(...lats) - Math.min(...lats)) * 0.12);
  return { minLon: Math.min(...lons) - padLon, maxLon: Math.max(...lons) + padLon, minLat: Math.min(...lats) - padLat, maxLat: Math.max(...lats) + padLat };
}

export function project2d(coordinate, bounds, width = 1000, height = 660) {
  const x = ((coordinate.longitude - bounds.minLon) / (bounds.maxLon - bounds.minLon)) * width;
  const y = height - ((coordinate.latitude - bounds.minLat) / (bounds.maxLat - bounds.minLat)) * height;
  return { x, y };
}

export function projectGlobe(coordinate, rotation = 0, radius = 260, cx = 500, cy = 330) {
  const lat = (coordinate.latitude * Math.PI) / 180;
  const lon = ((coordinate.longitude + rotation) * Math.PI) / 180;
  const z = Math.cos(lat) * Math.cos(lon);
  return {
    x: cx + radius * Math.cos(lat) * Math.sin(lon),
    y: cy - radius * Math.sin(lat),
    visible: z >= -0.04,
    depth: z,
  };
}

export function encodeState(state) {
  const params = new URLSearchParams();
  if (state.entity) params.set("entity", state.entity);
  if (state.spoilerMax) params.set("spoiler", String(state.spoilerMax));
  if (state.layers?.length) params.set("layers", state.layers.join(","));
  if (state.mode && state.mode !== "map2d") params.set("mode", state.mode);
  return `?${params.toString()}`;
}

export function decodeState(search, defaults = {}) {
  const params = new URLSearchParams(search);
  return {
    ...defaults,
    entity: params.get("entity") || defaults.entity || null,
    spoilerMax: Math.min(Number(params.get("spoiler") ?? defaults.spoilerMax ?? 0), 3),
    layers: params.get("layers")?.split(",").filter(Boolean) || defaults.layers || [],
    mode: params.get("mode") || defaults.mode || "map2d",
  };
}
