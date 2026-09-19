# Workflow 3D — image-to-3D (Trellis2)

Fonte: `00000000-0000-0000-0000-000000001509_workflow.json` (ComfyUI, 66 nodes,
100 links, 12 grupos). Pipeline: imagem 2D → modelo 3D texturizado.
As artes conceituais do EP01 são a matéria-prima de entrada.

## Passo a passo de uso

1. Abrir o JSON no ComfyUI (ou importar no RunComfy).
2. No node **#122 `LoadImage`**, trocar `RunComfy_examples_1509_1.png` pela arte
   2D da peça (ex.: `arte/Kenua_Vaarn.jpg`).
3. No switch **#248 `Switch: Remove background`**: ON para personagem/criatura/prop;
   OFF para peças sem fundo removível (ver ressalva).
4. No node **#322 `Save3DAdvanced`**, renomear a saída por peça
   (ex.: pasta `3d/ep01-kenua` em vez de `3d/RunComfy_1509_lantern`).
5. Rodar a fila; conferir os previews (`PreviewImage` ×7, `Preview3DAdvanced` ×2).
6. Se o modelo sair achatado/esticado, ajustar o FoV no node **#298
   `Pixal3DConditioning`** (atual 49.13). Para variação, mexer nas seeds dos
   KSamplers (12: 43 · 18: 42 · 3: 56 · 23: 42); steps/CFG já calibrados.

## Mapa de nodes (o que mexer)

| # | Node | Valor atual | Papel |
|---|---|---|---|
| 122 | `LoadImage` | `RunComfy_examples_1509_1.png` | **Imagem de entrada** |
| 248 | `Switch: Remove background` | ON (True) | Liga/desliga o BiRefNet |
| 298 | `Pixal3DConditioning` | 49.13 | FoV da câmera virtual |
| 12/18/3/23 | `KSampler` ×4 | seeds 43/42/56/42, steps 12–20, CFG 1–12 | Variação/qualidade |
| 314/315/318 | `ComfySwitchNode` | OFF (False) | Ramificações alternativas (investigar no canvas) |
| 322 | `Save3DAdvanced` | `3d/RunComfy_1509_lantern`, 1024² | **Saída** — renomear por peça |

Saídas de malha: `MeshToFile3D` #247/#282/#285. Pós-malha: remesh, suavização
de normais, decimação, unwrap UV; baking de cor + oclusão de ambiente + normal map.

## Modelos exigidos (verificar no ambiente Comfy)

- `trellis_2_int8_convrot.safetensors` (UNET estrutura/forma)
- `pixal3d_int8_convrot.safetensors` (UNET alternativo)
- `trellis_2_shape_vae_bf16.safetensors` (VAE forma)
- `trellis_2_texture_vae_bf16.safetensors` (VAE textura)
- `dino_v3_L_naf_fp32.safetensors` (CLIP Vision)
- `birefnet.safetensors` (remoção de fundo)
- `moge_2_vitl_normal_fp16.safetensors` (geometria/FoV)

## Ressalva — limite do workflow: objetos, não cenários

O Trellis2 foi desenhado para reconstruir **objetos isolados** (personagem,
criatura, prop) a partir de uma imagem com fundo removível. Cenários inteiros
— Pedreira, Posto de Varga, Sala de Registros, Câmara — tendem a sair
deformados (geometria colapsada, texturas esticadas), porque não há "fundo"
para remover nem volume único para reconstruir.

**Receita por tipo de peça:**
- Personagem/criatura/prop → fundo ON, entrada direta. Caso de uso ideal.
- Cenário → **não usar este workflow para a cena inteira**; usar apenas para
  props isolados recortados da arte (ex.: a carroça tombada, o contrato sobre
  a mesa, a placa de Daren), que depois compõem a cena em outro software.

**Teste piloto:** `Kenua_Vaarn.jpg` (personagem, fundo ON) — se sair íntegro,
o workflow está validado para as peças-tipo do EP01; cenários ficam fora
do piloto.
