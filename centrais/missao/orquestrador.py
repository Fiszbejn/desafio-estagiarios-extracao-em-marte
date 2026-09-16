"""Orquestrador da Central de Missão.

Compatível com o contrato que o avaliador espera de
`centrais/avaliacao.py::executar_avaliacao(cliente, limite_de_ciclos)`:
`cliente` expõe `chamar`, `consultar_estado`, `consultar_eventos`,
`avancar_ciclo` e `simulacao_encerrada` — sem rede real, sem loop de tempo
real. Por isso a lógica não fala HTTP diretamente: recebe `cliente` e só usa
essa interface, funcionando tanto in-process (avaliador) quanto contra um
servidor real via `ClienteHttpLocal` (uso manual, ver `__main__`).

`passo` é chamado uma vez por ciclo pelo loop único em
`centrais/avaliacao.py` (junto com o passo das outras quatro centrais),
nunca mais possuindo seu próprio loop/`avancar_ciclo` fora do modo manual.

Responsabilidades resolvidas até aqui:
1. Nunca deixar o saldo de energia da própria Missão chegar a zero — ela é
   a única central irrecuperável do mundo: se dormir, para de alocar
   energia (inclusive para si mesma) e a simulação trava.
2. Manter as outras 4 centrais operacionais acima de um piso mínimo de
   energia, com alvos calibrados pelo custo real de cada uma. Extração é a
   mais faminta; Armazenagem é a mais barata por operação, mas tem dreno
   contínuo de manutenção por ocupação.
3. Reagir a eventos `operacao_invalida` repondo energia da central afetada
   na hora, mais rápido que esperar o próximo check de limiar.
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
    # Extração precisa de folga bem maior que as outras: uma única extração
    # de um mineral raro (custo_extracao=8.0, modo cuidadoso) pode custar
    # bem mais de 60 de energia sozinha. Um alvo baixo demais força a central
    # a reduzir a quantidade extraída para caber no saldo, capturando só uma
    # fração do valor de cada jazida valiosa.
    "extracao": {"limiar_minimo": 10.0, "alvo": 250},
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
    """Mantém as centrais operacionais acima do piso mínimo do seu perfil de custo.

    Uma alocação só é aplicada pelo mundo no ciclo seguinte ao pedido
    (`POST /missao/alocar-energia`). Reavaliar o limiar todo ciclo sem
    lembrar o que já foi pedido faz a Missão pedir a mesma reposição várias
    vezes antes da primeira chegar, estourando a reserva estratégica em
    poucas dezenas de ciclos — por isso `pendentes` trava uma central por
    exatamente um ciclo após cada pedido, até o saldo já refletir a resposta.
    """
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
    """`operacao_invalida` com central dormente/sem saldo é o sinal mais rápido
    de que uma central precisa de energia — mais rápido que esperar o próximo
    check de limiar, porque veio da tentativa real de executar um comando.

    `motivo` é `str(erro)` (ver `mundo/motor/motor_de_simulacao.py`). Um
    `EnergiaInsuficienteError(central)` imprime exatamente o nome da central;
    "Central X dormente" tambem indica falta de energia. Qualquer outro
    motivo (capacidade excedida, jazida indisponivel, quantidade invalida...)
    nao tem nada a ver com energia — reagir a ele aqui so desperdiça reserva
    em cima de um bug de outra central, sem nunca resolver a causa real.
    """
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
    # O que ficou pendente no ciclo anterior ja foi aplicado nesse `estado`
    # (a alocacao entra no tick seguinte ao pedido) — limpar antes de
    # reavaliar, senao a central fica bloqueada de receber nova reposicao
    # para sempre depois da primeira vez.
    pendentes.clear()
    proteger_energia_da_missao(cliente, energia, pendentes)
    distribuir_energia_operacional(cliente, energia, pendentes)
    for evento in eventos:
        if evento["tipo"] == "operacao_invalida":
            reagir_a_central_dormente(cliente, evento, pendentes)


def executar(cliente: Any, limite_de_ciclos: int) -> None:
    """Ponto de entrada só para rodar esta central sozinha, manualmente.

    No avaliador, `passo` é chamado direto pelo loop único de
    `centrais/avaliacao.py`, junto com o passo das outras quatro centrais.
    """
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
