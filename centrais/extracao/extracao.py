from __future__ import annotations

from typing import Any

from centrais.comum.minerais import custo_extracao, e_valioso, valor_por_unidade

CENTRAL = "extracao"
MARGEM_DE_SEGURANCA = 0.5

FATOR_DESPERDICIO_POR_MODO = {"cuidadoso": 1.0, "normal": 1.2, "agressivo": 1.4}
MULT_ENERGIA_POR_MODO = {"cuidadoso": 1.8, "normal": 1.0, "agressivo": 0.45}
AJUSTE_ENERGIA_POR_PERFIL = {"superficial": 0.9, "profunda": 1.25, "mapeadora": 1.1}
FATOR_BASE_DE_ENERGIA = 0.2
EXPOENTE_DE_ESCASSEZ = 2.0
SENSIBILIDADE_AO_DESGASTE = 0.65
MARGEM_DE_SEGURANCA_DO_CUSTO = 1.0
MODO_POR_MINERAL = {
    "cristal_marciano_raro": "cuidadoso",
    "gelo_de_agua": "normal",
    "jarosita": "normal",
}


def criar_contexto() -> dict:
    return {"quantidade_original_por_jazida": {}}


def _parametros_de_extracao(mineral: str) -> dict:
    # "superficial" sempre: qualidade final e min(100, qualidade_do_modo +
    # bonus_do_perfil), e "cuidadoso"/"normal" ja saturam perto de 100, entao
    # o bonus de perfis mais caros nunca se realiza plenamente.
    if e_valioso(mineral):
        modo = MODO_POR_MINERAL.get(mineral, "cuidadoso")
        return {"tipo_preferido": "precisa", "modo": modo, "perfil_de_escavacao": "superficial"}
    return {"tipo_preferido": "leve", "modo": "agressivo", "perfil_de_escavacao": "superficial"}


def _fracao_restante(contexto: dict, jazida: dict) -> float:
    # A API nao expoe a quantidade original da jazida; usa a primeira
    # observacao como aproximacao.
    originais = contexto["quantidade_original_por_jazida"]
    identificador = jazida["identificador"]
    if identificador not in originais:
        originais[identificador] = jazida["quantidade_disponivel"]
    return min(1.0, jazida["quantidade_disponivel"] / originais[identificador])


def _atratividade(contexto: dict, jazida: dict) -> float:
    # Cada mineral tem duas jazidas; ponderar por valor x fracao_restante^2
    # (em vez de só valor) evita esgotar uma inteira, pagando escassez
    # crescente, antes de usar a irmã ainda intacta.
    fracao_restante = _fracao_restante(contexto, jazida)
    return valor_por_unidade(jazida["mineral"]) * (fracao_restante**EXPOENTE_DE_ESCASSEZ)


def _custo_por_unidade(contexto: dict, jazida: dict, unidade: dict, modo: str, perfil: str) -> float:
    # Aproxima o custo real de `mundo/api/extracao.py::iniciar_extracao`.
    fracao_restante = _fracao_restante(contexto, jazida)
    fator_de_escassez = 1.0 if fracao_restante <= 0.0 else fracao_restante**-EXPOENTE_DE_ESCASSEZ
    fator_de_desgaste = 1.0 + max(0.0, unidade["desgaste"]) * SENSIBILIDADE_AO_DESGASTE
    custo_por_unidade = (
        custo_extracao(jazida["mineral"])
        * FATOR_BASE_DE_ENERGIA
        * MULT_ENERGIA_POR_MODO[modo]
        * AJUSTE_ENERGIA_POR_PERFIL[perfil]
        * fator_de_escassez
        * fator_de_desgaste
    )
    return custo_por_unidade * MARGEM_DE_SEGURANCA_DO_CUSTO


def passo(cliente: Any, estado: dict, eventos: list[dict], contexto: dict) -> None:
    for evento in eventos:
        if evento["tipo"] in ("extracao_concluida", "extracao_interrompida"):
            cliente.chamar(
                "POST", "/extracao/retornar-unidade", {"identificador_da_unidade": evento["dados"]["unidade"]}
            )

    saldo = estado["energia"].get(CENTRAL, 0.0)
    if saldo <= 0.0:
        return

    jazidas = cliente.chamar("GET", "/extracao/jazidas")
    disponiveis = [j for j in jazidas if j["estado"] == "disponivel" and j["quantidade_disponivel"] > 0]
    if not disponiveis:
        return
    disponiveis.sort(key=lambda j: _atratividade(contexto, j), reverse=True)

    mineradoras = cliente.chamar("GET", "/extracao/mineradoras")
    unidades_livres = [m for m in mineradoras if m["estado"] == "disponivel"]

    for jazida in disponiveis:
        if not unidades_livres:
            break
        parametros = _parametros_de_extracao(jazida["mineral"])
        unidade = next(
            (u for u in unidades_livres if u["tipo"] == parametros["tipo_preferido"]),
            unidades_livres[0],
        )
        fator_desperdicio = FATOR_DESPERDICIO_POR_MODO[parametros["modo"]]
        quantidade = min(unidade["capacidade"], jazida["quantidade_disponivel"] / fator_desperdicio)
        if quantidade <= 0:
            continue
        custo_por_unidade = _custo_por_unidade(
            contexto, jazida, unidade, parametros["modo"], parametros["perfil_de_escavacao"]
        )
        # Reduz a quantidade ao maximo afordavel em vez de desistir da jazida.
        orcamento_disponivel = saldo - MARGEM_DE_SEGURANCA
        if custo_por_unidade > 0 and quantidade * custo_por_unidade > orcamento_disponivel:
            quantidade = orcamento_disponivel / custo_por_unidade
        if quantidade < 1.0:
            continue
        custo_estimado = quantidade * custo_por_unidade
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
    import time

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
            time.sleep(1.0 * quantidade)

        def simulacao_encerrada(self) -> bool:
            energia = self.consultar_estado()["energia"]
            return all(saldo <= 0.0 for central, saldo in energia.items() if central != "reserva_estrategica")

    executar(_ClienteHttpLocal(), limite_de_ciclos=10_000_000)
