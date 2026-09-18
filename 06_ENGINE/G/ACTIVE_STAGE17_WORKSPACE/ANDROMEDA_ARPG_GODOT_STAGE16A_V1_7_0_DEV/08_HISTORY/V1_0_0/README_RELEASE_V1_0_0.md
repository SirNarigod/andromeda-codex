# Andrômeda Códex — Living Simulation Engine V1.0.0

Primeiro release funcional do núcleo de simulação viva.

- A Master V2.0.1 é dependência externa obrigatória e somente leitura.
- O engine suporta timelines privadas por jogador e schema SHARED para evolução futura.
- Offline: apenas rotinas `ROUTINE_SAFE`.
- Estruturas destruídas regeneram após 7 dias do universo; história/memória não é apagada.
- O LLM Gateway controla linguagem e intenção candidata, nunca a verdade/estado do mundo.
- Um provider LLM real deve ser vinculado em deployment; credenciais não são incluídas.
- O Atlas recebe apenas projeções JSON read-only de snapshots backend-only.
