# Stage17 / Etapa 31 — S17-C3R4A Gathering Mutable Capacity Contract — Implementação

Status: `S17_C3R4A_GATHERING_MUTABLE_CAPACITY_CONTRACT = PASS`

## Ponto de integração

`01_RUNTIME/integrated_arpg_engine_v09.py::_attach_gathering_arpg()` constrói
`ARPGGatheringWorkCore(self, world_instance_id)` diretamente — é 01_RUNTIME
protegido, não pode ser editado, e não aceita parametrizar a classe. A
própria `12_AUTHORITY_BACKEND_STAGE17/andromeda_authority_adapter.py` já
tinha precedente exatamente para este problema:
`_resume_world_with_immutable_gathering_definitions()` (linha 224-286)
monkey-patcha `ARPGGatheringWorkCore._node_definition` temporariamente
durante o boot normal do adapter, restaurando o original no `finally`.
Esse mecanismo pré-existente **já** neutraliza o crash de boot para FAUNA
especificamente quando o mundo é resumido via o adapter — mas nunca
reconcilia `capacity_units` para o valor real atual (recongela
perpetuamente no primeiro valor visto), não cobre nenhuma construção de
engine fora do adapter (a própria ferramenta de recovery, por exemplo), e
não é genérico por classe de fonte.

Seguindo o mesmo padrão já estabelecido no projeto, a integração escolhida
foi: **monkeypatch de `ARPGGatheringWorkCore._insert_node`** (não
`_node_definition`), instalado a partir de um novo módulo Stage17
dedicado. Como Python resolve métodos dinamicamente, o patch se aplica a
toda instância construída depois de `install()` ser chamado, não importa
qual código faz essa construção — cobre o adapter, a ferramenta de
recovery e qualquer script futuro igualmente, sem exigir tocar em nenhum
call-site protegido.

## Arquivo criado

[`12_AUTHORITY_BACKEND_STAGE17/stage17_gathering_capacity_contract.py`](../12_AUTHORITY_BACKEND_STAGE17/stage17_gathering_capacity_contract.py)

Conteúdo: `classify_definition_diff(persisted, expected)` (função pura,
zero I/O), `install(cls)`/`uninstall()`/`is_installed()`
(monkeypatch idempotente), `install_on_import_path(runtime_dir)`
(conveniência). Nunca cria tabela nova, nunca importa
`resource_metric_placement`/`andromeda_authority_adapter`, nunca contém
`node_ref`/valores reais hardcoded (confirmado por teste estático).

## Schema V2 — como a separação foi implementada

`arpg_gathering_nodes.definition_json`/`definition_hash` continuam sendo
UMA coluna JSON e UMA coluna hash (schema da tabela é 01_RUNTIME
protegido, não pode mudar). A separação STRUCTURAL/MUTABLE não é física
(duas colunas) — é uma separação **de comparação**, feita por
`classify_definition_diff()`: campo-a-campo, decide se a única diferença é
`capacity_units` E `renewability=="LIVING_ECOLOGY_STAGE14"`. Quando
permitido, a definição completa nova é recomputada e repersistida
(`text, h = self._payload(d)`), preservando o invariante que TODO o resto
do core já depende (`sha256(definition_json)==definition_hash`) — `node()`,
`list_nodes()`, `verify()`, `_definition_row()` continuam funcionando sem
qualquer alteração, porque a linha nunca fica logicamente inconsistente.

**Contrato**: `S17_GATHERING_NODE_DEFINITION_SCHEMA_V2` (novo, nomeado
nesta rodada). **Anterior**: `V1_LEGACY_UNVERSIONED` (implícito, nunca
nomeado até a S17-C3R3).

## Comportamento por classe (não generalizado)

O gate é `renewability=="LIVING_ECOLOGY_STAGE14"` — rótulo semântico já
atribuído pelo próprio core protegido a FLORA/FAUNA/FISHING — não uma
lista arbitrária por `source_kind`. Consequência, comprovada por teste:

- **FAUNA**: elegível; é a única classe onde a colisão realmente ocorre
  hoje (`country_scale.py` não separa "máximo" de "atual" para fauna —
  `count` faz os dois papéis).
- **MINERAL**: `renewability=="NON_RENEWABLE_WITHIN_STAGE09"` — **nunca**
  elegível, mesmo que só `capacity_units` divirja (teste 07).
- **FLORA**: elegível em princípio (mesmo rótulo), mas o próprio modelo de
  dados do core protegido já separa `capacity_units` (fixo, só genesis) de
  `remaining_units` (mutável) — uma divergência de `capacity_units` sozinha
  é estruturalmente impossível hoje (confirmado: 0/56 FLORA drifted no
  scan completo). Qualquer outra divergência (ex.: `source_meta.tier`)
  continua rejeitada (teste 10).
- **FISHING**: elegível em princípio, mas sua capacidade nunca lê fonte
  viva nenhuma (fórmula determinística) — imune por construção.

## Recorrência — prova, não suposição

Nada impede que o boot subsequente recompute e ache o MESMO valor
(reconciliado) de novo — nesse caso `expected_hash==persisted_hash` e nem
o patch é acionado (`MATCH` direto). Se uma nova caça acontecer depois,
o próximo boot vê exatamente o mesmo padrão de diff (`{capacity_units}`) e
reconcilia de novo, sem nunca lançar `IntegrityError` — comprovado por dois
ciclos reais de hunt→restart contra uma cópia do mundo real (ver testes).

## Guard de integridade — preservado

Qualquer diferença fora de `{capacity_units}` (fonte, atividade, item de
saída, bloco, schema) continua levantando `IntegrityError` exatamente como
antes — comprovado por teste sintético e por um teste real (mutação
artificial de `tier` em `country_scale_state` pós-migração, no mundo real
copiado, ainda falha).

## Testes

`STAGE17_TOOLS/tests/test_stage17_gathering_capacity_contract.py` (19
testes) + `STAGE17_TOOLS/tests/test_migrate_stage17_gathering_mutable_capacity_v1.py`
(19 testes) = **38 testes, 38 PASS**. Detalhe completo em
[S17_C3R4A_GATHERING_MUTABLE_CAPACITY_TESTS_V0_1_0_DEV.json](S17_C3R4A_GATHERING_MUTABLE_CAPACITY_TESTS_V0_1_0_DEV.json).

Nenhum teste tocou o DB real durante R4A — cópias descartáveis
(`shutil.copyfile`) e fixtures sintéticas apenas. Confirmado por hash do
DB real idêntico antes/depois de toda a suíte rodar.

## Anomalia encontrada e corrigida ainda em R4A/R4B (transparência total)

Durante a PRIMEIRA aplicação real (R4B), a própria ferramenta de migração
reportou `main_db_unchanged: true` e um `post_migration_scan` desatualizado
(ainda mostrando o drift antigo) — **apesar de o COMMIT já ter sido
efetivado com sucesso**. Causa raiz: a verificação pós-commit usava uma
conexão `mode=ro&immutable=1` (que por design nunca consulta um arquivo
`-wal`) imediatamente após o `COMMIT`, antes de qualquer checkpoint —
então via bytes do arquivo principal ainda desatualizados. Uma reauditoria
independente, feita após o processo Python encerrar por completo (o que
disparou um checkpoint automático do SQLite ao fechar a última conexão),
confirmou que os dados reais já estavam corretos o tempo todo — o bug era
só na autoverificação imediata da ferramenta, não uma falha de dado.
Corrigido adicionando `PRAGMA wal_checkpoint(FULL)` logo após o `COMMIT`,
antes de qualquer leitura de verificação. Teste de regressão
`test_38_apply_hash_after_and_post_scan_reflect_the_actual_committed_state`
adicionado e passando. Ver
[S17_C3R4B_GATHERING_MIGRATION_EXECUTION_V0_1_0_DEV.md](S17_C3R4B_GATHERING_MIGRATION_EXECUTION_V0_1_0_DEV.md)
para o traço completo.

## Integridade protegida

`01_RUNTIME`, Stage16A, Stage16B, Master/Living: **zero diff** — apenas
lidos. Nenhum arquivo protegido foi editado nesta rodada.
