# Stage17 — Post-Closure Backlog

## BLOQUEIO REAL ATIVO (não é backlog — ver relatório final, Seção "current world resumable")
`STAGE17_CURRENT_WORLD_RESUMABLE = false` no momento em que esta rodada
terminou. Causa raiz completa registrada no relatório final e em
`S17_C3R5_CLOSURE_SPRINT_ACCEPTANCE_V0_1_0_DEV.json`. Resumo: o limite
espacial de engagement (Bloqueio 2, correto e funcionando) só encontra 19
NPCs elegíveis por posição perto do cluster de recursos; deste grupo,
apenas 1 permanece vivo e com vida cheia depois do volume de testes reais
de Combat/G19 desta própria rodada — insuficiente para os 2 slots
(COMMON+ALPHA) exigidos no boot. Nenhuma correção de hack foi aplicada.

Itens que NÃO bloqueiam `STAGE17_PLAYABLE_VERTICAL_SLICE_V0_ACCEPTANCE`.
Cada um tem ID, descrição, severidade e sugestão de estágio futuro.

## BACKLOG-01 — Death overlay/prompt ausente na UI
**Severidade:** Cosmético/UX.
`death_respawn_client`'s `death_projected`/`respawn_projected` signals não
têm nenhum listener de apresentação conectado (`grep` confirmou zero
conexões em `13_GODOT_ARPG_STAGE17/scripts`). O estado (`DEAD_AWAITING_RESPAWN`,
bloqueio de input) funciona corretamente e é 100% real/authoritative — só
não há um texto/HUD dizendo "Você morreu — pressione R para renascer". A
tecla R já funciona sem prompt visual.
**Sugestão:** Stage17.1 — HUD minimalista (label + fade) conectado aos
sinais já existentes.

## BACKLOG-02 — `request_reload_resync()` sem gatilho de input normal
**Severidade:** Baixa.
O "continue" básico (fechar e reabrir o jogo, mundo persistido) já funciona
via o boot server-authoritative padrão (`bind_session()` sempre resume o
mundo existente) — não depende deste comando. `request_reload_resync()` é
um mecanismo de resync EXPLÍCITO para divergência detectada, hoje só
acionado por harnesses de teste.
**Sugestão:** Stage17.1 — botão "Resync" no menu de pausa, para uso manual
em caso de suspeita de drift local vs servidor.

## BACKLOG-03 — Morte por combate (dano de inimigo) não existe em V0
**Severidade:** Baixa para V0 (o ciclo morte→respawn É real e jogável via
exaustão de água).
`death_respawn_client._on_bridge_command_result_received()` só projeta
`death_event` automaticamente a partir de `REPORT_WATER_EXHAUSTION`. Não
há mecanismo de dano inimigo→jogador reduzindo HP a zero nesta slice.
**Sugestão:** Stage18 — sistema de dano recebido pelo jogador em combate.

## BACKLOG-04 — GroundLoot: `GROUND_LOOT_REACHABLE_AUTO_SETTLE_LIMITATION` (RESOLVIDA)
**Status:** Aparentemente resolvida como efeito colateral do Bloqueio 3
desta rodada (S17-C3R5) — `AuthorityGroundLootRuntimeGate` foi de 51/53
para **53/53, 0 erros** depois da correção de `_verify_drop_reachable()`.
A limitação original (client sobrescrevendo `reachable` autoritativo) e
esta correção de autoridade compartilhavam a mesma superfície de código;
não foi um alvo direto desta rodada, mas o resultado observado é
positivo. Mantida aqui só como referência histórica — não é mais um
bloqueio nem uma limitação conhecida.

## BACKLOG-05 — Drift de posição do jogador por regressões repetidas no world principal
**Severidade:** Processo/harness, não gameplay.
Rodar o mesmo gate (ex.: C2) várias vezes seguidas contra o world principal
acumula pequenos deslocamentos reais do jogador (cada run começa de onde o
anterior parou), porque o `AndromedaAuthoritySpaceMapper` ancora ao
primeiro snapshot de CADA sessão nova — um design são para um jogador
humano normal (que não se teleporta entre sessões de teste), mas que
amplifica deslocamentos entre execuções automatizadas consecutivas. Foi
exatamente a causa raiz por trás da falha inicial do cenário BLOCKED e do
approach normal de TREE nesta rodada — corrigida com um `MOVE_TO_POINT`
legítimo de volta à anchor canônica, não uma mudança de arquitetura.
**Sugestão:** Stage17.1 — gates regressivos/repetitivos devem rodar contra
cópia descartável do world (já é a regra formal desta rodada, Seção 13);
formalizar isso como prática obrigatória em ferramentas futuras de CI.

## BACKLOG-06 — `S17_G19_COMMON_TARGET_UNBOUNDED_SELECTION_GAP` (referência)
**Severidade:** Já corrigida nesta rodada (S17-C3R5) via limite espacial de
engagement — mantido aqui apenas como referência cruzada ao ID histórico
para rastreabilidade; não é mais um bloqueio.

## BACKLOG-08 — Pickup do corpo de inimigo derrotado às vezes fica fora de alcance
**Severidade:** Baixa — não bloqueia o loop nuclear de combate (selecionar
→ atacar → derrotar), que passa 86/91 no Combat gate após as correções
desta rodada. `AuthorityCombatRuntimeGate.gd`'s aproximação até a bag do
inimigo derrotado (`MOVE_TO_POINT` até a posição do drop, até 40
tentativas) às vezes termina a ~9,4 m do alvo em vez de dentro dos 0,5 m
exigidos — mesma família de problema de aproximação/NavMesh já corrigida
para TREE/ORE nesta rodada (`gathering_client.gd`), mas não replicada
aqui porque não bloqueia nenhum passo do fluxo manual obrigatório (looting
de corpo não está listado como etapa própria na Seção 22 da autorização —
"combat" é satisfeito por selecionar/atacar/derrotar).
**Sugestão:** Stage17.1 — aplicar o mesmo padrão de
`_navigable_standoff_point` (varredura de ângulo + validação de distância
de chegada real) à aproximação de pickup de loot de inimigo.

## BACKLOG-07 — `S17_C2_RESOURCE_AUTHORITATIVE_APPROACH_GATHER` legacy gap ID
Referência cruzada: `S17_C3R5_C2_BLOCKED_SETUP_NAV_DESTINATION_GAP`
corrigido nesta rodada com destino dinâmico derivado da geometria real do
blocker + NavigationServer3D; mantido aqui só como rastreabilidade
histórica.
