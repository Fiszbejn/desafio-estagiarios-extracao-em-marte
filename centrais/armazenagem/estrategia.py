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
