# Living Simulation Engine V1.1.0 — Changelog

## Added
- DomainIntegrationHub persistente e idempotente para integração causal entre módulos.
- Economia local, carteira, inventário, vendedores, estoque, compra/venda e preços runtime dinâmicos.
- CombatSystem MAR com vida, dano abstrato, desgaste, cadáver, recursos e reparo em local canônico de manutenção.
- Mobilidade baseada em rotas, trânsito, acesso, fuga/patrulha espaciais e relógio biológico.
- Lei/reputação/facções runtime, profissões, empregos, salários e produtividade econômica.
- IntegratedLivingEngineV11 e SystemHealthMonitor para bootstrap e health gate cruzado.

## Changed
- Demanda econômica passa a resolver destino → território → população.
- Segurança alimentar reage apenas a fluxos FOOD locais.
- Fações usam economia/desemprego locais e diplomacia runtime em seus ticks.
- Bootstrap V1.1 usa seeds contextuais runtime em vez de valores universais.

## Fixed
- Nascimento, morte e migração reconciliam população agregada.
- Entidades mortas deixam o scheduler.
- Testemunhas co-localizadas criam memória automaticamente.
- ECO_FLEE deixa de ser apenas gasto de energia.
- Animais envelhecem e acumulam fome/sede.
- Emprego encerra com morte; ARREARS continua ocupando vínculo; carteiras são garantidas antes do salário.
- Compra/venda transfere o valor monetário completo; comércio remoto físico é bloqueado.
- Relações de facção deixam de ser inertes.
- Equipamento pode ser reparado sem inventar oficina ou preço canônico.

## Governance
- Master V2.0.1 permanece READ_ONLY e sem mutações.
- Valores monetários, saúde, dano, rendimento, salários, leis operacionais e balanceamento são runtime, não cânone.
- IMP-019 requer especificação autoral de compatibilidade reprodutiva.
- IMP-022 permanece AUTHOR_REVIEW; política protegida de recuperação em 7 dias não foi alterada.
- IMP-021 (clima planetário contínuo/doenças) permanece P2 não bloqueante para uma futura expansão.
