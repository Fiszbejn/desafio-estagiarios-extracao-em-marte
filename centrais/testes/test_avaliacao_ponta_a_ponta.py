from avaliador.aplicacao.cliente_de_avaliacao import ClienteDeAvaliacao
from centrais.avaliacao import executar_avaliacao


def test_pipeline_completo_gera_faturamento():
    cliente = ClienteDeAvaliacao()
    cliente.resetar(semente=1)

    executar_avaliacao(cliente, limite_de_ciclos=1500)

    estado_final = cliente.consultar_estado()
    assert estado_final["faturamento_total"] > 0.0
