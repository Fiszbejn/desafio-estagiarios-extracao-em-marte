from avaliador.aplicacao.cliente_de_avaliacao import ClienteDeAvaliacao
from centrais.extracao import extracao


def test_passo_inicia_extracao_quando_ha_jazida_e_mineradora_livres():
    cliente = ClienteDeAvaliacao()
    cliente.resetar(semente=1)
    contexto = extracao.criar_contexto()

    estado = cliente.consultar_estado()
    extracao.passo(cliente, estado, [], contexto)
    cliente.avancar_ciclo()

    mineradoras = cliente.chamar("GET", "/extracao/mineradoras")
    assert any(m["estado"] != "disponivel" for m in mineradoras)
