extends Node
class_name AndromedaSkillClient

## Stage06 skill/hotbar projection boundary (ARPG_SKILL_CORE_CONTRACT_V0_7_0.json).
## Achado da auditoria de 13/09: arpg_skill_core.py (ARPGSkillCore) e o unico
## sistema do backend com contrato aprovado + testes (17) mas SEM nenhum
## cliente Godot e SEM projecao de snapshot no bridge (12_AUTHORITY_BACKEND_STAGE17
## nao tinha nenhuma mencao a "skill" ate entao).
##
## Este script fecha a METADE cliente dessa lacuna, no mesmo padrao ja usado por
## inventory_client.gd/combat_authority_client.gd (projeta snapshot, nunca calcula
## rank/custo/cooldown localmente). Fase 7.1 (14/09) ligou a METADE servidor:
## andromeda_authority_adapter.py agora envia "skill_projection" no snapshot
## (exatamente o formato validado abaixo) e aceita o comando REQUEST_USE_SKILL,
## delegando 100% a ARPGSkillCore.use_skill() ja protegido - confirmado ao vivo
## (aprender+atribuir skill, snapshot reflete estado real, uso sem alvo rejeita
## com SKILL_TARGET_REQUIRED, uma rejeicao de negocio real, nao stub).
## Fase 8.1 (14/09) fechou o resto: request_learn_skill()/request_assign_active()/
## request_activate_passive() ligados a REQUEST_LEARN_SKILL/REQUEST_ASSIGN_ACTIVE_SKILL/
## REQUEST_ACTIVATE_PASSIVE_SKILL no adapter, mesmo delegate-total aos metodos
## correspondentes de ARPGSkillCore (sem gate de item/trainer - o core nunca teve
## essa checagem). Confirmado ao vivo: aprender->PASS, aprender de novo->
## SKILL_ALREADY_LEARNED, ativar passiva->PASS, atribuir passiva como ativa->
## SKILL_NOT_ACTIVE (rejeicao real do core).

signal skills_projected(result: Dictionary)
signal skill_intent_prepared(result: Dictionary)

const AUTHORITY := "GODOT_SKILL_CLIENT_PROJECTION_ONLY"
const ACTIVE_SLOTS := 8
const PASSIVE_SLOTS := 4
const RANK_MIN := 1
const RANK_MAX := 10

var _hud: AndromedaHUDController
var _projection: Dictionary = {}
var _projection_session_ref: String = ""
var _last_snapshot_sequence: int = -1
var _needs_resync: bool = true
var _request_serial: int = 0
var _last_intent: Dictionary = {}
var _bound: bool = false


func bind_runtime(hud_value: AndromedaHUDController) -> Dictionary:
	if hud_value == null:
		return _rejected("HUD_REQUIRED")
	_hud = hud_value
	if not _bound:
		var bridge: AndromedaRuntimeBridge = _bridge()
		if bridge != null and not bridge.snapshot_applied.is_connected(_on_bridge_snapshot_applied):
			bridge.snapshot_applied.connect(_on_bridge_snapshot_applied)
		_bound = true
	return {"status": "PASS", "authority": AUTHORITY}


## Backend agora envia "skill_projection" no snapshot (fase 7.1, 14/09) no
## formato {active_slots: Array[8], passive_slots: Array[4], skills:
## {skill_ref: {rank: 1..10, mastery_progress: float}}}, mesmo nivel de
## validacao ja feito em inventory_client.gd#_validate_snapshot_shape.
func project_skill_snapshot(snapshot: Dictionary) -> Dictionary:
	var external: Dictionary = _validate_external(snapshot)
	if external.get("status") != "PASS":
		return external
	var shape: Dictionary = _validate_snapshot_shape(snapshot)
	if shape.get("status") != "PASS":
		return shape
	var sequence: int = int(snapshot.get("snapshot_sequence"))
	_projection_session_ref = str(snapshot.get("session_ref", ""))
	_last_snapshot_sequence = sequence
	_projection = {
		"snapshot_sequence": sequence,
		"active_slots": (snapshot.get("active_slots", []) as Array).duplicate(true),
		"passive_slots": (snapshot.get("passive_slots", []) as Array).duplicate(true),
		"skills": (snapshot.get("skills", {}) as Dictionary).duplicate(true),
	}
	_needs_resync = false
	var ui_result: Dictionary = {}
	if _hud != null and _hud.has_method("project_skill_state"):
		ui_result = _hud.project_skill_state(_projection)
	var result := {
		"status": "PASS",
		"snapshot_sequence": sequence,
		"ui_projection": ui_result,
		"rank_calculated_locally": false,
		"mastery_calculated_locally": false,
		"cooldown_calculated_locally": false,
		"authority": AUTHORITY,
	}
	skills_projected.emit(result.duplicate(true))
	return result


## Prepara o envelope de intent pra usar uma skill (execucao real fica com
## ARPGSkillCore/ARPGCombatCore no backend - este metodo so empacota o pedido).
func request_use_skill(skill_ref: String, active_slot: int) -> Dictionary:
	if _needs_resync:
		return _rejected("SKILL_PROJECTION_NOT_YET_RECEIVED")
	if skill_ref.strip_edges().is_empty() or active_slot < 1 or active_slot > ACTIVE_SLOTS:
		return _rejected("SKILL_REF_AND_VALID_ACTIVE_SLOT_REQUIRED")
	return _prepare_intent("REQUEST_USE_SKILL", {
		"skill_ref": skill_ref.strip_edges(),
		"active_slot": active_slot,
		"client_presentation_only": true,
	})


## Fase 8.1 (Stage17, 14/09): mesmo molde de request_use_skill - a execucao real
## fica com ARPGSkillCore.learn_skill(), este metodo so empacota o pedido.
func request_learn_skill(skill_ref: String) -> Dictionary:
	if _needs_resync:
		return _rejected("SKILL_PROJECTION_NOT_YET_RECEIVED")
	if skill_ref.strip_edges().is_empty():
		return _rejected("SKILL_REF_REQUIRED")
	return _prepare_intent("REQUEST_LEARN_SKILL", {
		"skill_ref": skill_ref.strip_edges(),
		"client_presentation_only": true,
	})


func request_assign_active(skill_ref: String, slot: int) -> Dictionary:
	if _needs_resync:
		return _rejected("SKILL_PROJECTION_NOT_YET_RECEIVED")
	if skill_ref.strip_edges().is_empty() or slot < 1 or slot > ACTIVE_SLOTS:
		return _rejected("SKILL_REF_AND_VALID_ACTIVE_SLOT_REQUIRED")
	return _prepare_intent("REQUEST_ASSIGN_ACTIVE_SKILL", {
		"skill_ref": skill_ref.strip_edges(),
		"slot": slot,
		"client_presentation_only": true,
	})


func request_activate_passive(skill_ref: String, slot: int) -> Dictionary:
	if _needs_resync:
		return _rejected("SKILL_PROJECTION_NOT_YET_RECEIVED")
	if skill_ref.strip_edges().is_empty() or slot < 1 or slot > PASSIVE_SLOTS:
		return _rejected("SKILL_REF_AND_VALID_PASSIVE_SLOT_REQUIRED")
	return _prepare_intent("REQUEST_ACTIVATE_PASSIVE_SKILL", {
		"skill_ref": skill_ref.strip_edges(),
		"slot": slot,
		"client_presentation_only": true,
	})


func projected_state() -> Dictionary:
	return _projection.duplicate(true)


func needs_resync() -> bool:
	return _needs_resync


func contract_snapshot() -> Dictionary:
	return {
		"active_slots": ACTIVE_SLOTS,
		"passive_slots": PASSIVE_SLOTS,
		"rank_range": [RANK_MIN, RANK_MAX],
		"progression_model": "1_TO_10_BY_USE_MASTERY",
		"class_model": "FIXED_5_CLASS_ARMAMENT_FAMILY",
		"rank_authority": false,
		"cooldown_authority": false,
		"cost_authority": false,
		"backend_projection_wired": true,
		"backend_command_wired": true,
		"backend_command_wired_note": "REQUEST_USE_SKILL + REQUEST_LEARN_SKILL + REQUEST_ASSIGN_ACTIVE_SKILL + REQUEST_ACTIVATE_PASSIVE_SKILL (fase 8.1)",
		"authority": AUTHORITY,
	}


func _prepare_intent(command: String, params: Dictionary) -> Dictionary:
	var bridge: AndromedaRuntimeBridge = _bridge()
	if bridge == null:
		return _rejected("BRIDGE_AUTOLOAD_NOT_FOUND")
	_request_serial += 1
	var prepared_params: Dictionary = params.duplicate(true)
	prepared_params["request_ref"] = "B06-SKILL-REQUEST-%06d" % _request_serial
	var built: Dictionary = bridge.build_command_envelope(command, prepared_params)
	if built.get("status") != "PASS":
		return built
	var transport_result: Dictionary = {
		"status": "NOT_AVAILABLE",
		"reason": "BRIDGE_NOT_READY_NO_LIVE_BACKEND",
	}
	var submitted: bool = false
	if bridge.connection_state().get("authority_session_bound") == true:
		var envelope: Dictionary = built.get("envelope", {}) as Dictionary
		transport_result = bridge.submit_command(
			command, prepared_params, str(envelope.get("command_ref", ""))
		)
		submitted = transport_result.get("status") == "PASS"
	_last_intent = {
		"status": "PASS",
		"intent": command,
		"request_ref": prepared_params["request_ref"],
		"intent_envelope": built,
		"transport_result": transport_result,
		"transport_submitted": submitted,
		"authority": AUTHORITY,
	}
	skill_intent_prepared.emit(_last_intent.duplicate(true))
	return _last_intent.duplicate(true)


func _validate_snapshot_shape(snapshot: Dictionary) -> Dictionary:
	if not snapshot.get("active_slots", []) is Array or (snapshot.get("active_slots") as Array).size() != ACTIVE_SLOTS:
		return _rejected("EXACTLY_%d_ACTIVE_SKILL_SLOTS_REQUIRED" % ACTIVE_SLOTS)
	if not snapshot.get("passive_slots", []) is Array or (snapshot.get("passive_slots") as Array).size() != PASSIVE_SLOTS:
		return _rejected("EXACTLY_%d_PASSIVE_SKILL_SLOTS_REQUIRED" % PASSIVE_SLOTS)
	if not snapshot.get("skills", {}) is Dictionary:
		return _rejected("INVALID_SKILLS_PROJECTION")
	return {"status": "PASS", "authority": AUTHORITY}


func _validate_external(snapshot: Dictionary) -> Dictionary:
	if snapshot.get("server_authoritative") != true:
		return _rejected("NON_AUTHORITATIVE_SKILL_SNAPSHOT")
	var session: AndromedaClientSession = _session()
	if session == null or not session.has_active_session():
		return _rejected("NO_ACTIVE_SESSION")
	var session_ref_value: String = str(snapshot.get("session_ref", "")).strip_edges()
	if session_ref_value != session.session_ref():
		return _rejected("SESSION_MISMATCH")
	var sequence_value: Variant = snapshot.get("snapshot_sequence")
	if typeof(sequence_value) != TYPE_INT or typeof(sequence_value) == TYPE_BOOL or int(sequence_value) <= _last_snapshot_sequence:
		return _rejected("STALE_OR_DUPLICATE_SKILL_SNAPSHOT")
	return {"status": "PASS", "authority": AUTHORITY}


func _on_bridge_snapshot_applied(snapshot: Dictionary) -> void:
	var projection_value: Variant = snapshot.get("skill_projection")
	if not projection_value is Dictionary:
		return  # sessao ainda nao recebeu um snapshot com este campo
	var projection: Dictionary = (projection_value as Dictionary).duplicate(true)
	projection["server_authoritative"] = snapshot.get("server_authoritative")
	projection["session_ref"] = snapshot.get("session_ref")
	projection["snapshot_sequence"] = snapshot.get(
		"presentation_sequence", snapshot.get("snapshot_sequence")
	)
	project_skill_snapshot(projection)


func _bridge() -> AndromedaRuntimeBridge:
	return get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge


func _session() -> AndromedaClientSession:
	return get_node_or_null("/root/ClientSession") as AndromedaClientSession


func _rejected(reason: String) -> Dictionary:
	return {"status": "REJECTED", "reason": reason, "authority": AUTHORITY}
