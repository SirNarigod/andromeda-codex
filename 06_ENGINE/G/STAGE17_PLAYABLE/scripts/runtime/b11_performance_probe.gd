extends Node
class_name AndromedaB11PerformanceProbe

## B11 measurement-only probe. It does not impose an invented FPS/frame-time target.

const AUTHORITY := "GODOT_B11_OBSERVATION_ONLY"
const REPORT_SCHEMA := "ANDROMEDA_STAGE16B_B11_PERFORMANCE_V0_8_0"

var _capturing: bool = false
var _label: String = ""
var _metadata: Dictionary = {}
var _frame_times_ms: Array[float] = []
var _events: Array[Dictionary] = []
var _start_ticks_usec: int = 0
var _start_process_frames: int = 0
var _start_nodes: int = 0
var _start_objects: int = 0
var _start_static_memory_bytes: int = 0
var _peak_static_memory_bytes: int = 0
var _last_report: Dictionary = {}


func _process(delta: float) -> void:
	if not _capturing:
		return
	_frame_times_ms.append(delta * 1000.0)
	_peak_static_memory_bytes = maxi(_peak_static_memory_bytes, _static_memory_bytes())


func begin_capture(label_value: String, metadata_value: Dictionary = {}) -> Dictionary:
	if _capturing:
		return _rejected("CAPTURE_ALREADY_ACTIVE")
	_label = label_value.strip_edges()
	if _label.is_empty():
		return _rejected("EMPTY_CAPTURE_LABEL")
	_metadata = metadata_value.duplicate(true)
	_frame_times_ms.clear()
	_events.clear()
	_start_ticks_usec = Time.get_ticks_usec()
	_start_process_frames = Engine.get_process_frames()
	_start_nodes = _node_count()
	_start_objects = int(Performance.get_monitor(Performance.OBJECT_COUNT))
	_start_static_memory_bytes = _static_memory_bytes()
	_peak_static_memory_bytes = _start_static_memory_bytes
	_capturing = true
	return {
		"status": "PASS",
		"label": _label,
		"measurement_only": true,
		"numeric_threshold_invented": false,
		"authority": AUTHORITY,
	}


func mark_event(event_kind: String, detail: Dictionary = {}) -> Dictionary:
	if not _capturing:
		return _rejected("CAPTURE_NOT_ACTIVE")
	var normalized_kind: String = event_kind.strip_edges().to_upper()
	if normalized_kind.is_empty():
		return _rejected("EMPTY_EVENT_KIND")
	_events.append({
		"event_kind": normalized_kind,
		"elapsed_ms": float(Time.get_ticks_usec() - _start_ticks_usec) / 1000.0,
		"process_frame": Engine.get_process_frames(),
		"node_count": _node_count(),
		"object_count": int(Performance.get_monitor(Performance.OBJECT_COUNT)),
		"static_memory_bytes": _static_memory_bytes(),
		"detail": detail.duplicate(true),
	})
	return {
		"status": "PASS",
		"event_kind": normalized_kind,
		"event_index": _events.size() - 1,
		"authority": AUTHORITY,
	}


func end_capture(final_metadata: Dictionary = {}) -> Dictionary:
	if not _capturing:
		return _rejected("CAPTURE_NOT_ACTIVE")
	_capturing = false
	var end_ticks_usec: int = Time.get_ticks_usec()
	var duration_s: float = maxf(0.000001, float(end_ticks_usec - _start_ticks_usec) / 1000000.0)
	var end_process_frames: int = Engine.get_process_frames()
	var sampled_frames: int = _frame_times_ms.size()
	var process_frames: int = maxi(0, end_process_frames - _start_process_frames)
	var sorted_samples: Array[float] = _frame_times_ms.duplicate()
	sorted_samples.sort()
	var average_ms: float = _average(_frame_times_ms)
	var p95_ms: float = _percentile(sorted_samples, 0.95)
	var max_ms: float = sorted_samples.back() if not sorted_samples.is_empty() else 0.0
	var end_nodes: int = _node_count()
	var end_objects: int = int(Performance.get_monitor(Performance.OBJECT_COUNT))
	var end_static_memory_bytes: int = _static_memory_bytes()
	var combined_metadata: Dictionary = _metadata.duplicate(true)
	combined_metadata.merge(final_metadata, true)
	_last_report = {
		"schema": REPORT_SCHEMA,
		"status": "MEASURED",
		"label": _label,
		"renderer_method": str(ProjectSettings.get_setting("rendering/renderer/rendering_method", "gl_compatibility")),
		"renderer_name": RenderingServer.get_rendering_device().get_device_name() if RenderingServer.get_rendering_device() != null else "HEADLESS_OR_GL_COMPATIBILITY_UNAVAILABLE",
		"duration_s": duration_s,
		"sampled_frame_count": sampled_frames,
		"process_frame_count": process_frames,
		"observed_fps_from_process_frames": float(process_frames) / duration_s,
		"engine_fps_monitor": float(Performance.get_monitor(Performance.TIME_FPS)),
		"frame_time_ms": {
			"average": average_ms,
			"p95": p95_ms,
			"maximum": max_ms,
			"sample_count": sampled_frames,
		},
		"engine_time_monitors_s": {
			"process": float(Performance.get_monitor(Performance.TIME_PROCESS)),
			"physics_process": float(Performance.get_monitor(Performance.TIME_PHYSICS_PROCESS)),
		},
		"memory": {
			"static_start_bytes": _start_static_memory_bytes,
			"static_end_bytes": end_static_memory_bytes,
			"static_peak_bytes": _peak_static_memory_bytes,
			"static_delta_bytes": end_static_memory_bytes - _start_static_memory_bytes,
		},
		"object_counts": {
			"nodes_start": _start_nodes,
			"nodes_end": end_nodes,
			"nodes_delta": end_nodes - _start_nodes,
			"objects_start": _start_objects,
			"objects_end": end_objects,
			"objects_delta": end_objects - _start_objects,
		},
		"events": _events.duplicate(true),
		"metadata": combined_metadata,
		"formal_numeric_threshold_available": false,
		"numeric_pass_threshold_invented": false,
		"classification_policy": "REPORT_METRICS_AND_TREAT_ONLY_UNEQUIVOCAL_REGRESSION_OR_ERROR_AS_FAILURE",
		"gameplay_authority": false,
		"authority": AUTHORITY,
	}
	return _last_report.duplicate(true)


func is_capturing() -> bool:
	return _capturing


func last_report() -> Dictionary:
	return _last_report.duplicate(true)


func contract_snapshot() -> Dictionary:
	return {
		"schema": REPORT_SCHEMA,
		"measurement_only": true,
		"fps_authority": false,
		"frame_time_threshold_invented": false,
		"gameplay_authority": false,
		"mutates_runtime_state": false,
		"authority": AUTHORITY,
	}


func _node_count() -> int:
	var root: Node = get_tree().root if get_tree() != null else null
	return _count_node_recursive(root) if root != null else 0


func _count_node_recursive(node: Node) -> int:
	var count: int = 1
	for child: Node in node.get_children():
		count += _count_node_recursive(child)
	return count


func _static_memory_bytes() -> int:
	return int(Performance.get_monitor(Performance.MEMORY_STATIC))


func _average(values: Array[float]) -> float:
	if values.is_empty():
		return 0.0
	var sum: float = 0.0
	for value: float in values:
		sum += value
	return sum / float(values.size())


func _percentile(sorted_values: Array[float], fraction: float) -> float:
	if sorted_values.is_empty():
		return 0.0
	var index: int = clampi(int(ceil(fraction * float(sorted_values.size()))) - 1, 0, sorted_values.size() - 1)
	return sorted_values[index]


func _rejected(reason: String) -> Dictionary:
	return {"status": "REJECTED", "reason": reason, "authority": AUTHORITY}
