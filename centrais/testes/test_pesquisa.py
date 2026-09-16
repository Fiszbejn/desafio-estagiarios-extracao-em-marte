from avaliador.aplicacao.cliente_de_avaliacao import ClienteDeAvaliacao
from centrais.pesquisa import pesquisa_solucao


def test_passo_nao_quebra_quando_carga_da_fila_nao_existe():
    cliente = ClienteDeAvaliacao()
    cliente.resetar(semente=1)
    cliente.chamar("POST", "/missao/alocar-energia", {"destino": "pesquisa", "quantidade": 30, "politica": "pulso"})
    cliente.avancar_ciclo()

    contexto = pesquisa_solucao.criar_contexto()
    estado = cliente.consultar_estado()
    evento = {"tipo": "carga_disponivel", "dados": {"carga": "carga-teste"}}
    pesquisa_solucao.passo(cliente, estado, [evento], contexto)

    em_andamento = cliente.chamar("GET", "/pesquisa/em-andamento")
    assert em_andamento == []
