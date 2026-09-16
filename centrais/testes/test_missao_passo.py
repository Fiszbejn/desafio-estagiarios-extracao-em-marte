from avaliador.aplicacao.cliente_de_avaliacao import ClienteDeAvaliacao
from centrais.missao import orquestrador


def test_passo_repoe_central_no_saldo_inicial_exato():
    cliente = ClienteDeAvaliacao()
    cliente.resetar(semente=1)
    contexto = orquestrador.criar_contexto()

    estado = cliente.consultar_estado()
    assert estado["energia"]["extracao"] == 10.0  # saldo inicial == limiar_minimo
    orquestrador.passo(cliente, estado, [], contexto)
    cliente.avancar_ciclo()

    novo_estado = cliente.consultar_estado()
    assert novo_estado["energia"]["extracao"] > 10.0
