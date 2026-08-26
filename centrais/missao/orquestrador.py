"""Orquestrador da Central de Missão.

Compatível com o contrato que o avaliador espera de
`centrais/avaliacao.py::executar_avaliacao(cliente, limite_de_ciclos)`:
`cliente` expõe `chamar`, `consultar_estado`, `consultar_eventos`,
`avancar_ciclo` e `simulacao_encerrada` — sem rede real, sem loop de tempo
real. Por isso a lógica não fala HTTP diretamente: recebe `cliente` e só usa
essa interface, funcionando tanto in-process (avaliador) quanto contra um
servidor real via `ClienteHttpLocal` (uso manual, ver `__main__`).

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
INTERVALO_DE_CICLOS_ENTRE_VERIFICACOES = 10

LIMIAR_DE_SEGURANCA_DA_MISSAO = 5.0
QUANTIDADE_DE_REPOSICAO_DA_MISSAO = 20

PERFIL_DE_ENERGIA_POR_CENTRAL = {
    "extracao": {"limiar_minimo": 10.0, "alvo": 40},
    "transporte": {"limiar_minimo": 10.0, "alvo": 25},
    "pesquisa": {"limiar_minimo": 10.0, "alvo": 25},
    "armazenagem": {"limiar_minimo": 10.0, "alvo": 20},
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


def proteger_energia_da_missao(cliente: Any, energia: dict) -> None:
    """Repõe o saldo da Missão sempre que ele cair abaixo do limiar de segurança."""
    if energia["missao"] < LIMIAR_DE_SEGURANCA_DA_MISSAO:
        alocar_energia(cliente, "missao", QUANTIDADE_DE_REPOSICAO_DA_MISSAO)


def distribuir_energia_operacional(cliente: Any, energia: dict) -> None:
    """Mantém as centrais operacionais acima do piso mínimo do seu perfil de custo."""
    for central, perfil in PERFIL_DE_ENERGIA_POR_CENTRAL.items():
        saldo_atual = energia[central]
        if saldo_atual < perfil["limiar_minimo"]:
            quantidade_a_repor = math.ceil(perfil["alvo"] - saldo_atual)
            if quantidade_a_repor > 0:
                alocar_energia(cliente, central, quantidade_a_repor)


def reagir_a_central_dormente(cliente: Any, evento: dict) -> None:
    """`operacao_invalida` com central dormente/sem saldo é o sinal mais rápido
    de que uma central precisa de energia — mais rápido que esperar o próximo
    check de limiar, porque veio da tentativa real de executar um comando."""
    central = evento["dados"].get("central")
    if central in PERFIL_DE_ENERGIA_POR_CENTRAL:
        alocar_energia(cliente, central, PERFIL_DE_ENERGIA_POR_CENTRAL[central]["alvo"])
    elif central == "missao":
        alocar_energia(cliente, "missao", QUANTIDADE_DE_REPOSICAO_DA_MISSAO)


def monitorar_eventos(cliente: Any, desde_ciclo: int) -> int:
    """Consome eventos novos do barramento e reage a falhas por falta de energia.

    Retorna o próximo cursor de ciclo a usar na consulta seguinte.
    """
    eventos = cliente.consultar_eventos(desde_ciclo)
    ultimo_ciclo = desde_ciclo
    for evento in eventos:
        if evento["tipo"] == "operacao_invalida":
            reagir_a_central_dormente(cliente, evento)
        ultimo_ciclo = max(ultimo_ciclo, evento["ciclo"])
    return ultimo_ciclo


def executar_ciclo_de_gestao_de_energia(cliente: Any, desde_ciclo: int) -> int:
    estado = cliente.consultar_estado()
    energia = estado["energia"]
    proteger_energia_da_missao(cliente, energia)
    distribuir_energia_operacional(cliente, energia)
    return monitorar_eventos(cliente, desde_ciclo)


def executar(cliente: Any, limite_de_ciclos: int) -> None:
    """Ponto de entrada compatível com o contrato do avaliador.

    Checa e realoca a cada `INTERVALO_DE_CICLOS_ENTRE_VERIFICACOES` ciclos, e
    não a cada ciclo: consumo passivo é de 0.05/ciclo e os limiares têm
    margem de sobra pra isso, mas consultar+alocar em toda chamada de
    `avancar_ciclo` explode o número de chamadas em rodadas de milhares de
    ciclos (o avaliador roda 100-200 seeds).
    """
    desde_ciclo = 0
    ciclos_restantes = limite_de_ciclos
    while ciclos_restantes > 0:
        if cliente.simulacao_encerrada():
            return
        desde_ciclo = executar_ciclo_de_gestao_de_energia(cliente, desde_ciclo)
        passo = min(INTERVALO_DE_CICLOS_ENTRE_VERIFICACOES, ciclos_restantes)
        cliente.avancar_ciclo(passo)
        ciclos_restantes -= passo


if __name__ == "__main__":
    executar(ClienteHttpLocal(), limite_de_ciclos=10_000_000)
