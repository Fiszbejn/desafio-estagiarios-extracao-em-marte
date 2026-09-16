from __future__ import annotations

from typing import Any

from centrais.comum.minerais import e_valioso

CENTRAL = "transporte"
MISSAO = "missao"
CUSTO_AUTORIZACAO = 0.2
MARGEM_DE_SEGURANCA = 1.0


def criar_contexto() -> dict:
    return {"cargas_despachadas": set()}


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


def _escolher_rota(rotas: list[dict], mineral: str) -> dict | None:
    if not rotas:
        return None
    if e_valioso(mineral):
        return min(rotas, key=lambda r: r["multiplicador_degradacao"])
    return min(rotas, key=lambda r: r["custo_energia_base"])


def _despachar(cliente: Any, contexto: dict, identificador_da_carga: str) -> None:
    if identificador_da_carga in contexto["cargas_despachadas"]:
        return

    plano = cliente.chamar("GET", f"/transporte/planejar-transporte?identificador_da_carga={identificador_da_carga}")
    identificadores_de_rota = plano.get("rotas_disponiveis", [])
    if not identificadores_de_rota:
        return

    cargas = cliente.chamar("GET", "/transporte/cargas-disponiveis")
    carga = next((c for c in cargas if c["identificador"] == identificador_da_carga), None)
    if carga is None:
        return

    todas_as_rotas = cliente.chamar("GET", "/transporte/rotas")
    rotas_candidatas = [r for r in todas_as_rotas if r["identificador"] in identificadores_de_rota]
    rota = _escolher_rota(rotas_candidatas, carga["mineral"])
    if rota is None:
        return

    transportadores = cliente.chamar("GET", "/transporte/transportadores")
    unidade = next((t for t in transportadores if t["estado"] == "disponivel"), None)
    if unidade is None:
        return

    saldo = cliente.consultar_estado()["energia"].get(CENTRAL, 0.0)
    if saldo < rota["custo_energia_base"] + MARGEM_DE_SEGURANCA:
        return

    autorizacao = _autorizar(cliente, "iniciar_viagem")
    if autorizacao is None:
        return

    modo = "rapido" if e_valioso(carga["mineral"]) else "economico"
    cliente.chamar(
        "POST",
        "/transporte/iniciar-viagem",
        {
            "identificador_da_unidade": unidade["identificador"],
            "identificador_da_rota": rota["identificador"],
            "identificador_da_carga": identificador_da_carga,
            "id_autorizacao": autorizacao,
            "modo": modo,
        },
    )
    contexto["cargas_despachadas"].add(identificador_da_carga)


def passo(cliente: Any, estado: dict, eventos: list[dict], contexto: dict) -> None:
    for evento in eventos:
        tipo = evento["tipo"]
        dados = evento["dados"]
        if tipo == "extracao_concluida":
            _despachar(cliente, contexto, dados["carga"])
        elif tipo == "transporte_concluido":
            cliente.chamar(
                "POST",
                "/transporte/descarregar",
                {"identificador_da_unidade": dados["unidade"], "identificador_da_carga": dados["carga"]},
            )
            cliente.chamar("POST", "/transporte/retornar-unidade", {"identificador_da_unidade": dados["unidade"]})
        elif tipo == "viagem_abortada":
            contexto["cargas_despachadas"].discard(dados["carga"])
            cliente.chamar("POST", "/transporte/retornar-unidade", {"identificador_da_unidade": dados["unidade"]})


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
