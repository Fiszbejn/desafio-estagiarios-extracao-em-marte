from __future__ import annotations

from typing import Any


CENTRAL = "armazenagem"
MISSAO = "missao"
CUSTO_POR_UNIDADE = 0.05
CUSTO_AUTORIZACAO = 0.2
MARGEM_DE_SEGURANCA = 1.0
RESERVA_MINIMA = 500.0
MAXIMO_DE_EXTRACOES = 1
PREFERENCIA_DE_MINERAIS = {
    "gelo_de_agua": 40.0,
    "jarosita": 35.0,
}
ORCAMENTOS_INICIAIS = {
    "extracao": 120.0,
    "transporte": 150.0,
    "armazenagem": 80.0,
    "pesquisa": 100.0,
}


def _autorizar(cliente: Any, operacao: str, central: str = CENTRAL) -> str | None:
    estado = cliente.consultar_estado()
    if estado["energia"].get(MISSAO, 0.0) < CUSTO_AUTORIZACAO:
        return None
    resposta = cliente.chamar(
        "POST",
        "/missao/autorizar-missao",
        {
            "operacao": operacao,
            "central_solicitante": central,
        },
    )
    return resposta["id_autorizacao"]


def armazenar_cargas_disponiveis(cliente: Any, cargas: list[dict]) -> None:
    armazens = cliente.chamar("GET", "/armazenagem/armazens")
    estado = cliente.consultar_estado()
    saldo = estado["energia"].get(CENTRAL, 0.0)

    for armazem in armazens:
        cargas_do_armazem = [
            carga
            for carga in cargas
            if carga["identificador"] not in armazem["pilha"]
            and armazem["ocupacao"] + carga["quantidade"] <= armazem["capacidade"]
        ]
        if not cargas_do_armazem:
            continue

        for carga in cargas_do_armazem:
            custo = carga["quantidade"] * CUSTO_POR_UNIDADE
            if saldo < custo + MARGEM_DE_SEGURANCA:
                continue
            autorizacao = _autorizar(cliente, "receber_carga")
            if autorizacao is None:
                return
            cliente.chamar(
                "POST",
                "/armazenagem/receber-carga",
                {
                    "identificador_do_armazem": armazem["identificador"],
                    "identificadores_das_cargas": [carga["identificador"]],
                    "id_autorizacao": autorizacao,
                },
            )
            saldo -= custo
            armazem["ocupacao"] += carga["quantidade"]
            return


def executar(cliente: Any, limite_de_ciclos: int) -> None:
    ultimo_ciclo_lido = 0
    orcamentos_enviados = False
    extracoes_iniciadas = 0
    cargas_em_analise: set[str] = set()
    cargas_aprovadas: set[str] = set()
    cargas_retiradas: set[str] = set()

    for _ in range(limite_de_ciclos):
        if cliente.simulacao_encerrada():
            return

        estado = cliente.consultar_estado()
        if not orcamentos_enviados:
            reserva = estado["energia"].get("reserva_estrategica", 0.0)
            total = sum(ORCAMENTOS_INICIAIS.values())
            if reserva - total >= RESERVA_MINIMA:
                for destino, quantidade in ORCAMENTOS_INICIAIS.items():
                    cliente.chamar(
                        "POST",
                        "/missao/alocar-energia",
                        {"destino": destino, "quantidade": quantidade, "politica": "pulso"},
                    )
                orcamentos_enviados = True

        eventos = cliente.consultar_eventos(ultimo_ciclo_lido)
        ultimo_ciclo_lido = estado["ciclo_atual"] + 1

        for evento in eventos:
            tipo = evento["tipo"]
            dados = evento["dados"]
            if tipo == "extracao_concluida":
                cliente.chamar(
                    "POST",
                    "/extracao/retornar-unidade",
                    {"identificador_da_unidade": dados["unidade"]},
                )
                _iniciar_transporte_se_houver_orcamento(
                    cliente, dados["carga"], dados["jazida"],
                )
            elif tipo == "transporte_concluido":
                cliente.chamar(
                    "POST",
                    "/transporte/retornar-unidade",
                    {"identificador_da_unidade": dados["unidade"]},
                )
                cargas = cliente.chamar("GET", "/transporte/cargas-disponiveis")
                armazenar_cargas_disponiveis(
                    cliente,
                    [carga for carga in cargas if carga["identificador"] == dados["carga"]],
                )
            elif tipo == "cargas_armazenadas":
                for identificador in dados["cargas"]:
                    if identificador in cargas_em_analise:
                        continue
                    tipo_de_analise = _escolher_analise(cliente)
                    if tipo_de_analise is not None:
                        cliente.chamar(
                            "POST",
                            "/pesquisa/iniciar-analise",
                            {
                                "identificador_da_carga": identificador,
                                "tipo_de_analise": tipo_de_analise,
                            },
                        )
                        cargas_em_analise.add(identificador)
            elif tipo == "analise_concluida":
                identificador = dados["carga"]
                if identificador in cargas_em_analise:
                    cliente.chamar(
                        "POST",
                        "/pesquisa/aprovar-carga",
                        {"identificador_da_carga": identificador, "politica": "comercial"},
                    )
            elif tipo == "carga_aprovada":
                identificador = dados["carga"]
                if identificador not in cargas_aprovadas:
                    _retirar_carga_se_for_topo(cliente, identificador)
                    cargas_aprovadas.add(identificador)
            elif tipo == "cargas_desempilhadas":
                for identificador in dados["cargas"]:
                    if identificador in cargas_aprovadas and identificador not in cargas_retiradas:
                        autorizacao = _autorizar(cliente, "preparar_distribuicao", "pesquisa")
                        if autorizacao is not None:
                            cliente.chamar(
                                "POST",
                                "/pesquisa/preparar-distribuicao",
                                {"identificador_da_carga": identificador, "id_autorizacao": autorizacao},
                            )
                            cargas_retiradas.add(identificador)

        if (
            extracoes_iniciadas < MAXIMO_DE_EXTRACOES
            and orcamentos_enviados
            and _pode_operar(cliente, "extracao", 10.0)
        ):
            jazidas = cliente.chamar("GET", "/extracao/jazidas")
            disponiveis = [
                jazida
                for jazida in jazidas
                if jazida["estado"] == "disponivel"
                and jazida["mineral"] in PREFERENCIA_DE_MINERAIS
            ]
            disponiveis.sort(
                key=lambda jazida: PREFERENCIA_DE_MINERAIS.get(jazida["mineral"], 0.0),
                reverse=True,
            )
            modo_de_extracao = _escolher_extracao(cliente)
            mineradoras = cliente.chamar("GET", "/extracao/mineradoras")
            unidade_disponivel = next(
                (unidade for unidade in mineradoras if unidade["estado"] == "disponivel"),
                None,
            )
            if disponiveis and unidade_disponivel is not None and modo_de_extracao is not None:
                cliente.chamar(
                    "POST",
                    "/extracao/iniciar-extracao",
                    {
                        "identificador_da_unidade": unidade_disponivel["identificador"],
                        "identificador_da_jazida": disponiveis[0]["identificador"],
                        "quantidade": 10.0,
                        "modo": modo_de_extracao,
                        "perfil_de_escavacao": "superficial",
                    },
                )
                extracoes_iniciadas += 1

        cliente.avancar_ciclo()


def _pode_operar(cliente: Any, central: str, custo_estimado: float) -> bool:
    estado = cliente.consultar_estado()
    return estado["energia"].get(central, 0.0) >= custo_estimado + MARGEM_DE_SEGURANCA


def _iniciar_transporte_se_houver_orcamento(
    cliente: Any, identificador_da_carga: str, identificador_da_jazida: str,
) -> None:
    modo_de_transporte = _escolher_transporte(cliente)
    if modo_de_transporte is None:
        return
    jazida = cliente.chamar("GET", f"/extracao/jazidas/{identificador_da_jazida}")
    rotas = cliente.chamar("GET", "/transporte/rotas")
    rota = next(
        (
            item for item in rotas
            if item["condicao"] == "livre" and item["origem"] == jazida["localizacao"]
        ),
        None,
    )
    autorizacao = _autorizar(cliente, "iniciar_viagem", "transporte")
    if rota is None or autorizacao is None:
        return
    cliente.chamar(
        "POST",
        "/transporte/iniciar-viagem",
        {
            "identificador_da_unidade": "transportadora-1",
            "identificador_da_rota": rota["identificador"],
            "identificador_da_carga": identificador_da_carga,
            "id_autorizacao": autorizacao,
            "modo": modo_de_transporte,
        },
    )


def _escolher_extracao(cliente: Any) -> str | None:
    saldo = cliente.consultar_estado()["energia"].get("extracao", 0.0)
    if saldo >= 15.0:
        return "cuidadoso"
    if saldo >= 11.0:
        return "normal"
    if saldo >= 3.0:
        return "agressivo"
    return None


def _escolher_transporte(cliente: Any) -> str | None:
    saldo = cliente.consultar_estado()["energia"].get("transporte", 0.0)
    if saldo >= 8.0:
        return "rapido"
    if saldo >= 4.0:
        return "economico"
    return None


def _escolher_analise(cliente: Any) -> str | None:
    saldo = cliente.consultar_estado()["energia"].get("pesquisa", 0.0)
    if saldo >= 6.0:
        return "completa"
    if saldo >= 3.0:
        return "rapida"
    return None


def _retirar_carga_se_for_topo(cliente: Any, identificador_da_carga: str) -> None:
    for armazem in cliente.chamar("GET", "/armazenagem/armazens"):
        if armazem["pilha"] and armazem["pilha"][-1] == identificador_da_carga:
            if not _pode_operar(cliente, CENTRAL, 0.0):
                return
            autorizacao = _autorizar(cliente, "retirar_carga")
            if autorizacao is None:
                return
            cliente.chamar(
                "POST",
                "/armazenagem/retirar-carga",
                {
                    "identificador_do_armazem": armazem["identificador"],
                    "identificador_da_carga": identificador_da_carga,
                    "id_autorizacao": autorizacao,
                },
            )
            return
