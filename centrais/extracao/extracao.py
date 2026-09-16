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
