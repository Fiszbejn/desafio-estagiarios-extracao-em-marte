"""Orquestrador da Central de Missão.

Responsabilidades resolvidas até aqui:
1. Nunca deixar o saldo de energia da própria Missão chegar a zero — ela é
   a única central irrecuperável do mundo: se dormir, para de alocar
   energia (inclusive para si mesma) e a simulação trava.
2. Manter as outras 4 centrais operacionais acima de um piso mínimo de
   energia, com alvos calibrados pelo custo real de cada uma. Extração é a
   mais faminta (custo por operação escala com quantidade e valor do
   mineral); Armazenagem é a mais barata por operação, mas tem dreno
   contínuo de manutenção por ocupação.
"""

from __future__ import annotations

import math
import time

import httpx

URL_BASE = "http://localhost:8000"
INTERVALO_DE_VERIFICACAO_SEGUNDOS = 1.0

LIMIAR_DE_SEGURANCA_DA_MISSAO = 5.0
QUANTIDADE_DE_REPOSICAO_DA_MISSAO = 20

PERFIL_DE_ENERGIA_POR_CENTRAL = {
    "extracao": {"limiar_minimo": 10.0, "alvo": 40},
    "transporte": {"limiar_minimo": 10.0, "alvo": 25},
    "pesquisa": {"limiar_minimo": 10.0, "alvo": 25},
    "armazenagem": {"limiar_minimo": 10.0, "alvo": 20},
}


def consultar_estado() -> dict:
    resposta = httpx.get(f"{URL_BASE}/missao/estado")
    resposta.raise_for_status()
    return resposta.json()


def consultar_eventos(desde_ciclo: int) -> list[dict]:
    resposta = httpx.get(f"{URL_BASE}/missao/eventos", params={"desde_ciclo": desde_ciclo})
    resposta.raise_for_status()
    return resposta.json()


def alocar_energia(destino: str, quantidade: int, politica: str = "pulso") -> None:
    """`quantidade` precisa ser inteira: a API de alocação rejeita fração (422)."""
    resposta = httpx.post(
        f"{URL_BASE}/missao/alocar-energia",
        json={"destino": destino, "quantidade": quantidade, "politica": politica},
    )
    resposta.raise_for_status()


def proteger_energia_da_missao(energia: dict) -> None:
    """Repõe o saldo da Missão sempre que ele cair abaixo do limiar de segurança."""
    if energia["missao"] < LIMIAR_DE_SEGURANCA_DA_MISSAO:
        alocar_energia("missao", QUANTIDADE_DE_REPOSICAO_DA_MISSAO)


def distribuir_energia_operacional(energia: dict) -> None:
    """Mantém as centrais operacionais acima do piso mínimo do seu perfil de custo."""
    for central, perfil in PERFIL_DE_ENERGIA_POR_CENTRAL.items():
        saldo_atual = energia[central]
        if saldo_atual < perfil["limiar_minimo"]:
            quantidade_a_repor = math.ceil(perfil["alvo"] - saldo_atual)
            if quantidade_a_repor > 0:
                alocar_energia(central, quantidade_a_repor)


def reagir_a_central_dormente(evento: dict) -> None:
    """`operacao_invalida` com central dormente/sem saldo é o sinal mais rápido
    de que uma central precisa de energia — mais rápido que esperar o próximo
    check de limiar, porque veio da tentativa real de executar um comando."""
    central = evento["dados"].get("central")
    if central in PERFIL_DE_ENERGIA_POR_CENTRAL:
        alocar_energia(central, PERFIL_DE_ENERGIA_POR_CENTRAL[central]["alvo"])
    elif central == "missao":
        alocar_energia("missao", QUANTIDADE_DE_REPOSICAO_DA_MISSAO)


def monitorar_eventos(desde_ciclo: int) -> int:
    """Consome eventos novos do barramento e reage a falhas por falta de energia.

    Retorna o próximo cursor de ciclo a usar na consulta seguinte.
    """
    eventos = consultar_eventos(desde_ciclo)
    ultimo_ciclo = desde_ciclo
    for evento in eventos:
        if evento["tipo"] == "operacao_invalida":
            reagir_a_central_dormente(evento)
        ultimo_ciclo = max(ultimo_ciclo, evento["ciclo"])
    return ultimo_ciclo


def executar_ciclo_de_gestao_de_energia(desde_ciclo: int) -> int:
    estado = consultar_estado()
    energia = estado["energia"]
    proteger_energia_da_missao(energia)
    distribuir_energia_operacional(energia)
    return monitorar_eventos(desde_ciclo)


def executar_loop_de_gestao_de_energia() -> None:
    desde_ciclo = 0
    while True:
        desde_ciclo = executar_ciclo_de_gestao_de_energia(desde_ciclo)
        time.sleep(INTERVALO_DE_VERIFICACAO_SEGUNDOS)


if __name__ == "__main__":
    executar_loop_de_gestao_de_energia()
