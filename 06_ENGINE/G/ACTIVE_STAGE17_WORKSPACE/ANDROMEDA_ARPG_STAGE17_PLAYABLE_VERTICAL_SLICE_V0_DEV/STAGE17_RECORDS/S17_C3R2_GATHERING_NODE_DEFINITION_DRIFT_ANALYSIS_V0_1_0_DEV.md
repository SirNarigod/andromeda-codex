# Stage17 / Etapa 31 — S17-C3R2 Gathering Node Definition Drift — Root Cause

Rodada 100% read-only. Zero mutação, zero engine mutável construído, zero
`resume_world()` chamado. Prova por hash ao final.

## Causa raiz — provada por código, não por inferência

`arpg_gathering_work_core.py::_consume_source()` linha 421:

```python
elif node["source_kind"]=="FAUNA": src["count"]=current-taken
self.country._persist_state()
```

**Toda captura HUNTING bem-sucedida decrementa diretamente
`country_scale_state.payload_json.country.states[...].blocks[...].fauna[...].count`.**
Este é o mesmo mecanismo, correto e autoritativo, que o core protegido usa
para MINERAL/FLORA (`remaining_units`) — para FAUNA ele usa `count` na
própria árvore de dados country-scale.

`arpg_gathering_work_core.py::_insert_node()` linha 210-216, chamada em
TODO boot via `_bootstrap_nodes()` → `ARPGGatheringWorkCore.__init__()`:

```python
def _insert_node(self, d, *, state_remaining=None):
    text, h = self._payload(d)  # recomputa a definição AGORA, do country-scale ATUAL
    row = SELECT definition_hash WHERE node_ref=...
    if row:
        if row["definition_hash"] != h: raise IntegrityError("gathering node drift:"+node_ref)
        return
    INSERT ...
```

`_node_definition()` (linha 184-208) constrói `capacity_units` diretamente de
`a.get("count", 0)` — ou seja, **a definição persistida na primeira vez que
o node foi visto captura o `count` daquele instante como se fosse
identidade fixa e para sempre**, mas o PRÓPRIO subsistema (via
`_consume_source`) muda legitimamente esse mesmo `count` a cada hunt bem
sucedido.

**Isso é um gap arquitetural pré-existente, real, genérico**: qualquer node
FAUNA/FLORA (`renewability: "LIVING_ECOLOGY_STAGE14"`) que seja
suficientemente utilizado via gameplay real eventualmente colide com este
check na próxima vez que `resume_world()` for chamado. Não é exclusivo de
`GTH-1D268772796B25C4CC6B`, não é um evento único.

## Prova numérica exata

- Definição persistida: `capacity_units: 86`.
- `country_scale_state` atual (lido read-only): `FAU-BROWSER-05-04-01.count = 58`.
- Diferença: 28 unidades consumidas.
- Esse número é plausível e consistente com o volume real de testes
  HUNTING desta sessão (diagnóstico C3A repetido + múltiplas execuções do
  gate GroundLoot, cada uma criando 3 drops via o mesmo node, mais
  tentativas anteriores).

## Comparação field-by-field

| FIELD | PERSISTED | EXPECTED (recomputado do country-scale atual) | CLASSIFICATION |
|---|---|---|---|
| node_ref | GTH-1D268772796B25C4CC6B | mesmo | IDENTICAL |
| world_instance_id | rt:world:bd0f78f5-... | mesmo | IDENTICAL |
| zone_ref/block_ref | ZONE-STA-05-BLK-04 / STA-05-BLK-04 | mesmo | IDENTICAL |
| activity_type/source_kind | HUNTING/FAUNA | mesmo | IDENTICAL |
| source_ref | FAU-BROWSER-05-04-01 | mesmo | IDENTICAL |
| output_item_ref | ITEM-FAUNA-FAU-BROWSER | mesmo | IDENTICAL |
| source_meta.species_ref/role/tier/name | FAU-BROWSER/HERBIVORE/MÉDIO/Folhívoro de Dossel | mesmo | IDENTICAL |
| **capacity_units** | **86** | **58** | **VALUE_DRIFT** |
| definition_hash | be85ac2a... | (recalculado, diferente) | HASH_ONLY (consequência do VALUE_DRIFT acima, não uma causa própria) |

Nenhum outro campo diverge. Não há `TYPE_DRIFT`, `MISSING_PERSISTED`,
`NEW_EXPECTED_FIELD` ou `ORDERING_ONLY` — a canonicalização (`canonical_json`,
chaves ordenadas, separadores compactos) é estável; confirmei recomputando o
hash do JSON persistido e batendo exatamente com `definition_hash` — a linha
persistida em si não está corrompida, ela é internamente consistente. O
único problema é que ela ficou **desatualizada** em relação a uma fonte que
mudou legitimamente depois.

## Linha do tempo real (corrigindo uma suposição inicial errada)

As primeiras comparações contra `_archive_pre_COMBAT_20260829T071705Z_authority`
e arquivos irmãos pareciam mostrar `count=86` "antes" — **isso estava
errado**: esses arquivos são os mundos de cold-boot quebrados
(`world_instance_id` aleatório) do próprio incidente de metodologia relatado
em `S17_C1B_C1_C2_INVALIDATED_RUNS`, não o mundo real `bd0f78f5`. Coincidem
em `count=86` só porque a seed (160800) gera a mesma população inicial para
qualquer instância nova. Confirmado por leitura direta de `worlds.world_instance_id`
em cada arquivo.

Os únicos dois backups genuínos de `bd0f78f5` disponíveis são:

- `_archive_pre_wal_discard_repair_20260829T0900Z_authority` (05:30): `count=58` — **já drifted**.
- Live atual (06:11): `count=58` — igual.

**Não existe nenhum backup real de `bd0f78f5` anterior ao drift.** O mundo
`bd0f78f5` só existe desde a continuação C1B/C1/C2 (primeiro boot
`2026-08-29T06:26:42Z` na sessão anterior); o consumo de 86→58 aconteceu em
algum ponto entre esse primeiro boot e 05:30 — dentro da própria janela de
testes de Combat/GroundLoot/G19 já documentada, coerente com a causa
mecânica provada acima.

## Efeito físico do primeiro dry-run C3R1 — separado e não relacionado

O hash do arquivo principal mudou fisicamente
(`6748cb7b...`→`c84d1bda...`, +155.648 bytes) quando o primeiro dry-run
falhou, e os arquivos `-wal`/`-shm` foram consumidos. Isso é um **efeito de
checkpoint físico do SQLite** (WAL mesclado ao arquivo principal), não uma
mudança de conteúdo de jogo — o drift semântico (86 vs 58) **já existia**
no arquivo antes desse checkpoint acontecer (confirmado: o mesmo `count=58`
aparece no backup de 05:30, feito ANTES da tentativa de dry-run que
crashou). O checkpoint apenas expôs, não causou, o drift.

## Relação com C1B/C1/C2

`GTH-1D268772796B25C4CC6B` **não é** nenhum dos GTH lógicos usados pelos
placements físicos: TREE usa `GTH-CA3D9A47934BD64A24B4`, ORE usa
`GTH-34AC1BC54C33917F0553` — ambos `MINERAL`/`FLORA`
(`NON_RENEWABLE_WITHIN_STAGE09` para ORE, mas FLORA/TREE também carrega
`LIVING_ECOLOGY_STAGE14` e teoricamente poderia sofrer o mesmo tipo de
drift no futuro se consumido o bastante). Como a iteração de
`_bootstrap_nodes()` processa recursos e flora do mesmo bloco
(`STA-05-BLK-04`) antes de fauna, e o erro só disparou na entrada de fauna,
isso é evidência (não prova formal de ordem de `list_zones()`) de que
TREE/ORE deste bloco específico teriam sido revalidados sem erro até esse
ponto desta mesma tentativa de boot. **Não há prova direta de que o drift
invalide qualquer evidência já coletada de C1B/C1/C2** — nenhuma dessas
evidências dependia de um `resume_world()` limpo acontecer depois do fato;
todas foram capturadas via roundtrips HTTP reais, já registrados. C1B/C1/C2
permanecem PASS.

## Opções de recuperação avaliadas (nenhuma executada)

**Opção A — Restaurar de backup**: **DESCARTADA como solução real.** Todo
backup genuíno de `bd0f78f5` já contém o mesmo drift (só existe um, e ele
já está drifted). Restaurar não evita o problema, só muda qual outro estado
(posição do Player, ownership) precisa ser re-resolvido, e o próximo uso
normal de HUNTING neste node reproduziria o mesmo drift de novo assim que
o consumo acumulado justificasse.

**Opção B — Recriar DEV world novo**: Tecnicamente possível (política já
aprovada para DEV worlds), mas desproporcional: exigiria re-bake do
manifesto de placement (novo `world_instance_id` → novos `placement_ref`),
re-verificação completa de C1B/C1/C2 do zero, e não resolve a causa
raiz — um mundo novo sofreria exatamente o mesmo drift assim que HUNTING
suficiente fosse exercido nele de novo.

**Opção C — Migração formal do gathering node — RECOMENDADA.** Duas
variantes, da mais correta à mais conservadora:

- **C1 (correção arquitetural, preferida)**: ajuste em
  `01_RUNTIME/arpg_gathering_work_core.py::_insert_node()` para tratar
  `capacity_units` como campo mutável (não hash-locked) especificamente
  para sources com `renewability == "LIVING_ECOLOGY_STAGE14"` —
  re-derivando e re-persistindo a definição corrente em vez de levantar
  `IntegrityError`. Resolve a causa raiz de forma genérica para qualquer
  node FAUNA/FLORA/FISHING, não só este. Requer autorização explícita para
  tocar `01_RUNTIME` (fora do escopo desta rodada).
- **C2 (correção de dados, interina)**: re-sincronizar apenas
  `arpg_gathering_nodes.definition_json`/`definition_hash` deste ÚNICO
  node_ref para refletir o `capacity_units=58` atual, usando exatamente a
  mesma lógica `_node_definition()`+canonical hash que o código já usa —
  não é "consertar o hash às cegas" (proibido pela Seção 17): o valor novo
  já foi validado contra a fonte autoritativa real nesta auditoria. É um
  band-aid: desbloqueia o boot agora, mas não impede o mesmo drift
  reaparecer com mais HUNTING futuro.

Nenhuma foi implementada nesta rodada.

## Perda de estado se C2 for aplicada
Nenhuma — é uma correção pontual de um snapshot desatualizado, não uma
restauração. Posição do Player, ownership, C1B/C1/C2, depletion de outros
nodes — nada disso é tocado.

## Player recovery
Continua necessário depois de qualquer opção de recuperação do drift —
são problemas independentes. A ordem correta permanece: resolver o drift
(C1 ou C2 acima) → mundo resumível → backup fresco → `repair_stage17_player_position.py --apply`.
