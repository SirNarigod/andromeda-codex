extends Node3D
class_name AndromedaStreamingManager

## CELL-level presentation (below) and ZONE-level Living authority (G16B-09C,
## further below) are two different granularities and two different
## authorities. Read this file's header comments at each section boundary
## before assuming either one governs the other.

const AUTHORITY := "GODOT_CELL_STREAMING_PRESENTATION_ONLY"
const STATE_ACTIVE := "ACTIVE"
const STATE_PRELOAD := "PRELOAD"
const STATE_SYSTEMIC := "SYSTEMIC"

## G16B-09C: the backend's own authoritative label for a real world zone_ref
## (andromeda_authority_adapter.py::_streaming_projection()). Godot never
## computes this value -- it only projects whatever REQUEST_SNAPSHOT/
## REQUEST_RELOAD_RESYNC's real `world_streaming` block reports. Distinct
## from AUTHORITY above: that one is honest about the CELL grid below being
## presentation-only local prototype geometry, unrelated to any real
## zone_ref; this one is honest that the ZONE data itself is NOT decided
## here, only displayed/queried.
const ZONE_AUTHORITY := "GODOT_ZONE_STREAMING_PROJECTS_BACKEND_AUTHORITY"

@export var cell_scene: PackedScene
@export var area_ref: String = "AREA-B04-LOCAL-PROTOTYPE"
@export var living_macro_ref: String = "LIVING-MACRO-4096-B04-REFERENCE"
@export var cell_size_m: float = 256.0
@export_range(1, 8, 1) var logical_radius_cells: int = 2
@export_range(0, 2, 1) var preload_ring: int = 1

var _active_cell := Vector2i.ZERO
var _loaded_cells: Dictionary = {}
var _systemic_references: Dictionary = {}

# =====================================================================
# ZONE-level Living authority state (G16B-09C). Entirely separate from
# the CELL-level vars above -- never read or written by any CELL-level
# function, and vice versa.
# =====================================================================
signal zone_streaming_projected(result: Dictionary)

var _zone_bound: bool = false
var _zone_current_ref: String = ""
var _zone_entries: Dictionary = {}  ## zone_ref -> {zone_ref, block_ref, stream_phase, zone_living_state}
var _zone_living_macro_context: Dictionary = {}
var _zone_projection_valid: bool = false


func _ready() -> void:
	_rebuild_stream_plan()


func set_active_cell(cell_coordinate: Vector2i) -> Dictionary:
	if abs(cell_coordinate.x) > logical_radius_cells or abs(cell_coordinate.y) > logical_radius_cells:
		return {
			"status": "REJECTED",
			"reason": "ACTIVE_CELL_OUTSIDE_LOGICAL_AREA",
			"authority": AUTHORITY,
		}
	_active_cell = cell_coordinate
	_rebuild_stream_plan()
	return {"status": "PASS", "active_cell": _active_cell, "authority": AUTHORITY}


func active_cell() -> Vector2i:
	return _active_cell


func cell_ref_for(coordinate: Vector2i) -> String:
	return "CELL-B04-%+03d-%+03d" % [coordinate.x, coordinate.y]


func systemic_reference_for(cell_ref: String) -> Dictionary:
	return (_systemic_references.get(cell_ref, {}) as Dictionary).duplicate(true)


func state_snapshot() -> Dictionary:
	var active_refs: Array[String] = []
	var preload_refs: Array[String] = []
	for ref_value: Variant in _loaded_cells.keys():
		var ref: String = str(ref_value)
		var cell := _loaded_cells[ref] as AndromedaStreamingCell
		if cell.stream_state() == STATE_ACTIVE:
			active_refs.append(ref)
		else:
			preload_refs.append(ref)
	active_refs.sort()
	preload_refs.sort()
	var systemic_refs: Array[String] = []
	for ref_value: Variant in _systemic_references.keys():
		systemic_refs.append(str(ref_value))
	systemic_refs.sort()
	var axis_count: int = logical_radius_cells * 2 + 1
	return {
		"status": "PASS",
		"area_ref": area_ref,
		"cell_size_m": cell_size_m,
		"preload_ring": preload_ring,
		"total_logical_cells": axis_count * axis_count,
		"active_cells": active_refs,
		"preload_cells": preload_refs,
		"loaded_scene_cell_count": active_refs.size() + preload_refs.size(),
		"systemic_unloaded_cell_count": systemic_refs.size(),
		"systemic_refs": systemic_refs,
		"living_macro_ref": living_macro_ref,
		"distant_visuals_loaded": false,
		"entire_region_loaded": false,
		"living_parallel_implementation": false,
		"systemic_state_source": "EXTERNAL_LIVING_REFERENCE_ONLY",
		"authority": AUTHORITY,
	}


func loaded_cell_snapshot(cell_ref: String) -> Dictionary:
	var cell := _loaded_cells.get(cell_ref) as AndromedaStreamingCell
	if cell == null:
		return {}
	return cell.snapshot()


func _rebuild_stream_plan() -> void:
	var wanted_loaded: Dictionary = {}
	var next_systemic: Dictionary = {}
	for x: int in range(-logical_radius_cells, logical_radius_cells + 1):
		for y: int in range(-logical_radius_cells, logical_radius_cells + 1):
			var coordinate := Vector2i(x, y)
			var ref: String = cell_ref_for(coordinate)
			var distance: int = maxi(abs(x - _active_cell.x), abs(y - _active_cell.y))
			if distance <= preload_ring:
				wanted_loaded[ref] = {
					"coordinate": coordinate,
					"state": STATE_ACTIVE if coordinate == _active_cell else STATE_PRELOAD,
				}
			else:
				next_systemic[ref] = {
					"cell_ref": ref,
					"coordinate": coordinate,
					"state": STATE_SYSTEMIC,
					"living_macro_ref": living_macro_ref,
					"godot_scene_loaded": false,
					"systemic_state_preserved_by_reference": true,
				}
	for ref_value: Variant in _loaded_cells.keys().duplicate():
		var ref: String = str(ref_value)
		if wanted_loaded.has(ref):
			continue
		var obsolete := _loaded_cells[ref] as AndromedaStreamingCell
		_loaded_cells.erase(ref)
		obsolete.queue_free()
	for ref_value: Variant in wanted_loaded.keys():
		var ref: String = str(ref_value)
		var plan: Dictionary = wanted_loaded[ref]
		var cell := _loaded_cells.get(ref) as AndromedaStreamingCell
		if cell == null:
			assert(cell_scene != null)
			cell = cell_scene.instantiate() as AndromedaStreamingCell
			cell.name = ref
			add_child(cell)
			_loaded_cells[ref] = cell
		var coordinate: Vector2i = plan["coordinate"]
		cell.position = Vector3(coordinate.x * 6.0, -24.0, coordinate.y * 6.0)
		cell.configure(ref, living_macro_ref, str(plan["state"]))
	_systemic_references = next_systemic


func bind_zone_authority() -> Dictionary:
	if not _zone_bound:
		var bridge: AndromedaRuntimeBridge = get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
		if bridge != null and not bridge.snapshot_applied.is_connected(_on_bridge_snapshot_applied_for_zone):
			bridge.snapshot_applied.connect(_on_bridge_snapshot_applied_for_zone)
		_zone_bound = true
	return {"status": "PASS", "authority": ZONE_AUTHORITY}


func _on_bridge_snapshot_applied_for_zone(snapshot: Dictionary) -> void:
	var streaming_value: Variant = snapshot.get("world_streaming")
	if not streaming_value is Dictionary:
		return
	project_world_streaming(streaming_value as Dictionary)


func project_world_streaming(world_streaming: Dictionary) -> Dictionary:
	if world_streaming.get("server_authoritative") != true:
		return _zone_rejected("NON_AUTHORITATIVE_WORLD_STREAMING")
	var current_zone_ref_value: String = str(world_streaming.get("current_zone_ref", "")).strip_edges()
	if current_zone_ref_value.is_empty():
		return _zone_rejected("MISSING_CURRENT_ZONE_REF")
	var zones_value: Variant = world_streaming.get("zones")
	if not zones_value is Array:
		return _zone_rejected("MISSING_ZONES_ARRAY")
	var next_entries: Dictionary = {}
	for entry_value: Variant in (zones_value as Array):
		if not entry_value is Dictionary:
			continue
		var entry: Dictionary = entry_value as Dictionary
		var zone_ref_value: String = str(entry.get("zone_ref", "")).strip_edges()
		var phase: String = str(entry.get("stream_phase", "")).strip_edges()
		if zone_ref_value.is_empty() or phase not in [STATE_ACTIVE, STATE_SYSTEMIC]:
			continue
		next_entries[zone_ref_value] = {
			"zone_ref": zone_ref_value,
			"block_ref": str(entry.get("block_ref", "")),
			"stream_phase": phase,
			"zone_living_state": (entry.get("zone_living_state", {}) as Dictionary).duplicate(true),
		}
	if not next_entries.has(current_zone_ref_value):
		return _zone_rejected("CURRENT_ZONE_REF_NOT_IN_ZONES_ARRAY")
	_zone_current_ref = current_zone_ref_value
	_zone_entries = next_entries
	_zone_living_macro_context = (world_streaming.get("living_macro_context", {}) as Dictionary).duplicate(true)
	_zone_projection_valid = true
	var result := {
		"status": "PASS",
		"current_zone_ref": _zone_current_ref,
		"zone_count": _zone_entries.size(),
		"authority": ZONE_AUTHORITY,
	}
	zone_streaming_projected.emit(result.duplicate(true))
	return result


func current_authoritative_zone_ref() -> String:
	return _zone_current_ref


func zone_phase(zone_ref_value: String) -> String:
	var entry := _zone_entries.get(zone_ref_value, {}) as Dictionary
	return str(entry.get("stream_phase", ""))


func zone_entry(zone_ref_value: String) -> Dictionary:
	return (_zone_entries.get(zone_ref_value, {}) as Dictionary).duplicate(true)


func zone_refs() -> Array[String]:
	var refs: Array[String] = []
	for ref_value: Variant in _zone_entries.keys():
		refs.append(str(ref_value))
	return refs


func living_macro_context() -> Dictionary:
	return _zone_living_macro_context.duplicate(true)


func zone_projection_valid() -> bool:
	return _zone_projection_valid


func _zone_rejected(reason: String) -> Dictionary:
	return {"status": "REJECTED", "reason": reason, "authority": ZONE_AUTHORITY}
