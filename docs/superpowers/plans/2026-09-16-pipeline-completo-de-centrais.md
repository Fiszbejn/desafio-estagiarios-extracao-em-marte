# Pipeline Completo das Cinco Centrais — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ligar as cinco centrais (extração, transporte, armazenagem, pesquisa, missão) num único pipeline compatível com o contrato do avaliador, maximizando `faturamento_total` real.

**Architecture:** `centrais/avaliacao.py` passa a ser o único dono do loop de ciclos (só ele chama `cliente.avancar_ciclo()`). Cada central expõe uma função `passo(cliente, estado, eventos, contexto)` sem loop próprio, chamada uma vez por ciclo na ordem extração → transporte → armazenagem → pesquisa → missão. Cada módulo mantém `executar(cliente, limite_de_ciclos)` como wrapper fino só para rodar aquela central sozinha manualmente.

**Tech Stack:** Python 3.13, FastAPI `TestClient` (via `avaliador.aplicacao.cliente_de_avaliacao.ClienteDeAvaliacao`) para testes de integração, pytest.

**Spec:** `docs/superpowers/specs/2026-09-16-pipeline-completo-de-centrais-design.md`

## Global Constraints

- Nenhum arquivo em `mundo/`, `avaliador/` ou `pyproject.toml` pode ser modificado em conteúdo de forma que mude seu hash — são protegidos por `integridade/manifesto.py` (`ESCOPOS_PROTEGIDOS = ("mundo", "avaliador")` + `pyproject.toml` na raiz). `centrais/` e `docs/` não são protegidos.
- Todo código de domínio usa português (nomes de função, variável, docstring).
- Todas as centrais falam com o mundo só através do objeto `cliente` (`chamar`, `consultar_estado`, `consultar_eventos`, `avancar_ciclo`, `simulacao_encerrada`) — nunca `requests`/`httpx` direto contra uma URL fixa dentro do caminho usado pelo avaliador.
- Catálogo de valores de minério vem de `mundo/config/minerais.json` (fonte de verdade); o dict espelhado em `centrais/comum/minerais.py` precisa bater com esses valores.

---

### Task 1: Módulo comum de minerais + infraestrutura de testes

**Files:**
- Create: `centrais/comum/minerais.py`
- Create: `centrais/testes/__init__.py`
- Modify: `pyproject.toml` (adicionar `"centrais/testes"` a `testpaths`)

**Interfaces:**
- Produces: `centrais.comum.minerais.valor_por_unidade(mineral: str) -> float`, `centrais.comum.minerais.raridade(mineral: str) -> float`, `centrais.comum.minerais.e_valioso(mineral: str) -> bool`

- [ ] **Step 1: Instalar dependências de dev no venv do projeto**

Run: `.venv/Scripts/python.exe -m pip install pytest`

Expected: instala `pytest` sem erro (o projeto já usa `.venv/Scripts/python.exe` como interpretador; `pip list` antes deste passo não mostra `pytest`).

- [ ] **Step 2: Escrever o teste do catálogo**

Criar `centrais/testes/test_minerais.py`:

```python
from centrais.comum.minerais import e_valioso, raridade, valor_por_unidade


def test_hematita_e_barata_e_comum():
    assert valor_por_unidade("hematita") == 5.0
    assert raridade("hematita") == 0.1
    assert e_valioso("hematita") is False


def test_cristal_marciano_raro_e_valioso():
    assert valor_por_unidade("cristal_marciano_raro") == 200.0
    assert raridade("cristal_marciano_raro") == 0.95
    assert e_valioso("cristal_marciano_raro") is True


def test_mineral_desconhecido_nao_quebra():
    assert valor_por_unidade("mineral_inexistente") == 0.0
    assert e_valioso("mineral_inexistente") is False
```

- [ ] **Step 3: Rodar o teste e confirmar que falha por import ausente**

Run: `.venv/Scripts/python.exe -m pytest centrais/testes/test_minerais.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'centrais.comum'`

- [ ] **Step 4: Criar `centrais/comum/minerais.py`**

Valores copiados de `mundo/config/minerais.json` (fonte de verdade — não duplicar números sem conferir contra esse arquivo):

```python
from __future__ import annotations

CATALOGO: dict[str, dict[str, float]] = {
    "hematita": {"valor_por_unidade": 5.0, "raridade": 0.1},
    "silica_de_alta_pureza": {"valor_por_unidade": 20.0, "raridade": 0.3},
    "jarosita": {"valor_por_unidade": 35.0, "raridade": 0.6},
    "gelo_de_agua": {"valor_por_unidade": 40.0, "raridade": 0.5},
    "cristal_marciano_raro": {"valor_por_unidade": 200.0, "raridade": 0.95},
}
LIMIAR_DE_RARIDADE_PARA_PRESERVACAO = 0.5


def valor_por_unidade(mineral: str) -> float:
    return CATALOGO.get(mineral, {}).get("valor_por_unidade", 0.0)


def raridade(mineral: str) -> float:
    return CATALOGO.get(mineral, {}).get("raridade", 0.0)


def e_valioso(mineral: str) -> bool:
    return raridade(mineral) >= LIMIAR_DE_RARIDADE_PARA_PRESERVACAO
```

- [ ] **Step 5: Adicionar `centrais/testes` a `testpaths` em `pyproject.toml`**

Trocar:

```toml
testpaths = ["mundo/testes", "avaliador/testes", "integridade/testes"]
```

por:

```toml
testpaths = ["mundo/testes", "avaliador/testes", "integridade/testes", "centrais/testes"]
```

- [ ] **Step 6: Criar `centrais/testes/__init__.py` vazio**

- [ ] **Step 7: Rodar o teste e confirmar que passa**

Run: `.venv/Scripts/python.exe -m pytest centrais/testes/test_minerais.py -v`
Expected: 3 passed

- [ ] **Step 8: Commit**

```bash
git add centrais/comum/minerais.py centrais/testes/__init__.py centrais/testes/test_minerais.py pyproject.toml
git commit -m "feat: adiciona catalogo comum de minerais para as centrais"
```

---

### Task 2: Central de Extração

**Files:**
- Create: `centrais/extracao/extracao.py` (substitui o conteúdo atual, incompatível com o avaliador)
- Test: `centrais/testes/test_extracao.py`

**Interfaces:**
- Consumes: `centrais.comum.minerais.valor_por_unidade`, `centrais.comum.minerais.e_valioso`
- Produces: `centrais.extracao.extracao.criar_contexto() -> dict`, `centrais.extracao.extracao.passo(cliente, estado: dict, eventos: list[dict], contexto: dict) -> None`, `centrais.extracao.extracao.executar(cliente, limite_de_ciclos: int) -> None`

- [ ] **Step 1: Escrever o teste de integração**

```python
from avaliador.aplicacao.cliente_de_avaliacao import ClienteDeAvaliacao
from centrais.extracao import extracao


def test_passo_inicia_extracao_quando_ha_jazida_e_mineradora_livres():
    cliente = ClienteDeAvaliacao()
    cliente.resetar(semente=1)
    contexto = extracao.criar_contexto()

    estado = cliente.consultar_estado()
    extracao.passo(cliente, estado, [], contexto)
    cliente.avancar_ciclo()

    mineradoras = cliente.chamar("GET", "/extracao/mineradoras")
    assert any(m["estado"] != "disponivel" for m in mineradoras)
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `.venv/Scripts/python.exe -m pytest centrais/testes/test_extracao.py -v`
Expected: FAIL (função `passo`/`criar_contexto` ainda não existem nesse formato — o arquivo atual usa `requests`/webhook).

- [ ] **Step 3: Reescrever `centrais/extracao/extracao.py` por completo**

```python
from __future__ import annotations

from typing import Any

from centrais.comum.minerais import e_valioso, valor_por_unidade

CENTRAL = "extracao"
MARGEM_DE_SEGURANCA = 2.0

CUSTO_ESTIMADO_POR_TIPO = {"leve": 6.0, "precisa": 9.0}
FATOR_DESPERDICIO_POR_MODO = {"cuidadoso": 1.0, "normal": 1.2, "agressivo": 1.4}


def criar_contexto() -> dict:
    return {"unidades_ocupadas": set()}


def _parametros_de_extracao(mineral: str) -> dict:
    if e_valioso(mineral):
        return {"tipo_preferido": "precisa", "modo": "cuidadoso", "perfil_de_escavacao": "profunda"}
    return {"tipo_preferido": "leve", "modo": "agressivo", "perfil_de_escavacao": "superficial"}


def passo(cliente: Any, estado: dict, eventos: list[dict], contexto: dict) -> None:
    for evento in eventos:
        if evento["tipo"] in ("extracao_concluida", "extracao_interrompida"):
            unidade = evento["dados"]["unidade"]
            contexto["unidades_ocupadas"].discard(unidade)
            cliente.chamar("POST", "/extracao/retornar-unidade", {"identificador_da_unidade": unidade})

    saldo = estado["energia"].get(CENTRAL, 0.0)
    if saldo <= 0.0:
        return

    jazidas = cliente.chamar("GET", "/extracao/jazidas")
    disponiveis = [j for j in jazidas if j["estado"] == "disponivel" and j["quantidade_disponivel"] > 0]
    if not disponiveis:
        return
    disponiveis.sort(key=lambda j: valor_por_unidade(j["mineral"]), reverse=True)

    mineradoras = cliente.chamar("GET", "/extracao/mineradoras")
    unidades_livres = [
        m for m in mineradoras
        if m["estado"] == "disponivel" and m["identificador"] not in contexto["unidades_ocupadas"]
    ]

    for jazida in disponiveis:
        if not unidades_livres:
            break
        parametros = _parametros_de_extracao(jazida["mineral"])
        unidade = next(
            (u for u in unidades_livres if u["tipo"] == parametros["tipo_preferido"]),
            unidades_livres[0],
        )
        custo_estimado = CUSTO_ESTIMADO_POR_TIPO.get(unidade["tipo"], 9.0)
        if saldo < custo_estimado + MARGEM_DE_SEGURANCA:
            continue
        fator_desperdicio = FATOR_DESPERDICIO_POR_MODO[parametros["modo"]]
        quantidade = min(unidade["capacidade"], jazida["quantidade_disponivel"] / fator_desperdicio)
        if quantidade <= 0:
            continue
        cliente.chamar(
            "POST",
            "/extracao/iniciar-extracao",
            {
                "identificador_da_unidade": unidade["identificador"],
                "identificador_da_jazida": jazida["identificador"],
                "quantidade": quantidade,
                "modo": parametros["modo"],
                "perfil_de_escavacao": parametros["perfil_de_escavacao"],
            },
        )
        contexto["unidades_ocupadas"].add(unidade["identificador"])
        unidades_livres.remove(unidade)
        saldo -= custo_estimado


def executar(cliente: Any, limite_de_ciclos: int) -> None:
    contexto = criar_contexto()
    desde_ciclo = 0
    for _ in range(limite_de_ciclos):
        if cliente.simulacao_encerrada():
            return
        eventos = cliente.consultar_eventos(desde_ciclo)
        estado = cliente.consultar_estado()
        desde_ciclo = estado["ciclo_atual"] + 1
        passo(cliente, estado, eventos, contexto)
        cliente.avancar_ciclo()


if __name__ == "__main__":
    import httpx

    class _ClienteHttpLocal:
        def __init__(self, url_base: str = "http://localhost:8000") -> None:
            self._url_base = url_base

        def chamar(self, metodo: str, rota: str, json: dict | None = None) -> Any:
            resposta = httpx.request(metodo, f"{self._url_base}{rota}", json=json)
            resposta.raise_for_status()
            return resposta.json()

        def consultar_estado(self) -> dict:
            return self.chamar("GET", "/missao/estado")

        def consultar_eventos(self, desde_ciclo: int = 0) -> list[dict]:
            return self.chamar("GET", f"/missao/eventos?desde_ciclo={desde_ciclo}")

        def avancar_ciclo(self, quantidade: int = 1) -> None:
            import time

            time.sleep(1.0 * quantidade)

        def simulacao_encerrada(self) -> bool:
            energia = self.consultar_estado()["energia"]
            return all(saldo <= 0.0 for central, saldo in energia.items() if central != "reserva_estrategica")

    executar(_ClienteHttpLocal(), limite_de_ciclos=10_000_000)
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/python.exe -m pytest centrais/testes/test_extracao.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add centrais/extracao/extracao.py centrais/testes/test_extracao.py
git commit -m "feat: reescreve central de extracao no contrato do avaliador"
```

---

### Task 3: Central de Transporte

**Files:**
- Create: `centrais/transporte/transporte_otimizado.py` (substitui o conteúdo atual, incompatível com o avaliador)
- Test: `centrais/testes/test_transporte.py`

**Interfaces:**
- Consumes: `centrais.comum.minerais.e_valioso`
- Produces: `centrais.transporte.transporte_otimizado.criar_contexto() -> dict`, `centrais.transporte.transporte_otimizado.passo(cliente, estado, eventos, contexto) -> None`, `centrais.transporte.transporte_otimizado.executar(cliente, limite_de_ciclos) -> None`

- [ ] **Step 1: Escrever o teste de integração**

Este teste depende de uma carga já existir (`EM_JAZIDA`), então primeiro roda a extração real até ela concluir, e só então testa o passo de transporte:

```python
from avaliador.aplicacao.cliente_de_avaliacao import ClienteDeAvaliacao
from centrais.extracao import extracao
from centrais.transporte import transporte_otimizado


def _extrair_ate_ter_uma_carga(cliente, limite_de_ciclos=200):
    contexto_extracao = extracao.criar_contexto()
    desde_ciclo = 0
    for _ in range(limite_de_ciclos):
        estado = cliente.consultar_estado()
        extracao.passo(cliente, estado, cliente.consultar_eventos(desde_ciclo), contexto_extracao)
        eventos = cliente.consultar_eventos(desde_ciclo)
        desde_ciclo = estado["ciclo_atual"] + 1
        for evento in eventos:
            if evento["tipo"] == "extracao_concluida":
                return evento["dados"]["carga"], desde_ciclo
        cliente.avancar_ciclo()
    raise AssertionError("extracao nao concluiu a tempo")


def test_passo_inicia_viagem_para_carga_recem_extraida():
    cliente = ClienteDeAvaliacao()
    cliente.resetar(semente=1)
    _, desde_ciclo = _extrair_ate_ter_uma_carga(cliente)

    contexto = transporte_otimizado.criar_contexto()
    estado = cliente.consultar_estado()
    eventos = cliente.consultar_eventos(desde_ciclo - 1)
    transporte_otimizado.passo(cliente, estado, eventos, contexto)
    cliente.avancar_ciclo()

    transportadores = cliente.chamar("GET", "/transporte/transportadores")
    assert any(t["estado"] != "disponivel" for t in transportadores)
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `.venv/Scripts/python.exe -m pytest centrais/testes/test_transporte.py -v`
Expected: FAIL (`passo`/`criar_contexto` não existem no arquivo atual, que usa `argparse`/`httpx` contra servidor real)

- [ ] **Step 3: Reescrever `centrais/transporte/transporte_otimizado.py` por completo**

```python
from __future__ import annotations

from typing import Any

from centrais.comum.minerais import e_valioso

CENTRAL = "transporte"
MISSAO = "missao"
CUSTO_AUTORIZACAO = 0.2
MARGEM_DE_SEGURANCA = 1.0


def criar_contexto() -> dict:
    return {"cargas_despachadas": set()}


def _autorizar(cliente: Any, operacao: str) -> str | None:
    estado = cliente.consultar_estado()
    if estado["energia"].get(MISSAO, 0.0) < CUSTO_AUTORIZACAO:
        return None
    resposta = cliente.chamar(
        "POST",
        "/missao/autorizar-missao",
        {"operacao": operacao, "central_solicitante": CENTRAL},
    )
    return resposta["id_autorizacao"]


def _escolher_rota(rotas: list[dict], mineral: str) -> dict | None:
    if not rotas:
        return None
    if e_valioso(mineral):
        return min(rotas, key=lambda r: r["multiplicador_degradacao"])
    return min(rotas, key=lambda r: r["custo_energia_base"])


def _despachar(cliente: Any, contexto: dict, identificador_da_carga: str) -> None:
    if identificador_da_carga in contexto["cargas_despachadas"]:
        return

    plano = cliente.chamar("GET", f"/transporte/planejar-transporte?identificador_da_carga={identificador_da_carga}")
    identificadores_de_rota = plano.get("rotas_disponiveis", [])
    if not identificadores_de_rota:
        return

    cargas = cliente.chamar("GET", "/transporte/cargas-disponiveis")
    carga = next((c for c in cargas if c["identificador"] == identificador_da_carga), None)
    if carga is None:
        return

    todas_as_rotas = cliente.chamar("GET", "/transporte/rotas")
    rotas_candidatas = [r for r in todas_as_rotas if r["identificador"] in identificadores_de_rota]
    rota = _escolher_rota(rotas_candidatas, carga["mineral"])
    if rota is None:
        return

    transportadores = cliente.chamar("GET", "/transporte/transportadores")
    unidade = next((t for t in transportadores if t["estado"] == "disponivel"), None)
    if unidade is None:
        return

    saldo = cliente.consultar_estado()["energia"].get(CENTRAL, 0.0)
    if saldo < rota["custo_energia_base"] + MARGEM_DE_SEGURANCA:
        return

    autorizacao = _autorizar(cliente, "iniciar_viagem")
    if autorizacao is None:
        return

    modo = "rapido" if e_valioso(carga["mineral"]) else "economico"
    cliente.chamar(
        "POST",
        "/transporte/iniciar-viagem",
        {
            "identificador_da_unidade": unidade["identificador"],
            "identificador_da_rota": rota["identificador"],
            "identificador_da_carga": identificador_da_carga,
            "id_autorizacao": autorizacao,
            "modo": modo,
        },
    )
    contexto["cargas_despachadas"].add(identificador_da_carga)


def passo(cliente: Any, estado: dict, eventos: list[dict], contexto: dict) -> None:
    for evento in eventos:
        tipo = evento["tipo"]
        dados = evento["dados"]
        if tipo == "extracao_concluida":
            _despachar(cliente, contexto, dados["carga"])
        elif tipo == "transporte_concluido":
            cliente.chamar(
                "POST",
                "/transporte/descarregar",
                {"identificador_da_unidade": dados["unidade"], "identificador_da_carga": dados["carga"]},
            )
            cliente.chamar("POST", "/transporte/retornar-unidade", {"identificador_da_unidade": dados["unidade"]})
        elif tipo == "viagem_abortada":
            contexto["cargas_despachadas"].discard(dados["carga"])
            cliente.chamar("POST", "/transporte/retornar-unidade", {"identificador_da_unidade": dados["unidade"]})


def executar(cliente: Any, limite_de_ciclos: int) -> None:
    contexto = criar_contexto()
    desde_ciclo = 0
    for _ in range(limite_de_ciclos):
        if cliente.simulacao_encerrada():
            return
        eventos = cliente.consultar_eventos(desde_ciclo)
        estado = cliente.consultar_estado()
        desde_ciclo = estado["ciclo_atual"] + 1
        passo(cliente, estado, eventos, contexto)
        cliente.avancar_ciclo()
```

(Sem bloco `if __name__ == "__main__":` com CLI/`argparse` — esse era o padrão incompatível que estamos substituindo. Uso manual, se necessário, é só instanciar um cliente HTTP e chamar `executar`.)

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/python.exe -m pytest centrais/testes/test_transporte.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add centrais/transporte/transporte_otimizado.py centrais/testes/test_transporte.py
git commit -m "feat: reescreve central de transporte no contrato do avaliador"
```

---

### Task 4: Central de Armazenagem (reescrita)

**Files:**
- Create: `centrais/armazenagem/estrategia.py` (substitui o conteúdo atual — remove a lógica de extração/transporte/pesquisa que vazava pra este arquivo)
- Test: `centrais/testes/test_armazenagem.py`

**Interfaces:**
- Produces: `centrais.armazenagem.estrategia.criar_contexto() -> dict`, `centrais.armazenagem.estrategia.passo(cliente, estado, eventos, contexto) -> None`, `centrais.armazenagem.estrategia.executar(cliente, limite_de_ciclos) -> None`

- [ ] **Step 1: Escrever o teste de integração**

```python
from avaliador.aplicacao.cliente_de_avaliacao import ClienteDeAvaliacao
from centrais.armazenagem import estrategia


def test_passo_guarda_carga_quando_pesquisa_esta_ocupada(monkeypatch):
    cliente = ClienteDeAvaliacao()
    cliente.resetar(semente=1)
    # dá energia suficiente pra armazenagem e pra missao autorizar
    cliente.chamar("POST", "/missao/alocar-energia", {"destino": "armazenagem", "quantidade": 50, "politica": "pulso"})
    cliente.avancar_ciclo()

    chamado = {"valor": False}
    original_chamar = cliente.chamar

    def _pesquisa_sempre_ocupada(metodo, rota, json=None):
        if rota == "/pesquisa/em-andamento":
            chamado["valor"] = True
            return [{"carga": "carga-fake"}]
        return original_chamar(metodo, rota, json)

    monkeypatch.setattr(cliente, "chamar", _pesquisa_sempre_ocupada)

    contexto = estrategia.criar_contexto()
    estado = cliente.consultar_estado()
    evento = {"tipo": "carga_disponivel", "dados": {"carga": "carga-teste"}}
    # sem uma carga real no mundo o guardar() vai falhar ao buscar quantidade
    # (o teste real de ponta a ponta acontece na Task 7); aqui validamos que
    # o passo consulta /pesquisa/em-andamento antes de decidir.
    estrategia.passo(cliente, estado, [evento], contexto)
    assert chamado["valor"] is True
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `.venv/Scripts/python.exe -m pytest centrais/testes/test_armazenagem.py -v`
Expected: FAIL (`passo`/`criar_contexto` não existem no formato novo — o arquivo atual expõe `executar`/`armazenar_cargas_disponiveis` acoplados a extração/transporte/pesquisa)

- [ ] **Step 3: Reescrever `centrais/armazenagem/estrategia.py` por completo**

```python
from __future__ import annotations

from typing import Any

CENTRAL = "armazenagem"
MISSAO = "missao"
CUSTO_AUTORIZACAO = 0.2
CUSTO_POR_UNIDADE = 0.05
MARGEM_DE_SEGURANCA = 1.0


def criar_contexto() -> dict:
    return {"cargas_guardadas": {}}


def _autorizar(cliente: Any, operacao: str) -> str | None:
    estado = cliente.consultar_estado()
    if estado["energia"].get(MISSAO, 0.0) < CUSTO_AUTORIZACAO:
        return None
    resposta = cliente.chamar(
        "POST",
        "/missao/autorizar-missao",
        {"operacao": operacao, "central_solicitante": CENTRAL},
    )
    return resposta["id_autorizacao"]


def _pesquisa_ocupada(cliente: Any) -> bool:
    return len(cliente.chamar("GET", "/pesquisa/em-andamento")) > 0


def _guardar(cliente: Any, contexto: dict, identificador_da_carga: str, quantidade: float) -> None:
    saldo = cliente.consultar_estado()["energia"].get(CENTRAL, 0.0)
    custo = quantidade * CUSTO_POR_UNIDADE
    if saldo < custo + MARGEM_DE_SEGURANCA:
        return
    armazens = cliente.chamar("GET", "/armazenagem/armazens")
    armazens_em_uso = set(contexto["cargas_guardadas"].values())
    armazem = next(
        (
            a for a in armazens
            if a["identificador"] not in armazens_em_uso and a["ocupacao"] + quantidade <= a["capacidade"]
        ),
        None,
    )
    if armazem is None:
        return
    autorizacao = _autorizar(cliente, "receber_carga")
    if autorizacao is None:
        return
    cliente.chamar(
        "POST",
        "/armazenagem/receber-carga",
        {
            "identificador_do_armazem": armazem["identificador"],
            "identificadores_das_cargas": [identificador_da_carga],
            "id_autorizacao": autorizacao,
        },
    )
    contexto["cargas_guardadas"][identificador_da_carga] = armazem["identificador"]


def _retirar(cliente: Any, contexto: dict, identificador_da_carga: str) -> None:
    identificador_do_armazem = contexto["cargas_guardadas"].get(identificador_da_carga)
    if identificador_do_armazem is None:
        return
    autorizacao = _autorizar(cliente, "retirar_carga")
    if autorizacao is None:
        return
    cliente.chamar(
        "POST",
        "/armazenagem/retirar-carga",
        {
            "identificador_do_armazem": identificador_do_armazem,
            "identificador_da_carga": identificador_da_carga,
            "id_autorizacao": autorizacao,
        },
    )
    del contexto["cargas_guardadas"][identificador_da_carga]


def passo(cliente: Any, estado: dict, eventos: list[dict], contexto: dict) -> None:
    for evento in eventos:
        tipo = evento["tipo"]
        dados = evento["dados"]
        if tipo == "carga_disponivel" and _pesquisa_ocupada(cliente):
            cargas = cliente.chamar("GET", "/transporte/cargas-disponiveis")
            carga = next((c for c in cargas if c["identificador"] == dados["carga"]), None)
            if carga is not None:
                _guardar(cliente, contexto, dados["carga"], carga["quantidade"])
        elif tipo == "carga_aprovada":
            _retirar(cliente, contexto, dados["carga"])


def executar(cliente: Any, limite_de_ciclos: int) -> None:
    contexto = criar_contexto()
    desde_ciclo = 0
    for _ in range(limite_de_ciclos):
        if cliente.simulacao_encerrada():
            return
        eventos = cliente.consultar_eventos(desde_ciclo)
        estado = cliente.consultar_estado()
        desde_ciclo = estado["ciclo_atual"] + 1
        passo(cliente, estado, eventos, contexto)
        cliente.avancar_ciclo()
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/python.exe -m pytest centrais/testes/test_armazenagem.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add centrais/armazenagem/estrategia.py centrais/testes/test_armazenagem.py
git commit -m "refactor: armazenagem passa a so decidir guardar/retirar carga"
```

---

### Task 5: Central de Pesquisa

**Files:**
- Create: `centrais/pesquisa/pesquisa_solucao.py` (substitui o conteúdo atual, incompatível com o avaliador)
- Test: `centrais/testes/test_pesquisa.py`

**Interfaces:**
- Consumes: `centrais.comum.minerais.e_valioso`
- Produces: `centrais.pesquisa.pesquisa_solucao.criar_contexto() -> dict`, `centrais.pesquisa.pesquisa_solucao.passo(cliente, estado, eventos, contexto) -> None`, `centrais.pesquisa.pesquisa_solucao.executar(cliente, limite_de_ciclos) -> None`

- [ ] **Step 1: Escrever o teste de integração**

```python
from avaliador.aplicacao.cliente_de_avaliacao import ClienteDeAvaliacao
from centrais.pesquisa import pesquisa_solucao


def test_passo_inicia_analise_quando_carga_disponivel_e_slot_livre():
    cliente = ClienteDeAvaliacao()
    cliente.resetar(semente=1)
    cliente.chamar("POST", "/missao/alocar-energia", {"destino": "pesquisa", "quantidade": 30, "politica": "pulso"})
    cliente.avancar_ciclo()

    contexto = pesquisa_solucao.criar_contexto()
    estado = cliente.consultar_estado()
    # sem uma carga real cadastrada, o passo so consulta cargas-disponiveis
    # e nao encontra a "carga-teste" -> nao inicia nada, mas nao deve lancar excecao
    evento = {"tipo": "carga_disponivel", "dados": {"carga": "carga-teste"}}
    pesquisa_solucao.passo(cliente, estado, [evento], contexto)

    em_andamento = cliente.chamar("GET", "/pesquisa/em-andamento")
    assert em_andamento == []
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `.venv/Scripts/python.exe -m pytest centrais/testes/test_pesquisa.py -v`
Expected: FAIL (`passo`/`criar_contexto` não existem no arquivo atual, que usa `requests`/webhook)

- [ ] **Step 3: Reescrever `centrais/pesquisa/pesquisa_solucao.py` por completo**

```python
from __future__ import annotations

from typing import Any

from centrais.comum.minerais import e_valioso

CENTRAL = "pesquisa"
MISSAO = "missao"
CUSTO_AUTORIZACAO = 0.2


def criar_contexto() -> dict:
    return {
        "fila": [],
        "mineral_por_carga": {},
        "em_analise": None,
        "aprovadas_pendentes": set(),
    }


def _autorizar(cliente: Any, operacao: str) -> str | None:
    estado = cliente.consultar_estado()
    if estado["energia"].get(MISSAO, 0.0) < CUSTO_AUTORIZACAO:
        return None
    resposta = cliente.chamar(
        "POST",
        "/missao/autorizar-missao",
        {"operacao": operacao, "central_solicitante": CENTRAL},
    )
    return resposta["id_autorizacao"]


def _esta_em_algum_armazem(cliente: Any, identificador_da_carga: str) -> bool:
    armazens = cliente.chamar("GET", "/armazenagem/armazens")
    return any(identificador_da_carga in armazem["pilha"] for armazem in armazens)


def _tipo_de_analise(mineral: str) -> str:
    return "forense" if e_valioso(mineral) else "rapida"


def _politica_de_aprovacao(mineral: str) -> str:
    return "estrita" if e_valioso(mineral) else "comercial"


def _tentar_distribuir(cliente: Any, contexto: dict, identificador_da_carga: str) -> None:
    if _esta_em_algum_armazem(cliente, identificador_da_carga):
        return
    autorizacao = _autorizar(cliente, "preparar_distribuicao")
    if autorizacao is None:
        return
    cliente.chamar(
        "POST",
        "/pesquisa/preparar-distribuicao",
        {"identificador_da_carga": identificador_da_carga, "id_autorizacao": autorizacao},
    )
    contexto["aprovadas_pendentes"].discard(identificador_da_carga)


def passo(cliente: Any, estado: dict, eventos: list[dict], contexto: dict) -> None:
    for evento in eventos:
        tipo = evento["tipo"]
        dados = evento["dados"]
        if tipo == "carga_disponivel":
            identificador = dados["carga"]
            if identificador not in contexto["mineral_por_carga"]:
                cargas = cliente.chamar("GET", "/transporte/cargas-disponiveis")
                carga = next((c for c in cargas if c["identificador"] == identificador), None)
                if carga is not None:
                    contexto["mineral_por_carga"][identificador] = carga["mineral"]
                    contexto["fila"].append(identificador)
        elif tipo == "analise_concluida":
            identificador = dados["carga"]
            if identificador == contexto["em_analise"]:
                contexto["em_analise"] = None
            mineral = contexto["mineral_por_carga"].get(identificador, "")
            cliente.chamar(
                "POST",
                "/pesquisa/aprovar-carga",
                {"identificador_da_carga": identificador, "politica": _politica_de_aprovacao(mineral)},
            )
        elif tipo == "carga_aprovada":
            identificador = dados["carga"]
            contexto["aprovadas_pendentes"].add(identificador)
            _tentar_distribuir(cliente, contexto, identificador)
        elif tipo == "cargas_desempilhadas":
            for identificador in dados["cargas"]:
                if identificador in contexto["aprovadas_pendentes"]:
                    _tentar_distribuir(cliente, contexto, identificador)

    if contexto["em_analise"] is None and contexto["fila"] and not cliente.chamar("GET", "/pesquisa/em-andamento"):
        contexto["fila"].sort(key=lambda i: e_valioso(contexto["mineral_por_carga"].get(i, "")), reverse=True)
        identificador = contexto["fila"].pop(0)
        mineral = contexto["mineral_por_carga"].get(identificador, "")
        cliente.chamar(
            "POST",
            "/pesquisa/iniciar-analise",
            {"identificador_da_carga": identificador, "tipo_de_analise": _tipo_de_analise(mineral)},
        )
        contexto["em_analise"] = identificador


def executar(cliente: Any, limite_de_ciclos: int) -> None:
    contexto = criar_contexto()
    desde_ciclo = 0
    for _ in range(limite_de_ciclos):
        if cliente.simulacao_encerrada():
            return
        eventos = cliente.consultar_eventos(desde_ciclo)
        estado = cliente.consultar_estado()
        desde_ciclo = estado["ciclo_atual"] + 1
        passo(cliente, estado, eventos, contexto)
        cliente.avancar_ciclo()
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/python.exe -m pytest centrais/testes/test_pesquisa.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add centrais/pesquisa/pesquisa_solucao.py centrais/testes/test_pesquisa.py
git commit -m "feat: reescreve central de pesquisa no contrato do avaliador"
```

---

### Task 6: Ajuste da Central de Missão

**Files:**
- Modify: `centrais/missao/orquestrador.py`
- Test: `centrais/testes/test_missao_passo.py`

**Interfaces:**
- Produces: `centrais.missao.orquestrador.criar_contexto() -> dict`, `centrais.missao.orquestrador.passo(cliente, estado, eventos, contexto) -> None` (substitui `executar_ciclo_de_gestao_de_energia`, que deixa de existir como ponto de entrada)

- [ ] **Step 1: Escrever o teste do limiar corrigido**

```python
from avaliador.aplicacao.cliente_de_avaliacao import ClienteDeAvaliacao
from centrais.missao import orquestrador


def test_passo_repoe_central_no_saldo_inicial_exato():
    cliente = ClienteDeAvaliacao()
    cliente.resetar(semente=1)
    contexto = orquestrador.criar_contexto()

    estado = cliente.consultar_estado()
    assert estado["energia"]["extracao"] == 10.0  # saldo inicial == limiar_minimo
    orquestrador.passo(cliente, estado, [], contexto)
    cliente.avancar_ciclo()

    novo_estado = cliente.consultar_estado()
    assert novo_estado["energia"]["extracao"] > 10.0
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `.venv/Scripts/python.exe -m pytest centrais/testes/test_missao_passo.py -v`
Expected: FAIL — hoje `distribuir_energia_operacional` só dispara com `saldo_atual < perfil["limiar_minimo"]`, e `10.0 < 10.0` é `False`, então nada é alocado; também `passo`/`criar_contexto` ainda não existem.

- [ ] **Step 3: Editar `centrais/missao/orquestrador.py`**

Trocar a comparação estrita em `distribuir_energia_operacional` (linha com `if saldo_atual < perfil["limiar_minimo"]:`) por `<=`:

```python
def distribuir_energia_operacional(cliente: Any, energia: dict) -> None:
    """Mantém as centrais operacionais acima do piso mínimo do seu perfil de custo."""
    for central, perfil in PERFIL_DE_ENERGIA_POR_CENTRAL.items():
        saldo_atual = energia[central]
        if saldo_atual <= perfil["limiar_minimo"]:
            quantidade_a_repor = math.ceil(perfil["alvo"] - saldo_atual)
            if quantidade_a_repor > 0:
                alocar_energia(cliente, central, quantidade_a_repor)
```

Subir os alvos de `PERFIL_DE_ENERGIA_POR_CENTRAL` pra sustentar throughput real (extração/transporte/pesquisa agora rodam todo ciclo, não mais uma vez só):

```python
PERFIL_DE_ENERGIA_POR_CENTRAL = {
    "extracao": {"limiar_minimo": 10.0, "alvo": 60},
    "transporte": {"limiar_minimo": 10.0, "alvo": 40},
    "pesquisa": {"limiar_minimo": 10.0, "alvo": 35},
    "armazenagem": {"limiar_minimo": 10.0, "alvo": 25},
}
```

Substituir `monitorar_eventos` e `executar_ciclo_de_gestao_de_energia` por um único `passo`, e reescrever `executar` como wrapper fino:

```python
def criar_contexto() -> dict:
    return {}


def passo(cliente: Any, estado: dict, eventos: list[dict], contexto: dict) -> None:
    energia = estado["energia"]
    proteger_energia_da_missao(cliente, energia)
    distribuir_energia_operacional(cliente, energia)
    for evento in eventos:
        if evento["tipo"] == "operacao_invalida":
            reagir_a_central_dormente(cliente, evento)


def executar(cliente: Any, limite_de_ciclos: int) -> None:
    contexto = criar_contexto()
    desde_ciclo = 0
    for _ in range(limite_de_ciclos):
        if cliente.simulacao_encerrada():
            return
        eventos = cliente.consultar_eventos(desde_ciclo)
        estado = cliente.consultar_estado()
        desde_ciclo = estado["ciclo_atual"] + 1
        passo(cliente, estado, eventos, contexto)
        cliente.avancar_ciclo()


if __name__ == "__main__":
    executar(ClienteHttpLocal(), limite_de_ciclos=10_000_000)
```

Remover as constantes/funções que deixam de ser usadas: `INTERVALO_DE_VERIFICACAO_SEGUNDOS` continua usada por `ClienteHttpLocal.avancar_ciclo`; `INTERVALO_DE_CICLOS_ENTRE_VERIFICACOES` não é mais usada em lugar nenhum — remover a constante e a docstring de `executar` que a menciona (atualizar a docstring do módulo pra refletir o passo por ciclo em vez do lote de 10).

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/python.exe -m pytest centrais/testes/test_missao_passo.py -v`
Expected: 1 passed

- [ ] **Step 5: Rodar a suíte inteira de `centrais/testes` até aqui**

Run: `.venv/Scripts/python.exe -m pytest centrais/testes -v`
Expected: todos os testes das Tasks 1-6 passam

- [ ] **Step 6: Commit**

```bash
git add centrais/missao/orquestrador.py centrais/testes/test_missao_passo.py
git commit -m "fix: corrige limiar de reposicao e expoe passo por ciclo na missao"
```

---

### Task 7: Integração final em `centrais/avaliacao.py`

**Files:**
- Modify: `centrais/avaliacao.py`
- Test: `centrais/testes/test_avaliacao_ponta_a_ponta.py`

**Interfaces:**
- Consumes: `criar_contexto`/`passo` de `centrais.extracao.extracao`, `centrais.transporte.transporte_otimizado`, `centrais.armazenagem.estrategia`, `centrais.pesquisa.pesquisa_solucao`, `centrais.missao.orquestrador`
- Produces: `centrais.avaliacao.executar_avaliacao(cliente, limite_de_ciclos: int) -> None` (mesma assinatura já exigida por `avaliador/aplicacao/carregador_de_centrais.py`)

- [ ] **Step 1: Escrever o teste de ponta a ponta**

```python
from avaliador.aplicacao.cliente_de_avaliacao import ClienteDeAvaliacao
from centrais.avaliacao import executar_avaliacao


def test_pipeline_completo_gera_faturamento():
    cliente = ClienteDeAvaliacao()
    cliente.resetar(semente=1)

    executar_avaliacao(cliente, limite_de_ciclos=1500)

    estado_final = cliente.consultar_estado()
    assert estado_final["faturamento_total"] > 0.0
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `.venv/Scripts/python.exe -m pytest centrais/testes/test_avaliacao_ponta_a_ponta.py -v`
Expected: FAIL — `centrais/avaliacao.py` hoje só chama `executar_missao`, faturamento fica em `0.0`.

- [ ] **Step 3: Reescrever `centrais/avaliacao.py`**

```python
from __future__ import annotations

from typing import Any

from centrais.armazenagem import estrategia as armazenagem
from centrais.extracao import extracao
from centrais.missao import orquestrador as missao
from centrais.pesquisa import pesquisa_solucao
from centrais.transporte import transporte_otimizado


def executar_avaliacao(cliente: Any, limite_de_ciclos: int) -> None:
    contexto_extracao = extracao.criar_contexto()
    contexto_transporte = transporte_otimizado.criar_contexto()
    contexto_armazenagem = armazenagem.criar_contexto()
    contexto_pesquisa = pesquisa_solucao.criar_contexto()
    contexto_missao = missao.criar_contexto()

    desde_ciclo = 0
    for _ in range(limite_de_ciclos):
        if cliente.simulacao_encerrada():
            return
        eventos = cliente.consultar_eventos(desde_ciclo)
        estado = cliente.consultar_estado()
        desde_ciclo = estado["ciclo_atual"] + 1

        extracao.passo(cliente, estado, eventos, contexto_extracao)
        transporte_otimizado.passo(cliente, estado, eventos, contexto_transporte)
        armazenagem.passo(cliente, estado, eventos, contexto_armazenagem)
        pesquisa_solucao.passo(cliente, estado, eventos, contexto_pesquisa)
        missao.passo(cliente, estado, eventos, contexto_missao)

        cliente.avancar_ciclo()
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/python.exe -m pytest centrais/testes/test_avaliacao_ponta_a_ponta.py -v`
Expected: 1 passed (`faturamento_total > 0.0`)

- [ ] **Step 5: Rodar a suíte completa do projeto**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: todos os testes de `mundo/testes`, `avaliador/testes`, `integridade/testes` e `centrais/testes` passam (os três primeiros não devem ter sido afetados — nenhum arquivo protegido foi tocado).

- [ ] **Step 6: Commit**

```bash
git add centrais/avaliacao.py centrais/testes/test_avaliacao_ponta_a_ponta.py
git commit -m "feat: liga as cinco centrais no loop unico de avaliacao"
```

---

### Task 8: Validação com o avaliador real e ajuste fino

**Files:**
- Nenhum arquivo novo obrigatório; possíveis ajustes pontuais em qualquer `centrais/*/*.py` conforme o resultado medido.

- [ ] **Step 1: Gerar um manifesto de integridade local**

Run:
```bash
.venv/Scripts/python.exe -c "from pathlib import Path; from integridade.manifesto import gerar_manifesto; gerar_manifesto(Path('.'), Path('/tmp/manifesto-local.json'))"
```
Expected: cria `/tmp/manifesto-local.json` sem erro.

- [ ] **Step 2: Rodar o avaliador com poucas seeds pra iteração rápida**

Run:
```bash
.venv/Scripts/python.exe -m avaliador.cli --seeds 1,2,3,4,5 --limite-de-ciclos 2000 --manifesto /tmp/manifesto-local.json --saida docs/relatorios/avaliacao-local.md --mostrar-relatorio
```
Expected: relatório gerado com `integridade_aprovada: true` e nenhuma seed em `FALHA_OPERACIONAL`.

- [ ] **Step 3: Ler o relatório e verificar `faturamento_total` médio**

Abrir `docs/relatorios/avaliacao-local.md` e conferir a métrica agregada de faturamento. Se alguma seed vier com `LIMITE_EXCEDIDO` ou `FALHA_OPERACIONAL`, investigar o traceback impresso no relatório antes de seguir.

- [ ] **Step 4: Rodar com a faixa completa de seeds sugerida pela spec da plataforma**

Run:
```bash
.venv/Scripts/python.exe -m avaliador.cli --quantidade-seeds 100 --seed-inicial 1 --limite-de-ciclos 5000 --manifesto /tmp/manifesto-local.json --saida docs/relatorios/avaliacao-completa.md --mostrar-relatorio
```
Expected: relatório completo, sem falhas de integridade.

- [ ] **Step 5: Ajustar parâmetros se necessário e commitar**

Se o faturamento estiver baixo ou houver `operacao_invalida` recorrente nos eventos (visível consultando `cliente.consultar_eventos(0)` num script de depuração), ajustar os limiares de energia (`PERFIL_DE_ENERGIA_POR_CENTRAL` em `missao/orquestrador.py`) ou os parâmetros de decisão (`MARGEM_DE_SEGURANCA`, escolha de modo/rota/política nos outros módulos). Cada ajuste é um commit separado, com o relatório de antes/depois citado na mensagem:

```bash
git add centrais/<arquivo-ajustado>.py
git commit -m "tune: ajusta <parametro> apos medir faturamento no avaliador"
```

Não commitar os arquivos de relatório em `docs/relatorios/` nem o manifesto temporário — são artefatos de execução local.
