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
3. Emitir autorizações para as operações protegidas das demais centrais
   (iniciar_viagem, retirar_carga, solicitar_transporte, receber_carga,
   preparar_distribuicao) — nenhuma central opera sem passar pela Missão.
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


def alocar_energia(destino: str, quantidade: int, politica: str = "pulso") -> None:
    """`quantidade` precisa ser inteira: a API de alocação rejeita fração (422)."""
    resposta = httpx.post(
        f"{URL_BASE}/missao/alocar-energia",
        json={"destino": destino, "quantidade": quantidade, "politica": politica},
    )
    resposta.raise_for_status()


def emitir_autorizacao(operacao: str, central_solicitante: str, classe: str = "rapida") -> str:
    """Solicita à Missão um `id_autorizacao` para uma operação protegida de outra central.

    Usada por transporte (`iniciar_viagem`), armazenagem (`receber_carga`,
    `retirar_carga`, `solicitar_transporte`) e pesquisa (`preparar_distribuicao`)
    antes de executar a operação — a autorização é consumida uma única vez.
    """
    resposta = httpx.post(
        f"{URL_BASE}/missao/autorizar-missao",
        json={
            "operacao": operacao,
            "central_solicitante": central_solicitante,
            "classe": classe,
        },
    )
    resposta.raise_for_status()
    return resposta.json()["id_autorizacao"]


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


def executar_ciclo_de_gestao_de_energia() -> None:
    estado = consultar_estado()
    energia = estado["energia"]
    proteger_energia_da_missao(energia)
    distribuir_energia_operacional(energia)


def executar_loop_de_gestao_de_energia() -> None:
    while True:
        executar_ciclo_de_gestao_de_energia()
        time.sleep(INTERVALO_DE_VERIFICACAO_SEGUNDOS)


if __name__ == "__main__":
    executar_loop_de_gestao_de_energia()
