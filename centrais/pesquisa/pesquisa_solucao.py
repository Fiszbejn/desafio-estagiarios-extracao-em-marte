from __future__ import annotations

from typing import Any

from centrais.comum.minerais import ciclos_de_analise, valor_por_unidade

CENTRAL = "pesquisa"
MISSAO = "missao"
CUSTO_AUTORIZACAO = 0.2
# `mundo/api/pesquisa.py::iniciar_analise` mostra que `tipo_de_analise` so
# muda duracao e custo — nao ha nenhuma diferenca de qualidade/confiabilidade
# entre "rapida", "completa" e "forense". Com um unico slot compartilhado
# (capacidade_paralela = 1) sendo o gargalo real do pipeline, usar sempre a
# mais rapida E mais barata (0.5x duracao, 0.8x custo) e estritamente melhor
# — mais vazao no mesmo tempo, sem nenhuma perda.
TIPO_DE_ANALISE = "rapida"
# Mesma logica em `aprovar_carga`: a politica so muda o limiar de qualidade
# exigido (comercial=40, estrita=70, premium=85); nao afeta o valor entregue
# em `preparar_distribuicao`. Usar sempre "comercial" (o limiar mais baixo)
# nunca rejeita algo que uma politica mais rigida aceitaria, e ainda aprova
# cargas medianamente degradadas que "estrita"/"premium" descartariam a toa.
POLITICA_DE_APROVACAO = "comercial"


def criar_contexto() -> dict:
    return {
        "fila": [],
        "mineral_por_carga": {},
        "quantidade_por_carga": {},
        "aprovadas_pendentes": set(),
    }


def _prioridade(contexto: dict, identificador: str) -> float:
    """Valor bruto entregue por ciclo que a carga ocupa o slot da Pesquisa.

    Com um unico slot, a ordem de atendimento decide quem corre risco de
    nunca ser analisado antes da energia acabar — priorizar por valor
    total ignoraria que uma carga cara mas lenta de analisar (cristal leva
    8 ciclos) ocupa o gargalo por muito mais tempo que uma barata e rapida
    (hematita leva 2): o que maximiza a vazao é o valor por ciclo ocupado.
    """
    mineral = contexto["mineral_por_carga"].get(identificador, "")
    quantidade = contexto["quantidade_por_carga"].get(identificador, 0.0)
    duracao = ciclos_de_analise(mineral) * 0.5  # ajuste de duracao da analise "rapida"
    if duracao <= 0:
        return 0.0
    return (valor_por_unidade(mineral) * quantidade) / duracao


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
                    contexto["quantidade_por_carga"][identificador] = carga["quantidade"]
                    contexto["fila"].append(identificador)
        elif tipo == "analise_concluida":
            identificador = dados["carga"]
            cliente.chamar(
                "POST",
                "/pesquisa/aprovar-carga",
                {"identificador_da_carga": identificador, "politica": POLITICA_DE_APROVACAO},
            )
        elif tipo == "carga_aprovada":
            identificador = dados["carga"]
            contexto["aprovadas_pendentes"].add(identificador)
            _tentar_distribuir(cliente, contexto, identificador)
        elif tipo == "cargas_desempilhadas":
            for identificador in dados["cargas"]:
                if identificador in contexto["aprovadas_pendentes"]:
                    _tentar_distribuir(cliente, contexto, identificador)

    # A fonte de verdade de slot livre e sempre a API ao vivo, nunca uma
    # flag local: se um `iniciar-analise` for rejeitado (operacao_invalida),
    # nenhum `analise_concluida` chega pra liberar uma flag local, o que
    # travaria a fila pra sempre (unico slot compartilhado da central).
    if contexto["fila"] and not cliente.chamar("GET", "/pesquisa/em-andamento"):
        contexto["fila"].sort(key=lambda i: _prioridade(contexto, i), reverse=True)
        identificador = contexto["fila"].pop(0)
        cliente.chamar(
            "POST",
            "/pesquisa/iniciar-analise",
            {"identificador_da_carga": identificador, "tipo_de_analise": TIPO_DE_ANALISE},
        )


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
