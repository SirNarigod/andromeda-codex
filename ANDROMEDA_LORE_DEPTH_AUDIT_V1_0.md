# Auditoria de profundidade de lore — Andrômeda

## Causa raiz (achado real, não suposição)

O lore vive em 3 camadas com densidade muito diferente:

| Camada | Arquivos | Tamanho médio | O que é |
|---|---|---|---|
| `CANON_R2` | 126 | ~3,2 KB | Cânone original, escrito com cuidado autoral |
| `CANON_MASTER_V2` | 26 | ~44,8 KB | Catálogos consolidados grandes (índices, não entradas individuais) |
| `CANON_DERIVADO_ATIVO` | 280 | ~2,7 KB | Conteúdo **gerado durante as sessões deste projeto** pra preencher gameplay |

**A rasura está quase toda em `CANON_DERIVADO_ATIVO`.** Faz sentido: é conteúdo procedural/rápido pra fechar lacunas de gameplay (permitir que `country_scale.py` gere blocos, cidades, agricultura), nunca recebeu a mesma atenção narrativa do cânone original.

## Achados concretos, por categoria (do mais raso ao menos raso)

### 1. Locais (`GEOGRAFIA/*/LOCAIS/`) — 59 arquivos, ~340-460 bytes cada
O pior caso. Exemplo real, **arquivo completo**:
```json
{"record_id":"LOC-001-001","name":"Mercado Central","parent_subregion":"SUB-001-001",
"parent_political_unit":"TER-001","function":"Praça de comércio principal da confederação.",
"notable_link":"Feira Central de Lúminor (SUB-001-001)","settlement_tier":"COMPLEXO"}
```
Isso é **tudo** que existe sobre o Mercado Central de Lúminor. Sem descrição sensorial, sem NPC associado, sem gancho de história, sem conflito, sem o que só um mercado especificamente ANDROMEDIANO teria (o que se vende ali que não existe em nenhum outro lugar? quem controla o preço? já houve um incidente ali?). Os 59 locais em todos os 13+ territórios seguem esse mesmo padrão.

### 2. Subregiões (`GEOGRAFIA/*/SUBREGIOES/`) — 61 arquivos
Um degrau acima dos locais, mas ainda funcionais/mecânicos — servem pra o `country_scale.py` gerar blocos, não pra contar uma história.

### 3. Agricultura (`AGRICULTURA/`) — 9 arquivos, ~780 bytes cada
Puro dado de sistema:
```json
{"agz_id":"AGZ-090","title":"Pastagens Luminais","farming_type":"PASTORAL",
"produces":["leite proteico (CRI-002)","leite denso (CRI-003)","leite claro (CRI-004)"],
"notable_link":"EST-037 Curral e Estábulo; FLO-001 Pastagem Luminal; CRI-002/003/004"}
```
Zero textura — é uma lista de referências cruzadas, não uma zona agrícola com identidade própria.

### 4. Ecologia/Flora (`ECOLOGIA/FLORA/`) — 19 arquivos, ~1,35 KB cada
Melhor que agricultura (tem `summary` + `relations`), mas ainda esquemático — nenhuma planta tem uso cultural, ritual, ou conflito econômico em torno dela.

### 5. Androids / Enclave Sintético (`SOCIEDADES/FACCOES/FAC-090`) — o item que você citou
Este é o **menos raso** dos exemplos acima (tem hipótese de origem, 5 linhagens de chassi, relações, 3 geradores de história) — mas comparado às outras 4 classes jogáveis, falta exatamente o que você provavelmente sentiu faltando:
- **Nenhum indivíduo nomeado.** As outras classes se ancoram em facções com história (Vigília Radicular, Reis Magos); Androids só referencia "8 NPCs" por nome de arquivo, nunca descritos aqui.
- **Nenhuma textura psicológica/filosófica.** O arquivo já levanta a pergunta mais interessante do conceito — "mente transferida" vs "rotina de conduta treinada" — e **não responde nem explora**: uma android com mente transferida é a mesma pessoa que era antes? Tem gente que finge não notar a diferença? Existe preconceito contra androids "baratos" (rotina treinada) vs "legítimos" (mente transferida)?
- **Geradores de história puramente transacionais** (custo de reparo, escolta paga) — nenhum sobre identidade, pertencimento, ou o que significa ser uma consciência num corpo fabricado.
- **Nenhuma tensão social**: outras facções relevantes tem disputas explícitas; Androids só tem "disputa de custo de manutenção".

## Prioridade sugerida (pra não tentar tudo de uma vez)

| Prioridade | Item | Por quê |
|---|---|---|
| **Alta** | Androids/Enclave Sintético | É uma das 5 classes jogáveis — todo jogador que escolher essa classe sente a rasura direto |
| **Alta** | Os 59 Locais | Aparecem toda vez que alguém explora/viaja — maior superfície de contato com o jogador |
| **Média** | Subregiões | Menos visíveis diretamente, mas alimentam os locais |
| **Baixa** | Agricultura/Ecologia | Flavor econômico, baixo contato direto com o jogador |

## Como quero prosseguir

Enriquecer 59 locais + a classe inteira de Androids é um volume grande de escrita autoral — não é código, é decisão criativa (nomes, personalidades, conflitos, tom). Antes de escrever tudo de uma vez, prefiro:
1. Confirmar com você o tom/direção pra Androids (a pergunta filosófica é o coração do conceito — vale a pena decidir isso junto).
2. Fazer 2-3 locais como amostra do nível de profundidade que você quer, você aprova o padrão, e eu aplico nos outros 56.
