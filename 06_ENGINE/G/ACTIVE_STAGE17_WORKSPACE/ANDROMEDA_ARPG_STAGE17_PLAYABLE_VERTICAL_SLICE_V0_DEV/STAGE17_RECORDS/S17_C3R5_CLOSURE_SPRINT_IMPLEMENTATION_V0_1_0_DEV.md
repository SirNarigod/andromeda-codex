# Stage17 / Etapa 31 — S17-C3R5 Closure Sprint — Implementação

Rodada de fechamento: corrige apenas o que bloqueia diretamente a vertical
slice manual (Categorias A-E da autorização), registra o resto como
`POST_STAGE17_BACKLOG`.

## Bloqueio 1 — C2 BLOCKED setup nav destination gap

**Causa raiz real (mais profunda que o esperado)**: não foi só a escolha do
destino do cenário BLOCKED. `AndromedaAuthoritySpaceMapper` ancora
`local↔iso` no PRIMEIRO snapshot de cada sessão nova, pareando com a
posição REAL do Player naquele instante (`establish_from_snapshot`).
Rodar o mesmo gate repetidamente contra o world principal desloca o Player
um pouco a cada vez (movimentos internos do próprio teste), então a
sessão seguinte ancora a partir de uma posição ligeiramente diferente —
enquanto o blocker físico (`ResourceGatherLosBlocker`, `StaticBody3D`
fixo no `Main.tscn`) nunca se move. Depois de rodadas repetidas nesta
sessão, esse desalinhamento cresceu o bastante (~4,5 m) para que nenhum
ponto "do outro lado do blocker" também coubesse dentro de 1,5 m da TREE.

**Correção aplicada**:
1. [`13_GODOT_ARPG_STAGE17/tests/godot/s17c2_resource_authoritative_approach_gather_gate.gd`](../ANDROMEDA_ARPG_STAGE17_PLAYABLE_VERTICAL_SLICE_V0_DEV/13_GODOT_ARPG_STAGE17/tests/godot/s17c2_resource_authoritative_approach_gather_gate.gd) —
   `_derive_blocked_side_destination()`: deriva o destino do cenário
   BLOCKED dinamicamente a partir da geometria REAL do blocker
   (`CollisionShape3D`/`BoxShape3D` já presente na cena) + posição
   autoritativa atual da TREE + `NavigationServer3D.map_get_closest_point`
   — varre offsets crescentes do lado oposto ao blocker até achar um ponto
   navegável, dentro do alcance de coleta e ainda do lado correto do
   blocker. Nenhuma coordenada de log hardcoded.
2. [`STAGE17_TOOLS`... não aplicável — utilitário novo]
   [`13_GODOT_ARPG_STAGE17/tests/godot/s17c3r5_return_to_canonical_anchor.gd`](../ANDROMEDA_ARPG_STAGE17_PLAYABLE_VERTICAL_SLICE_V0_DEV/13_GODOT_ARPG_STAGE17/tests/godot/s17c3r5_return_to_canonical_anchor.gd) +
   `S17C3R5ReturnToCanonicalAnchorGate.tscn` — utilitário one-shot que
   emite UM `MOVE_TO_POINT` autoritativo normal (não é a ferramenta de
   recovery) de volta à âncora canônica do manifesto, lido via
   `AuthoritySpaceMapper.authority_to_local()` já ancorado na própria
   sessão. Usado antes de cada gate que dependa de alinhamento
   Player↔recurso, evitando repetir o drift acumulado.
3. `approach_destination_for()`/`_navigable_standoff_point()` em
   [`13_GODOT_ARPG_STAGE17/scripts/interaction/gathering_client.gd`](../ANDROMEDA_ARPG_STAGE17_PLAYABLE_VERTICAL_SLICE_V0_DEV/13_GODOT_ARPG_STAGE17/scripts/interaction/gathering_client.gd) —
   robustez adicional para o gameplay NORMAL (não só o cenário de teste):
   se a direção "de onde o jogador já está" não for navegável ou o ponto
   navegável mais próximo ficar fora do alcance real, varre as demais
   direções (passo de 30°) na mesma distância de standoff, sempre
   validando a distância do PONTO REALMENTE ANCORADO (`navigation_destination`
   devolvido por `validate_destination`), não do candidato bruto.

**Resultado**: `S17_C2_RESOURCE_AUTHORITATIVE_APPROACH_GATHER = PASS 92/92`
(ver `STAGE17_RUNTIME_STATE/logs/c3_regression/c3r5_c2_final.log`).

## Bloqueio 2 — COMMON/ALPHA target spatial boundary

[`12_AUTHORITY_BACKEND_STAGE17/andromeda_authority_adapter.py`](../ANDROMEDA_ARPG_STAGE17_PLAYABLE_VERTICAL_SLICE_V0_DEV/12_AUTHORITY_BACKEND_STAGE17/andromeda_authority_adapter.py) —
`_active_engagement_block_refs()` (novo) lê dinamicamente, do
`ResourceMetricPlacementRegistry` já carregado, o(s) `block_ref` onde a
engagement atual está materializada — nunca um literal no código.

**Primeira tentativa (revertida por dados reais, não por suposição)**:
filtrar por `npc.block_id == block_ref da engagement`. Rejeitada depois de
medir contra o mundo real: `NPC-01-01-01-013` (block `STA-01-BLK-01`,
DIFERENTE do block da engagement `STA-05-BLK-04`) está genuinamente a
9,6 m do cluster TREE/ORE; `NPC-05-04-03-002` (block `STA-05-BLK-04`, o
MESMO da engagement) está genuinamente a ~2195 km. Um filtro só-por-bloco
teria excluído errado o primeiro e admitido errado o segundo —
`block_id` não se correlaciona com posição física real neste mundo.

**Fix final**: `_active_engagement_center_and_radius_m()` — centro =
centroide das posições REAIS (`iso_x_m/iso_y_m`) dos placements ativos
(TREE/ORE); raio = 20× o espalhamento desses mesmos placements em torno
desse centro (≈70 m aqui) — nenhum valor observado de teste, só a escala
do próprio conteúdo autorado. `_ensure_development_combat_encounter()`
usa isso como FILTRO DE ELEGIBILIDADE real (não só preferência de
ordenação) tanto para reutilizar um alvo já armazenado quanto para buscar
um novo — um NPC fora do raio nunca entra no pool, e um alvo armazenado
fora do raio (como o COMMON histórico, ~2195 km) é tratado como
inelegível e substituído. Se nenhum candidato existir na área, levanta
`NO_VALID_COMMON_TARGET_IN_ACTIVE_AREA` em vez de `AuthorityBootError`
genérico. Nunca vasculha o planeta inteiro.

**Achado colateral importante**: as distâncias de ~80 km/~2195 km
observadas nas rodadas anteriores eram medidas Player↔NPC, e o Player
estava ele mesmo deslocado (~2200 km) durante quase toda essa janela —
uma vez o Player de volta à âncora (ver Bloqueio 1), a distância real
Player↔`NPC-01-01-01-013` também volta a ser pequena. Mas o gap
arquitetural em si (busca sem teto real, só preferência) era genuíno e
independente disso — `NPC-05-04-03-002` está genuinamente a ~2195 km do
cluster de recursos, não por causa do Player.

**Dois bugs reais encontrados e corrigidos durante a validação (não
suposição, medidos diretamente)**:

1. `self.resource_placement_registry` só era populado em `_boot()` DEPOIS
   do bloco `development_profile_bootstrap` — mas é exatamente esse bloco
   que chama `_ensure_development_combat_encounter()`. Ou seja, o registry
   ainda era `None` no exato momento em que meu novo código tentava
   consultá-lo, então o limite métrico nunca era realmente aplicado
   (`_active_engagement_center_and_radius_m()` sempre retornava
   `(None, 0.0)`, e o fallback "sem dados para limitar" deixava passar
   qualquer distância). Corrigido reordenando os dois blocos independentes
   em `_boot()` — só ordem, nenhuma lógica de nenhum dos dois mudou.
2. `ResourceMetricPlacementRegistry._row_dict()` aninha `iso_x_m`/`iso_y_m`
   dentro de `position: {...}` (removendo-os do nível superior do dict) —
   meu código lia `p["iso_x_m"]` direto, que nunca existe nesse formato,
   então `points` ficava sempre vazio mesmo com o registry corretamente
   carregado. Corrigido para ler `p["position"]["iso_x_m"]`.

Ambos confirmados via reprodução direta (script standalone construindo o
adapter real contra o world real, sem Godot) antes de gastar outra
rodada completa do gate: após as duas correções, `_ensure_development_
combat_encounter()` seleciona `NPC-01-01-01-013` (COMMON) e
`NPC-01-01-01-014` (ALPHA), ambos a ~2,16 m do Player na âncora, e uma
segunda chamada (idempotência) devolve exatamente os mesmos refs.

## Bloqueio 3 — GroundLoot authority (reachable)

[`12_AUTHORITY_BACKEND_STAGE17/andromeda_authority_adapter.py`](../ANDROMEDA_ARPG_STAGE17_PLAYABLE_VERTICAL_SLICE_V0_DEV/12_AUTHORITY_BACKEND_STAGE17/andromeda_authority_adapter.py) —
`_confirm_drop_settled()` previamente repassava `params["reachable"]`
(observação local do cliente via raycast físico + NavMesh) diretamente
para `stage16a.confirm_drop_settled(...)`, sem nenhuma reverificação —
exatamente o gap já documentado nos comentários do próprio gate Godot
(`authority_ground_loot_runtime_gate.gd` linha 275-277/549:
"client overwrites a server-side reachable=false with its own physics
observation... not probed from Godot"). Novo `_verify_drop_reachable()`
reusa `ResourceMetricPlacementRegistry.line_of_sight()` — a MESMA
autoridade de bloqueio já usada para gathering — para checar
independentemente se algum blocker offline-baked cruza o segmento
jogador↔posição assentada. A checagem só ESTREITA a alegação do cliente
(um bloqueio real força `reachable=false` mesmo se o cliente alegou
`true`); nunca AMPLIA (cliente alegando `false` é respeitado). Sem
registro de placement (mundos de teste antigos sem manifesto), o
comportamento degrada graciosamente para o valor do cliente — comprovado
por 10/10 testes pré-existentes de `test_stage16b_authority_ground_loot.py`
passando inalterados. Resultado real no gate Godot completo:
**`AuthorityGroundLootRuntimeGate` foi de 51/53 para 53/53, 0 erros** —
a `GROUND_LOOT_REACHABLE_AUTO_SETTLE_LIMITATION` (2 falhas históricas)
não se reproduziu mais depois desta correção de autoridade.

## Dialogue — conexão mínima ao input normal

Achado: `quest_client.gd` (acionado pela tecla E para QUALQUER NPC) só
atende NPCs com quest/oferta já projetada — um NPC puramente de diálogo
(ex.: `NPCB05DialoguePeer` na cena) sempre seria rejeitado
(`QUEST_STATE_NOT_PROJECTED_FOR_NPC`/`NO_PROJECTED_QUEST_FOR_NPC`), e
`npc_dialogue_client.gd` (já vinculado em `_ready()`) nunca era chamado
por nenhum caminho de input normal — só por harnesses de teste.

[`13_GODOT_ARPG_STAGE17/scripts/main.gd`](../ANDROMEDA_ARPG_STAGE17_PLAYABLE_VERTICAL_SLICE_V0_DEV/13_GODOT_ARPG_STAGE17/scripts/main.gd) —
adicionado fallback mínimo: quando `quest_client` rejeita por essas duas
razões específicas E `npc_dialogue_client.dialogue_target_available()`
(o alvo de diálogo é decidido pelo SERVIDOR via
`dialogue_npc_projection`, nunca pela seleção local do jogador — respeita
o contrato já documentado no próprio `npc_dialogue_client.gd`), dispara
`request_dialogue(_selected_target)` usando o NPC selecionado só como
âncora de apresentação do HUD, nunca como identidade.

## Save / Respawn — conexão mínima ao input normal

`save_reload_client.request_manual_save()` e
`death_respawn_client.request_respawn()` já existiam, prontos, mas só
eram chamados por harnesses de teste (`vertical_slice_client_harness.gd`,
gates B10/vertical-slice). Adicionadas em `main.gd::handle_action_event()`:

- `F5` → `save_reload_client.request_manual_save()`.
- `R` → `death_respawn_client.request_respawn()` (colocado ANTES do gate
  `world_input_blocked()` porque respawn precisa funcionar exatamente
  enquanto o mundo está bloqueado por morte; a própria função já se
  autovalida contra `DEAD_AWAITING_RESPAWN`, rejeitando de forma limpa e
  sem efeito colateral em qualquer outro estado).

## Death — já funcional (sem alteração)

`death_respawn_client._on_bridge_command_result_received()` já projeta
`death_event` automaticamente a partir de `REPORT_WATER_EXHAUSTION`
(exaustão de água é o único gatilho de morte existente nesta slice V0 —
dano de inimigo→jogador não existe ainda, ver BACKLOG-03).
`world_input_blocked()` já bloqueia input corretamente durante o estado
de morte. Não fazia falta nenhuma correção — só a tecla de respawn acima.

## Reload/Continue — já funcional (sem alteração)

O boot normal (`_boot()` do adapter, sempre resume o mundo persistido
quando existe) já garante continuidade sem qualquer ação explícita do
cliente. `request_reload_resync()` é um mecanismo de resync EXPLÍCITO
para divergência suspeita, não o "continue" básico — ver BACKLOG-02.

## Vendor / Inventory / Quest — já funcionais (sem alteração)

Confirmado por leitura de código: `main.gd::handle_action_event()` já
roteia `E` para `vendor_client`/`quest_client`/`gathering_client`/
`dropped_bag_client` conforme o tipo de alvo selecionado, e `I` já abre o
inventário via `hud.set_inventory_open(true)`. Nenhum destes passava por
caminho gate-only.
