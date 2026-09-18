# ANDRÔMEDA — FIRST PLAYABLE GODOT V0.1.25 DEV

Protótipo isométrico com navegação A*, clique híbrido, colisão de fauna e informação contextual por hover.

## Controles

- **Clique esquerdo curto no chão** — vai sozinho até o ponto clicado.
- **Segure clique esquerdo no chão** — após uma janela curta de detecção, passa a acompanhar o cursor; ao soltar, para imediatamente.
- **Clique direito curto no chão** — também vai sozinho até o ponto clicado.
- **SHIFT** — corre durante o movimento.
- **Clique direito em NPC/objeto** — aproxima e interage automaticamente.
- **Clique direito em inimigo** — persegue por navegação e ataca automaticamente; cliques repetidos nunca ignoram o cooldown global de **2 segundos**.
- **Clique direito em fauna pacífica/árvore/rocha** — aproxima e observa.
- **Passe o mouse sobre NPC, animal ou objeto** — mostra uma pequena ficha contextual.
- **T** — acende/apaga a tocha quando possuída.
- **I** — abre/fecha o inventário; ele fica oculto durante o jogo normal.
- **ESC** — cancela ação atual.

## Correções V0.1.7

- Animais usam a mesma malha A* do jogador e não atravessam mais o rio; quando necessário, usam a ponte.
- Fauna continua usando `CharacterBody3D` com cápsula física e colisões reais com obstáculos, Player e NPCs/objetos.
- NPCs/objetos possuem colisão física explícita; o NPC de Varga continua imóvel nesta build, mas não é atravessável.
- Botão direito agora é híbrido: move em chão vazio e executa ação contextual quando há alvo.
- Hover contextual exibe nome/tipo/status de NPCs, animais e objetos relevantes.
- Uma **Tocha da Entrada** foi colocada ao lado da entrada da Masmorra de Vigília.
- Ao coletar uma tocha, ela é equipada e acesa automaticamente; `T` continua alternando a luz.
- Itens coletados deixam de manter hitbox invisível clicável.

## Nota

Esta é uma build DEV visual. O Living continua recebendo envelopes de movimento/interação; o Godot é cliente de apresentação e teste.


# V0.1.8

- Clique esquerdo: movimento; ao clicar diretamente numa entrada/saída de área, caminha até ela e faz a transição automaticamente.
- Clique direito: movimento em chão vazio e interação/combate em alvos.
- Fauna hostil usa repath com throttle e detecção de travamento por progresso real, evitando travamentos fortes.


# V0.1.10

- Interações agora são despachadas de forma diferida, fora do `_physics_process`, evitando mutações físicas/reentrância durante o frame de física.
- Alvo e `object_id` são capturados/validados antes da ação; referências inválidas deixam de produzir chamadas após coleta/transição.
- Debounce curto impede interação duplicada em cliques consecutivos.
- Porta, cadeira, coleta, loja, livros e transições mantêm o contrato anterior.


## Correção V0.1.10

- Corrige erro runtime do Godot 4.7.1 em `Main.gd` durante aproximação/interação: atribuição de `Array` genérico a `Array[float]`.
- `ring_scales` agora é construído explicitamente com `append(float)`, preservando a tipagem.
- Auditoria adicionada para impedir retorno desse padrão em arrays tipados.


# V0.1.11

- Movimento no chão passa a ser **hold-to-move** para os dois botões do mouse: enquanto o botão estiver pressionado, o destino acompanha o cursor; ao soltar, o movimento horizontal é interrompido imediatamente.
- Clique direito contextual continua sendo comando completo para NPC/objeto/inimigo. Entradas/saídas de área continuam sendo transições de movimento por clique.
- Cooldown de ataque de **2,0 s** agora é centralizado em `_perform_attack_on()` e não é zerado ao clicar novamente, cancelar ou trocar o alvo.
- O destino do hold é atualizado por throttle (`0,12 s`) e somente quando o ponto sob o cursor muda o suficiente, evitando reconstruções de rota desnecessárias.


# V0.1.12

- Introduz detecção dual de **clique curto vs. hold** sem atrasar o início do movimento: o caminho é solicitado já no pressionar.
- Clique curto esquerdo/direito em chão mantém a rota após soltar até chegar ao destino.
- Hold é confirmado após `0,18 s`; a partir daí o destino acompanha o cursor e soltar interrompe o movimento imediatamente.
- Clique direito em alvo contextual não entra no modo hold: NPC/objeto/inimigo continua sendo um comando completo de aproximação + interação/combate.
- Clique esquerdo sobre entrada/saída de área continua sendo transição de movimento completa.
- Cooldown global de ataque de 2,0 s da V0.1.11 foi preservado.


# V0.1.13

- Botão direito deixa de usar hold-to-move. Ele funciona apenas por clique: chão vazio = movimento automático; alvo contextual = aproximação + interação/combate.
- Botão esquerdo preserva os dois modos aprovados: clique curto vai sozinho até o ponto; segurar acompanha o cursor e soltar interrompe.
- Inventário deixa de ocupar permanentemente o HUD. `I` alterna um painel dedicado de inventário; fechado por padrão.
- HUD permanente passa a mostrar apenas zona, vida, stamina, moedas, arma, tocha e ação atual.


# V0.1.14 DEV

- Marcador de clique menor e mais sutil.
- Inventário separado em ARMAS, MATERIAIS e OBJETOS.
- Couro obtido de fauna entra em MATERIAIS.
- Botão esquerdo é movimento puro, inclusive sobre objetos/NPCs/fauna/inimigos.
- Ponto ocupado pelo objeto usa aproximação ao ponto navegável mais próximo.
- Botão direito contextual e cooldown global de 2 s permanecem inalterados.


# V0.1.15 DEV

- Esquerdo entra/sai por transições de cenário (entrada/saída de masmorra), mas não interage com objetos comuns.
- Inventário possui seleção clicável de armas.
- Armas possuem dano, alcance, durabilidade e status diferenciados.
- Arco/besta operam à distância com projétil visual e tentativa de manter espaço do inimigo.
- Cooldown global de ataque continua em 2 segundos.
- Perfis de armas específicos deste First Playable são DEV/derivação e não alteram a Master.


# V0.1.16 DEV

- Dano recebido ativa AGGRO imediatamente, inclusive fora do raio de percepção.
- Alvos atingidos por arco/besta recalculam rota e perseguem o atacante.
- Superfície ampliada de 60×60 para 90×80 metros visuais aproximados.
- Navegação superficial ampliada para X -45..45 e Z -45..30.
- População de teste aumentada: hostis, fauna, NPCs e comerciantes.
- Ferreiro Orven vende Espada de Oficina.
- Arqueira Sael vende Arco de Galho Negro.
- Master V2.0.1 permanece READ_ONLY; nomes adicionais deste mapa são conteúdo DEV de teste.


# V0.1.17 DEV

- Arco e besta usam ciclo ATIRAR -> RECUAR -> PARAR -> ATIRAR.
- Não existe disparo durante o recuo.
- Inimigos divididos em FRACO, MÉDIO, FORTE e ALFA.
- Categorias alteram velocidade, dano, vida/durabilidade, ritmo de ataque e escala visual.
- Velúrio Alfa é o teste máximo atual de pressão corpo a corpo.


# V0.1.18 DEV

- Ranged só recua quando o inimigo entra na distância mínima/zona de perigo.
- Longe do inimigo, arco/besta permanecem parados e disparam normalmente.
- Recuo próximo é temporizado em 0.32 s e interrompido mesmo que a rota continue.
- Ciclo próximo: RECUAR -> PARAR -> ATIRAR.
- Inimigos mantêm tiers e velocidades aprovadas na V0.1.17.


# V0.1.19 DEV — regra final de recuo ranged

- Arco/besta não recuam por proximidade.
- Receber dano é o único gatilho de recuo automático.
- O inimigo que causou o dano define a direção oposta do recuo.
- Recuo: 0.32 s; estabilização: 0.18 s.
- Após estabilizar, o personagem volta ao ataque normalmente.


# V0.1.20 DEV — seleção de alvo

- Esquerdo em inimigo: seleciona o inimigo e mantém o comportamento de movimento.
- O alvo selecionado recebe indicador visual persistente.
- HUD mostra o alvo atual.
- Espaço inicia combate contra o alvo selecionado usando a arma equipada.
- Direito continua sendo ataque contextual direto.
- O alvo persiste até morrer/desaparecer/deixar de ser inimigo ou outro inimigo ser selecionado.
- Regra final de recuo ranged da V0.1.19 não foi alterada.


# V0.1.21 DEV — seleção genérica sem movimento

- Esquerdo em chão vazio: mover.
- Esquerdo em inimigo/NPC/animal/árvore/pedra/objeto interativo: selecionar e parar.
- Selecionar nunca cria movimento.
- Seleção persiste quando depois se clica no chão para andar.
- Espaço só ataca inimigo hostil selecionado.
- Direito mantém ação contextual.
- Transição pelo esquerdo permanece como exceção.


# V0.1.22 DEV — E usa o alvo selecionado

- Esquerdo seleciona e para.
- E em alvo não hostil: aproxima e executa automaticamente a ação contextual.
- NPC/objeto interativo: INTERACT.
- Animal passivo/árvore/pedra/hoverable: INSPECT.
- E em inimigo não ataca; usar Espaço ou direito.
- Direito continua contextual direto.


# V0.1.22 DEV FIX1

- Corrige erro de runtime ao alvo selecionado ser removido/freed.
- A seleção é limpa antes de qualquer acesso à referência destruída.
- Nenhuma regra de controle/interação foi alterada.


# V0.1.23 DEV — seleção não interrompe movimento

- Esquerdo no chão: cria/troca destino de movimento.
- Esquerdo em alvo: apenas seleciona.
- Se já estiver andando, selecionar outro alvo preserva caminho e destino.
- Se estiver parado, selecionar mantém o personagem parado.
- E/Espaço/Direito e transições permanecem como nas versões aprovadas.


# V0.1.24 DEV — HP / Stamina / Proteção / Escudo Alfa

- Jogador: barras de HP, Stamina e Proteção.
- Inimigos hostis: barra de HP.
- ALFA: HP + Escudo, com Escudo sempre menor que HP.
- Armas possuem interação diferente com Escudo e HP.
- Um golpe pode reduzir HP e Escudo simultaneamente, mas nunca pelo mesmo valor.


# V0.1.25 DEV — Laboratório

- HUD compacto.
- Barras 2D estáveis de HP; Alfa com HP + Escudo.
- Stamina gasta por ataque conforme arma.
- Lojas com catálogo, atributos e COMPRAR.
- Cosméticos: bônus de HP/Proteção/Stamina.
- Setores separados para tiro, predadores, ranged, one-shot e Alfa.


# V0.1.25 DEV FIX1

- Corrige Parser Error em `Wildlife.gd:258`.
- `_fire_enemy_projectile` agora recebe `Node3D`.
- `start_pos`/`end_pos` usam `Vector3` explícito.
- Nenhuma regra de gameplay foi alterada.


# V0.1.25 DEV FIX2

- Remove os dois warnings de variáveis locais não utilizadas no HUD.
- Nenhuma alteração funcional de gameplay.
