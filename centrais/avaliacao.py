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
