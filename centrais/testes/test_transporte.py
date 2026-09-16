from avaliador.aplicacao.cliente_de_avaliacao import ClienteDeAvaliacao
from centrais.extracao import extracao
from centrais.transporte import transporte_otimizado


def _extrair_ate_ter_uma_carga(cliente, limite_de_ciclos=200):
    contexto_extracao = extracao.criar_contexto()
    desde_ciclo = 0
    for _ in range(limite_de_ciclos):
        estado = cliente.consultar_estado()
        eventos = cliente.consultar_eventos(desde_ciclo)
        extracao.passo(cliente, estado, eventos, contexto_extracao)
        proximo_desde_ciclo = estado["ciclo_atual"] + 1
        for evento in eventos:
            if evento["tipo"] == "extracao_concluida":
                return evento["dados"]["carga"], desde_ciclo
        desde_ciclo = proximo_desde_ciclo
        cliente.avancar_ciclo()
    raise AssertionError("extracao nao concluiu a tempo")


def test_passo_inicia_viagem_para_carga_recem_extraida():
    cliente = ClienteDeAvaliacao()
    cliente.resetar(semente=1)
    _, desde_ciclo = _extrair_ate_ter_uma_carga(cliente)

    contexto = transporte_otimizado.criar_contexto()
    estado = cliente.consultar_estado()
    eventos = cliente.consultar_eventos(desde_ciclo)
    transporte_otimizado.passo(cliente, estado, eventos, contexto)
    cliente.avancar_ciclo()

    transportadores = cliente.chamar("GET", "/transporte/transportadores")
    assert any(t["estado"] != "disponivel" for t in transportadores)
