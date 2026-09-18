# Stage17 / Etapa 31 — S17-C1A Resource Metric Placement Authority Design

Status: `COMPLETE / AWAITING_AUTHOR_DECISION`

Implementation: `NOT_STARTED`

Esta rodada é exclusivamente de arquitetura. Nenhum backend, cliente Godot, contrato protegido, gate, banco, checkpoint ou backup foi alterado ou criado.

## 1. Resultado executivo

O projeto já contém fundamentos fortes para uma autoridade espacial de Resources: coordenadas métricas isométricas, persistência por `world_instance_id`, identidade determinística, zonas/blocos com limites geográficos, chunks, projeção LOD e exemplos de objetos que persistem posição individual. Porém, nenhum desses mecanismos hoje atribui uma posição métrica individual aos `GTH-*`.

O bloqueio de C1 é estrutural:

- `GTH-*` identifica um gathering node lógico e seu pool de depletion;
- o node conhece `world_instance_id`, `zone_ref` e `block_ref`;
- o backend só valida que Player e Resource estão no mesmo bloco;
- não existe `iso_x_m`, `iso_y_m`, altitude individual, raio métrico, LOS ou blocker para Resources;
- a projection atual `GODOT_LOCAL_PLACEHOLDER_ONLY` está correta e não deve ser promovida.

Recomendação técnica: **placement híbrido, produzido em build-time e materializado como autoridade por mundo**. Placements importantes são autorais; Resources comuns podem ser gerados deterministicamente dentro de regiões/exclusões autorais. O artefato de authoring é validado/baked offline, e o backend Stage17 materializa posições estáveis sem aceitar coordenadas do cliente.

A implementação continua bloqueada até o autor decidir a política de população e, principalmente, a granularidade entre identidade física e o `GTH-*` lógico.

## 2. Padrões espaciais existentes auditados

| Padrão existente | Evidência | Reutilização permitida | Limite |
|---|---|---|---|
| Frame geodético ↔ isométrico métrico | `01_RUNTIME/spatial_coordinates.py` | Reutilizar CRS, unidades, conversão e chunk derivado | Não cria placement de Resource |
| Anchors determinísticos por seed/tag/bbox | `_point_for_bbox`, `_point_near` em `spatial_coordinates.py` | Reutilizar o princípio de inputs estáveis + hash | Implementação atual não possui placement revision, terrain/exclusion validation nem identidade de Resource |
| Encounter anchors determinísticos | `01_RUNTIME/arpg_world_core.py` | Reutilizar padrão seed + zone + ordinal | São slots de encounter, usam altitude placeholder e não são Resources |
| Movimento métrico persistido | `01_RUNTIME/continuous_movement.py`, tabela `v15_motion_state` | Reutilizar frame, validação finita, hash e escopo de mundo | Tabela é para entidades móveis; Resource estático não deve ser disfarçado de actor |
| Actor home position | `01_RUNTIME/arpg_actor_core.py` | Referência de separação identity/state/position | Sem relação com nodes GTH |
| Posição exata de Ground Loot | `01_RUNTIME/arpg_ground_loot_core.py` | Referência de payload posicional individual persistido e hash-protegido | Drop nasce após evento e não pode ser fonte retroativa da posição do Resource |
| Posição exata de DroppedBag | `01_RUNTIME/arpg_water_bag_survival_core.py` | Referência de posição persistente por ref/world | Semântica de container/death, não placement de conteúdo |
| Objetos de cena com coordenada e range | `scene_interaction.py`, `spatial_coordinates.py`, `collision_interaction.py` | Referência para binding métrico e checagem de distância | A geração atual é runtime-derived e não traz política de Kit/terrain para Resources |
| World → zone → block e bounding regions | `country_scale.py`, `arpg_world_core.py` | Contenção, lookup, validação de zone/block | Centro de block/subregion não é posição individual |
| Country resources/flora/fauna | `country_scale.py` | Fonte de identidade, kind, capacidade e depletion agregados | Records não possuem coordenada individual |
| Atlas LOD e chunk payload | `atlas_country_lod.py`, `streaming_system.py` | Modelo de projection filtrada e ownership/chunk | A layer de Resources é block-level; não projeta instâncias físicas |
| ACTIVE / PRELOAD / SYSTEMIC | `arpg_terrain_traversal_streaming_core.py` | Política de materialização seletiva no Godot | `CELL-S16A-*` é cálculo de área/local e não deve virar identidade autoritativa persistente |
| Roads, bridges, hydrology e infrastructure | `arpg_mobility_infrastructure_core.py`, `arpg_world_core.py`, Master READ_ONLY | Futuras constraints/exclusions e contexto de acesso | Parte dos connectors/attachments é derived/coarse; não forma hoje um mapa métrico completo de blockers |
| CollisionInteractionSystem | `collision_interaction.py` | Padrão de servidor consultando posição authoritative de objetos | Só cobre scene objects/room boundaries; não há LOS de gathering |
| Living integration | `arpg_living_integration_core.py` | Preservar Resources como disponibilidade/depletion agregada | Living não precisa receber cada placement individual para continuar sistêmico |

Conclusão de reutilização: reaproveitar **frame, identidade mundial, hashing, persistência e projection**, mas não reaproveitar uma coordenada existente como se já fosse a posição do Resource.

## 3. Arquitetura atual de Resource e causa do bloqueio

`arpg_gathering_nodes` persiste o `node_ref GTH-*`, escopo territorial, tipo de atividade, fonte e definition hash. O `node_ref` deriva de:

`world_seed | activity | block_ref | source_kind | source_ref`

Mineral/flora/fauna são registros agregados do Country Runtime. Um `GTH-*` representa atualmente um pool lógico de trabalho/depletion, não comprovadamente uma árvore, rocha ou veio físico individual.

`create_work_order()` e `execute_work_order()` comparam apenas `worker_block_ref == node_block_ref`. O output físico usa a posição autoritativa do **Player** no instante da entrega. Portanto:

- identidade e depletion existem;
- position authority individual não existe;
- range métrico não existe;
- a posição do Player/drop não prova a posição do node;
- scene transform Godot não pode preencher o gap.

## 4. Opção A — Authorial Placement

Cada placement é explicitamente produzido pelo conteúdo da sub-região e entra em um manifest de build validado. O backend materializa a posição por mundo.

Fluxo conceitual:

`Blender/Godot/Kits authoring → export manifest → offline validator/bake → authoritative content artifact → Stage17 runtime materialization → snapshot → Godot presentation`

Dados conceituais: Resource identity, world/zone/block, posição métrica, altitude/binding, placement revision, source manifest hash e estado de ativação.

Vantagens:

- maior controle autoral e legibilidade do level design;
- melhor adequação para hero trees, minério importante, landmarks e tutorial;
- depuração e revisão visual simples;
- ótima previsibilidade de save/reload;
- integração natural com Kits e greybox.

Desvantagens:

- custo autoral alto para grande densidade;
- risco de erro manual/overlap sem validator;
- manifests maiores;
- manutenção trabalhosa em escala planetária.

Persistência: posição/revision materializadas por mundo; depletion permanece no core atual. Mudança de conteúdo nunca move placement de mundo existente silenciosamente.

## 5. Opção B — Deterministic Procedural Placement

A posição deriva de inputs estáveis, por exemplo:

`world_seed + placement_region_ref + resource/source identity + ordinal + placement_algorithm_version + constraint_set_hash`

O algoritmo precisa de regiões permitidas, exclusions, terrain/traversal input e ordenação canônica de candidatos. `random()` sem contrato, seed sem versão ou regeneração a cada boot não é aceitável.

Vantagens:

- escala e densidade com menor custo manual;
- repetibilidade quando inputs/algoritmo são congelados;
- eficiente para população comum;
- bom encaixe em chunks e geração de novos worlds.

Desvantagens:

- controle autoral inferior;
- impedir overlap/água/estrada/casa/cliff exige dados espaciais confiáveis;
- debugging e migration mais difíceis;
- mudança de algoritmo pode mover milhares de objetos;
- procedural puro não resolve sozinho terrain compatibility.

Persistência mínima segura: seed, algorithm version, content/constraint hashes e placements **materializados** no primeiro build/world. Removed/depleted/override state precisa persistir. Recalcular posições em todo reload é desaconselhado.

## 6. Opção C — Hybrid Placement

Combina:

- placements autorais explícitos para Resources importantes;
- regiões, densidades e exclusions autorais para common Resources;
- geração determinística versionada dentro dessas regiões;
- bake/materialização dos resultados antes do gameplay;
- overrides autorais explícitos e auditáveis.

Vantagens:

- controle onde importa e escala onde é seguro;
- melhor compatibilidade com Kits/Blender/Godot;
- permite hero placements e população comum no mesmo contrato;
- procedural deixa de depender de adivinhar terreno porque trabalha dentro de regiões validadas;
- snapshot e runtime continuam simples: ambos consomem placements materializados.

Desvantagens:

- pipeline de build/validation mais complexo;
- exige política clara de precedência entre explicit/generated/override;
- exige versionar manifest, algoritmo e migrations;
- torna indispensável decidir a relação entre placement físico e pool GTH.

Esta é a opção tecnicamente recomendada.

## 7. Relação com `GTH-*` e identidade física

Os `GTH-*` existentes devem permanecer. Eles já ligam source, activity, depletion e work orders.

Há duas cardinalidades possíveis:

1. **1 GTH = 1 placement físico/site.** Menor mudança para a primeira sub-região. O placement registry usa `(world_instance_id, node_ref)` como chave.
2. **1 GTH = pool lógico; N placements físicos = instâncias desse pool.** Melhor para várias árvores/pedras visíveis, mas requer uma identidade estável adicional de placement/instance e resolução `placement_ref → node_ref` antes do gather.

Recomendação: preservar GTH como autoridade lógica e permitir uma identidade física separada quando houver cardinalidade N:1. Para Playable V0, materializar um placement explícito para os GTH escolhidos de TREE/ORE evita reescrever depletion. Não se deve gerar uma nova família de refs sem a decisão autoral de granularidade.

## 8. Persistência por opção

| Estado | Authorial | Procedural | Hybrid |
|---|---|---|---|
| Position | Manifest + materialização por world | Resultado materializado; não só recalculado | Explicit/generated materializados |
| Seed | Opcional/proveniência | Obrigatória | Obrigatória para regiões geradas |
| Algorithm version | Import/bake version | Obrigatória | Obrigatória para parte gerada |
| Placement revision | Obrigatória | Obrigatória | Obrigatória |
| Depletion | GTH existente | GTH/instance mapping decidido | GTH/instance mapping decidido |
| Removed/override | Persistido | Persistido | Persistido |
| World identity | Obrigatória | Obrigatória | Obrigatória |
| Manifest/constraint hash | Obrigatório | Obrigatório | Obrigatório |

## 9. Altitude e terrain binding

O backend possui `altitude_m` em movimento e objetos posicionados, mas não existe hoje uma authority de heightfield detalhada capaz de calcular a altura de cada Resource. O `coordinate_center.altitude_m` de block/subregion é uma altitude agregada, não o chão individual.

Política recomendada:

- `iso_x_m`/`iso_y_m` são obrigatórios;
- altitude é explicitamente authored/baked a partir do mesmo artefato de terreno da sub-região;
- a origem da altitude e o terrain artifact hash acompanham o placement;
- durante design, altitude pode estar `UNBOUND`, mas o placement não se torna `ACTIVE_INTERACTIVE` até validação;
- `0.0` não pode ser fallback universal silencioso;
- Godot pode conformar apresentação visual, mas não reescrever authority em runtime.

## 10. Walkability, blockers e exclusions

Placement válido deve passar por combinação de build-time e runtime integrity:

1. validator offline confirma finitude, zone/block containment e identidade;
2. bake consulta o artefato de terrain/traversal, water, buildings, roads/bridges e exclusion volumes;
3. overlap é resolvido deterministicamente com ordem estável de candidatos;
4. o backend importa apenas manifest validado/hashado;
5. Godot pode detectar divergência de apresentação, mas nunca corrigi-la como authority.

O `CollisionInteractionSystem` mostra que o backend sabe checar distância/blockers de scene objects, mas não há regra protegida de LOS para gathering nem um obstacle map completo para Resources.

Classificação:

- metric distance: necessária para C2, mas o valor de range requer decisão autoral;
- placement walkability/exclusions: necessária no bake;
- LOS/blocker server-side de gather: `AUTHOR_DECISION_REQUIRED`;
- pathfinding Godot: apresentação/orquestração, não prova de authority.

## 11. World / zone / block / cell

Hierarquia autoritativa recomendada:

`world_instance_id → zone_ref → block_ref → metric position`

`subregion_ref` e `placement_region_ref` podem refinar authoring quando estáveis. O `CELL-S16A-*` atual é calculado de uma posição local para streaming/presentation; não deve ser requisito de identidade nem fonte da posição. `chunk_id`/cell podem ser derivados e indexados para consulta/projection.

## 12. ResourceMetricPlacementRegistry — recomendação conceitual

Criar futuramente um serviço Stage17 adjacente ao gathering/world spatial layer, não dentro do core protegido e não no Godot.

Responsabilidades:

- resolver `node_ref`/future `placement_ref` para posição métrica;
- validar world/zone/block/revision/manifest hash;
- manter placements materializados e hash-protegidos;
- expor queries por área/chunk para projection;
- fornecer posição ao guard métrico de gathering;
- preservar removed/override/migration state;
- rejeitar qualquer posição vinda de gameplay client.

Não deve decidir yield, tool, stamina, depletion, loot ou Living. O gathering protegido continua dono dessas regras; o serviço espacial adiciona o pré-requisito métrico Stage17 antes da delegação.

## 13. Gather range e LOS

Os contratos auditados dizem que o Resource deve ser abordado conforme seu target contract, mas não definem um número métrico de gathering. Os valores de 11–18 m encontrados pertencem à câmera, não ao gather.

Status formal:

`RESOURCE_GATHER_METRIC_RANGE_POLICY_REQUIRES_AUTHOR_DECISION`

Não existe regra protegida de LOS para gathering. O cliente já possui blocker/path checks de apresentação em outros sistemas, mas isso não constitui autoridade server-side.

Status:

`RESOURCE_GATHER_BLOCKER_LOS_POLICY = AUTHOR_DECISION_REQUIRED`

## 14. Pipeline de authoring recomendado

1. Autor constrói a sub-região com Kits no Blender/Godot/editor.
2. Placements explícitos, regions, density e exclusions são exportados como **dados de authoring**, nunca como command de gameplay.
3. Um validator/bake offline converte o arquivo para o frame territorial, valida bounds/terrain/overlap e produz manifest canônico ordenado.
4. O manifest registra schema/revision, source hashes, coordinate frame e placement hash.
5. Backend Stage17 importa/materializa em world creation ou migration explícita.
6. Snapshot projeta somente o conjunto relevante.
7. Godot cria/move presentation proxies a partir da projection.

Formato recomendado: JSON canônico e tool-neutral como artefato de intercâmbio. Blender/Godot Resources podem ser formatos de authoring internos, mas não o formato exclusivo de autoridade do Python.

## 15. Blender e Godot

Blender/Godot podem ser excelentes editores espaciais, desde que:

- emitam IDs/anchors e transforms no export offline;
- o exporter declare coordinate frame/scale/axis e provenance;
- o validator reprove NaN/Inf, out-of-bounds, overlap e referências desconhecidas;
- o manifest final seja hashado e importado pelo backend;
- transforms runtime do Node não sejam aceitos como correção de authority.

Assim, Godot ajuda a posicionar sem se tornar autoridade gameplay.

## 16. Reproducibility e versioning

Prova futura:

`same world seed + same content manifest hash + same placement schema/revision + same algorithm version + same constraints → same canonical sorted placement hash`

Versionamento mínimo:

- `resource_placement_schema_version` — formato;
- `resource_placement_revision` — conteúdo autoral;
- `placement_algorithm_version` — somente geração procedural;
- `source_manifest_hash` e `terrain/constraint hash`;
- migration identifier quando houver mudança de mundo existente.

O algoritmo não pode mudar posições de um world existente por simples upgrade de código.

## 17. Save compatibility e migration

- **DEV world:** pode ser descartado/recriado ou migrado explicitamente, sempre com record de mudança.
- **RELEASE world:** placement revision fica congelada; nenhuma movimentação silenciosa. Alteração exige migration que mapeie old/new placement refs e preserve depletion/removal.
- **NEW world:** nasce diretamente na revision atual.

Mover um Resource entre builds sem migration é incompatibilidade de save, mesmo se o `GTH-*` continuar igual.

## 18. Tratamento dos GTH atuais

Primeira migration conceitual recomendada:

- manter o Stage17 dev world ou criar uma nova world identity somente conforme a política aprovada;
- atribuir placements explícitos aos GTH representativos de TREE e ORE;
- preservar `node_ref`, source, capacity e depletion;
- registrar revision/provenance;
- não regenerar GTH;
- não inferir posição de Node Godot.

Se múltiplos objetos físicos por pool forem aprovados, a migration também cria identities de placement estáveis e mapeadas ao GTH, sem duplicar depletion.

## 19. Impacto no Living

Living pode continuar operando em escala country/zone/block e usando availability/depletion agregadas. Não é necessário projetar cada árvore/minério no ciclo SYSTEMIC. Placement detalhado pertence à camada espacial ativa do ARPG.

Living só precisaria conhecer posições individuais se uma futura regra sistêmica realmente depender delas. Evitar essa expansão agora preserva separação e performance.

## 20. Performance, scale e projection

- armazenar placements materializados simplifica reload e evita custo de regeneração;
- indexar por world/zone/block e, se útil, por chunk derivado;
- snapshot deve incluir `ACTIVE` com estado detalhado e `PRELOAD` com dados mínimos de materialização;
- `SYSTEMIC` não materializa nodes Godot;
- não enviar o planeta inteiro;
- spatial index avançado pode ser adicionado quando densidade justificar, sem mudar o contrato de identidade.

Risco de escala maior está no tamanho de snapshots e na cardinalidade física, não no cálculo de hash.

## 21. Security / authority

- gameplay client envia apenas target identity e intenção;
- nunca envia Resource position, range override, distance override ou placement correction;
- authoring import é offline/build-time e passa por validação/hash;
- não existe endpoint de gameplay para criar/mover Resource;
- snapshot/projection inclui world identity, sequence, authority label e server-authoritative marker;
- stale/wrong-world content é rejeitado.

## 22. Estratégia de gates futuros

Sem criar gates nesta rodada, a implementação recomendada deverá provar:

1. placement schema/contract e hashes;
2. GTH/placement identity preservation;
3. deterministic reproducibility;
4. persistence/restart/reload;
5. world/zone/block containment;
6. finite position e altitude binding;
7. walkability/water/building/road exclusion;
8. no overlap determinístico;
9. snapshot ACTIVE/PRELOAD e ausência em SYSTEMIC detalhado;
10. stale/session/world rejection;
11. no client position injection;
12. metric gather range;
13. optional LOS/blocker conforme decisão;
14. depletion continuity;
15. save migration;
16. no duplicate placement após streaming;
17. no Stage16B/protected mutation.

## 23. Comparação formal

| Critério | Authorial | Procedural | Hybrid |
|---|---|---|---|
| Authority clarity | Muito alta | Alta se algoritmo/inputs congelados | Muito alta após bake |
| Author control | Máximo | Baixo/médio | Alto onde importa |
| World-building | Excelente para composição | Bom para população | Excelente |
| Repeatability | Alta | Alta com versioning | Alta |
| Scale | Baixa/média | Muito alta | Alta |
| Runtime performance | Alta após materialização | Alta após materialização | Alta após materialização |
| Save compatibility | Simples se IDs estáveis | Arriscada sem materialização | Boa com revision congelada |
| Kit workflow | Excelente | Indireto | Excelente |
| Blender workflow | Excelente | Regions/exclusions apenas | Excelente |
| Godot workflow | Excelente como editor/proxy | Regions/preview | Excelente |
| Debugging | Simples | Mais difícil | Moderado |
| Migration | Explícita e localizada | Difícil em massa | Controlável por revision |
| Terrain compatibility | Boa com bake | Complexa | Melhor equilíbrio |
| Streaming | Direto | Direto após materialização | Direto |
| Complexity | Baixa/média | Alta | Alta, mas modular |
| Main risk | Authoring cost | Drift/invalid placement | Identity/cardinality policy |

## 24. Technical recommendation

Adotar **Hybrid Placement, Offline-Baked, Runtime-Materialized**:

- JSON canônico tool-neutral como manifest final;
- authorial explicit placements + procedural regions/exclusions;
- deterministic generation versionada apenas no bake;
- posições materializadas e congeladas por world/revision;
- `ResourceMetricPlacementRegistry` Stage17 adjacente ao world/gathering;
- GTH protegido como logical/depletion authority;
- identidade física adicional apenas se o autor aprovar múltiplos placements por GTH;
- altitude proveniente de terrain bake validado;
- Godot como authoring aid/presentation, nunca runtime authority;
- Living permanece agregado.

## 25. Riscos principais

1. Ambiguidade 1:1 versus N:1 entre GTH e objetos físicos.
2. Ausência atual de heightfield/terrain authority detalhada.
3. Range métrico de gathering ainda não definido.
4. LOS/blocker de gathering ainda não contratado server-side.
5. Mudança de placement revision pode quebrar saves sem migration.
6. Exporter com axis/scale incorretos pode deslocar toda a sub-região.
7. Procedural sem exclusions autorais pode invadir água/estrada/construções.
8. Snapshot amplo pode escalar mal se ignorar ACTIVE/PRELOAD/SYSTEMIC.

## 26. Decisões essenciais solicitadas ao autor

1. Aprovar o modelo **híbrido**: placements manuais para Resources importantes e geração determinística, limitada por regiões/exclusions autorais, para população comum?
2. Cada árvore/rocha/minério visível terá um `GTH-*`/depletion próprio, ou vários placements físicos poderão compartilhar um `GTH-*` como pool lógico? Recomendação técnica: GTH como pool lógico + identity física separada quando N:1 for necessária.
3. Aprovar a política de estabilidade: worlds de release congelam a placement revision e só mudam por migration explícita; worlds DEV podem ser recriados/migrados com record auditável?

## 27. Integridade e disposição

Stage16B permanece `CLOSED / READ_ONLY`.

Checkpoint e backup esperados e revalidados ao final desta rodada:

`77276aa0bcff0475193d2b85a89fdee7d27564b8b5c83af09f8725b414cd67cc`

Disposição:

- `S17_C1A_RESOURCE_METRIC_PLACEMENT_DESIGN = COMPLETE`
- `S17_C1A_IMPLEMENTATION = NOT_STARTED`
- `AWAITING_AUTHOR_DECISION = true`
- `S17_C1_RESOURCE_AUTHORITY_POSITION_CONTRACT = BLOCKED`
- `S17_C2_RESOURCE_AUTHORITATIVE_APPROACH_GATHER = NOT_STARTED`

