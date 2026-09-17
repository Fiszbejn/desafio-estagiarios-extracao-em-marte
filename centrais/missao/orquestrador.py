"""Orquestrador da Central de Missão.

`passo` é chamado uma vez por ciclo pelo loop único em
`centrais/avaliacao.py`. `executar`/`ClienteHttpLocal` só servem para uso
manual fora do avaliador.
"""

from __future__ import annotations

import math
import time
from typing import Any

import httpx

URL_BASE = "http://localhost:8000"
INTERVALO_DE_VERIFICACAO_SEGUNDOS = 1.0

LIMIAR_DE_SEGURANCA_DA_MISSAO = 5.0
QUANTIDADE_DE_REPOSICAO_DA_MISSAO = 20

PERFIL_DE_ENERGIA_POR_CENTRAL = {
    "extracao": {"limiar_minimo": 10.0, "alvo": 270},
    "transporte": {"limiar_minimo": 10.0, "alvo": 40},
    "pesquisa": {"limiar_minimo": 10.0, "alvo": 35},
    "armazenagem": {"limiar_minimo": 10.0, "alvo": 25},
}


class ClienteHttpLocal:
    """Adaptador para rodar este orquestrador manualmente contra um mundo
    real (`uvicorn mundo.api.app:app`), fora do avaliador."""

    def __init__(self, url_base: str = URL_BASE) -> None:
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
        # O mundo real avança sozinho (loop de tempo real); só esperamos.
        time.sleep(INTERVALO_DE_VERIFICACAO_SEGUNDOS * quantidade)

    def simulacao_encerrada(self) -> bool:
        # Não há endpoint HTTP para o motor.encerrada; aproximamos pela
        # regra de domínio: encerra quando todas as centrais estão dormentes.
        energia = self.consultar_estado()["energia"]
        return all(
            saldo <= 0.0 for central, saldo in energia.items() if central != "reserva_estrategica"
        )


def alocar_energia(cliente: Any, destino: str, quantidade: int, politica: str = "pulso") -> None:
    """`quantidade` precisa ser inteira: a API de alocação rejeita fração (422)."""
    cliente.chamar(
        "POST",
        "/missao/alocar-energia",
        {"destino": destino, "quantidade": quantidade, "politica": politica},
    )


def proteger_energia_da_missao(cliente: Any, energia: dict, pendentes: set[str]) -> None:
    """Repõe o saldo da Missão sempre que ele cair abaixo do limiar de segurança."""
    if "missao" in pendentes:
        return
    if energia["missao"] < LIMIAR_DE_SEGURANCA_DA_MISSAO:
        alocar_energia(cliente, "missao", QUANTIDADE_DE_REPOSICAO_DA_MISSAO)
        pendentes.add("missao")


def distribuir_energia_operacional(cliente: Any, energia: dict, pendentes: set[str]) -> None:
    """Mantém as centrais operacionais acima do piso mínimo do seu perfil de custo."""
    for central, perfil in PERFIL_DE_ENERGIA_POR_CENTRAL.items():
        if central in pendentes:
            continue
        saldo_atual = energia[central]
        if saldo_atual <= perfil["limiar_minimo"]:
            quantidade_a_repor = math.ceil(perfil["alvo"] - saldo_atual)
            if quantidade_a_repor > 0:
                alocar_energia(cliente, central, quantidade_a_repor)
                pendentes.add(central)


def reagir_a_central_dormente(cliente: Any, evento: dict, pendentes: set[str]) -> None:
    # `motivo` e `str(erro)`: `EnergiaInsuficienteError(central)` imprime o
    # nome da central, "Central X dormente" tambem indica falta de energia.
    # Qualquer outro motivo (capacidade excedida, jazida indisponivel...) nao
    # e sobre energia e nao deve gastar reserva.
    dados = evento["dados"]
    central = dados.get("central")
    motivo = dados.get("motivo", "")
    e_falta_de_energia = motivo == central or "dormente" in motivo
    if not e_falta_de_energia or central in pendentes:
        return
    if central in PERFIL_DE_ENERGIA_POR_CENTRAL:
        alocar_energia(cliente, central, PERFIL_DE_ENERGIA_POR_CENTRAL[central]["alvo"])
        pendentes.add(central)
    elif central == "missao":
        alocar_energia(cliente, "missao", QUANTIDADE_DE_REPOSICAO_DA_MISSAO)
        pendentes.add("missao")


def criar_contexto() -> dict:
    return {"pendentes": set()}


def passo(cliente: Any, estado: dict, eventos: list[dict], contexto: dict) -> None:
    energia = estado["energia"]
    pendentes = contexto["pendentes"]
    # Uma alocacao pedida neste ciclo so e aplicada no proximo; pendentes
    # evita pedir a mesma reposicao de novo antes dela chegar.
    pendentes.clear()
    proteger_energia_da_missao(cliente, energia, pendentes)
    distribuir_energia_operacional(cliente, energia, pendentes)
    for evento in eventos:
        if evento["tipo"] == "operacao_invalida":
            reagir_a_central_dormente(cliente, evento, pendentes)


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
