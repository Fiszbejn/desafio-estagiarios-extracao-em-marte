# Pipeline completo das cinco centrais — Design

## Objetivo

Hoje só a Central de Missão está plugada em `centrais/avaliacao.py`. O
avaliador oficial roda a simulação inteira sem que nenhuma central extraia,
transporte, armazene ou pesquise minério — resultado: `faturamento_total = 0`
em toda seed. O objetivo deste trabalho é ligar as cinco centrais de forma
compatível com o contrato do avaliador e maximizar `faturamento_total` real,
medido rodando `avaliador/cli.py`.

## Descoberta que define a arquitetura

`armazenagem/estrategia.py::executar()` já prova que o pipeline completo
funciona: ele mesmo despacha extração, transporte, armazenagem e pesquisa
dentro do seu próprio loop `for _ in range(limite_de_ciclos): ...
cliente.avancar_ciclo()`. Isso gera receita real (ordem de R$300 numa única
extração), mas está travado por parâmetros hardcoded (`MAXIMO_DE_EXTRACOES =
1`, só 2 minerais elegíveis, 1 transportadora fixa, sempre política
`comercial`).

Restrição física: só pode existir **um** lugar chamando
`cliente.avancar_ciclo()`. Se cada central tivesse seu próprio loop, o tempo
do mundo avançaria em duplicidade a cada central plugada. Logo, nenhuma
central pode mais possuir seu próprio loop de simulação.

## Arquitetura

`centrais/avaliacao.py` passa a ser o único dono do loop de ciclos:

```python
def executar_avaliacao(cliente, limite_de_ciclos):
    contexto = criar_contexto()
    desde_ciclo = 0
    for _ in range(limite_de_ciclos):
        if cliente.simulacao_encerrada():
            return
        eventos = cliente.consultar_eventos(desde_ciclo)
        estado = cliente.consultar_estado()
        desde_ciclo = estado["ciclo_atual"] + 1

        passo_extracao(cliente, estado, eventos, contexto.extracao)
        passo_transporte(cliente, estado, eventos, contexto.transporte)
        passo_armazenagem(cliente, estado, eventos, contexto.armazenagem)
        passo_pesquisa(cliente, estado, eventos, contexto.pesquisa)
        passo_missao(cliente, estado, eventos, contexto.missao)

        cliente.avancar_ciclo()
```

Ordem dos passos segue o fluxo físico do minério (extração → transporte →
armazenagem → pesquisa) com missão por último, para reagir no mesmo ciclo a
qualquer `operacao_invalida` gerado pelos passos anteriores.

Cada central expõe uma função de passo pura (sem loop, sem
`avancar_ciclo`), recebendo `cliente`, o `estado` e os `eventos` já
buscados no ciclo, e um dicionário de contexto **privado daquela central**
(estado local entre ciclos: unidades ocupadas, cargas em análise, etc.).
`executar(cliente, limite_de_ciclos)` continua existindo em cada módulo
como wrapper fino só para rodar aquela central sozinha manualmente — ele
cria seu próprio contexto e roda um loop local chamando só o próprio passo
mais `avancar_ciclo`.

Isso muda `missao/orquestrador.py` (extrair `executar_ciclo_de_gestao_de_energia`
como o passo, remover o loop de `executar` para o wrapper manual) e
`armazenagem/estrategia.py` (remover as chamadas a extração/transporte/pesquisa
que hoje vazam pra dentro do arquivo errado — cada uma migra pro arquivo da
central correta).

## Responsabilidade por central

### Extração (`centrais/extracao/extracao.py`)

Reage a `extracao_concluida`/`extracao_interrompida` (chama
`retornar-unidade`). A cada ciclo, para toda mineradora `disponivel` e toda
jazida `disponivel` ainda não esgotada, escolhe o par jazida+mineradora por
valor econômico do mineral (`valor_por_unidade` do catálogo em
`mundo/config/minerais.json`, carregado uma vez):

- minerais de alto valor/raridade (`cristal_marciano_raro`, `gelo_de_agua`,
  `jarosita`) → mineradora `precisa`, modo `cuidadoso`, perfil
  `profunda` (preserva qualidade, a perda por unidade é cara demais pra
  arriscar);
- minerais de baixo valor (`hematita`, `silica_de_alta_pureza`) → mineradora
  `leve`, modo `agressivo`, perfil `superficial` (throughput barato).

Quantidade = capacidade da mineradora, limitada ao
`quantidade_disponivel` da jazida. Só dispara se o saldo de energia da
central cobrir o custo estimado com margem.

### Transporte (`centrais/transporte/transporte_otimizado.py`)

Reage a `extracao_concluida` (carga `EM_JAZIDA`) e a `carga_disponivel`
(liberada pela armazenagem). Usa `GET
/transporte/planejar-transporte?identificador_da_carga=X` para obter rotas
já filtradas por compatibilidade/capacidade — evita reimplementar essa
checagem. Autoriza via Missão (`iniciar_viagem`) e escolhe rota + modo por
raridade do mineral:

- raridade ≥ 0.5 (`jarosita`, `gelo_de_agua`, `cristal_marciano_raro`) →
  menor `multiplicador_degradacao` disponível, modo `rapido` (o fator de
  raridade em trânsito multiplica a degradação; menos ciclos na estrada
  importa mais que economia de energia aqui);
- raridade < 0.5 (`hematita`, `silica_de_alta_pureza`) → menor
  `custo_energia_base`, modo `economico`.

Rastreia localmente quais cargas já têm viagem em andamento pra não
despachar a mesma carga duas vezes.

### Armazenagem (`centrais/armazenagem/estrategia.py`, reescrita)

Passa a ter uma responsabilidade única e real: decidir quando vale a pena
guardar uma carga recém-chegada (`transporte_concluido`) versus deixá-la
seguir direto pra análise. Critério: se a Pesquisa não tem slot livre
(`GET /pesquisa/em-andamento` não vazio), guarda a carga (ela decai 2x mais
rápido `NA_MAO` do que `EM_ARMAZEM`); se a Pesquisa está livre, não guarda —
deixa a Pesquisa puxar direto. Mantém no máximo uma carga por armazém neste
buffer para nunca precisar desempilhar mais de um item (evita o custo de
`retirar_carga` em cascata sobre itens que não são o alvo). Ao ver
`carga_aprovada` de uma carga que está guardada, retira (fica `NA_MAO`,
pronta pra distribuição).

Remove `MAXIMO_DE_EXTRACOES`, `PREFERENCIA_DE_MINERAIS` e toda chamada a
`/extracao/*`, `/transporte/*` e `/pesquisa/iniciar-analise` — esse código
migra para os arquivos das centrais corretas.

### Pesquisa (`centrais/pesquisa/pesquisa_solucao.py`)

Dono da fila de análise (capacidade paralela real = 1). Reage a
`transporte_concluido` (quando a armazenagem decidiu não guardar) e a
`cargas_desempilhadas` (quando a armazenagem retirou uma carga guardada)
chamando `iniciar-analise` assim que há slot livre; mantém fila local
(lista) para cargas que chegaram com o slot ocupado. Tipo de análise e
política de aprovação por valor do mineral:

- minerais raros/valiosos → `forense` (mais correta, custa mais, mas evita
  reprocessamento) + política `estrita`;
- minerais comuns → `rapida` (libera o slot mais rápido) + política
  `comercial`.

Ao ver `carga_aprovada`, autoriza `preparar_distribuicao` e chama o
endpoint assim que a carga estiver `NA_MAO` (direto, ou após
`cargas_desempilhadas` liberar do armazém).

### Missão (`centrais/missao/orquestrador.py`, ajuste)

Mantém a lógica atual de auto-proteção e distribuição por perfil
(`PERFIL_DE_ENERGIA_POR_CENTRAL`), com dois ajustes:

1. Verificação de segurança da própria Missão passa a rodar **todo ciclo**
   (não mais a cada `INTERVALO_DE_CICLOS_ENTRE_VERIFICACOES = 10`), já que
   agora existe atividade econômica real gerando autorizações (`0.2` de
   energia da Missão por autorização) em rajada — o intervalo de 10 ciclos
   deixava de acompanhar esse dreno.
2. Com trabalho real acontecendo, os alvos de energia por central em
   `PERFIL_DE_ENERGIA_POR_CENTRAL` sobem (a extração agora roda continuamente,
   não uma vez só) — ajustar os `alvo` pra sustentar o ritmo real observado
   nos testes com o avaliador, sem esgotar a reserva antes da hora.

## Integração

`centrais/avaliacao.py` implementa o loop único descrito acima, importando
o passo de cada central. Nenhuma central mais recebe `limite_de_ciclos`
diretamente exceto pelo próprio `executar()` (wrapper manual de cada
módulo).

## Validação

Rodar `avaliador/cli.py` com um conjunto de seeds (ex.: 20-30 pra
iteração rápida, depois a faixa completa 100-200 sugerida no
`DOCUMENTACAO_DO_PROJETO.md`) e observar `faturamento_total` médio no
relatório gerado. Iterar nos parâmetros de decisão (perfis de mineral,
limiares de energia) até estabilizar um resultado bom sem estourar
`FALHA_OPERACIONAL` em nenhuma seed.
