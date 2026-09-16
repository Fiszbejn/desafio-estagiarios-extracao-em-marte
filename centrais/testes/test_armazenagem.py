from avaliador.aplicacao.cliente_de_avaliacao import ClienteDeAvaliacao
from centrais.armazenagem import estrategia


def test_passo_consulta_pesquisa_antes_de_decidir_guardar(monkeypatch):
    cliente = ClienteDeAvaliacao()
    cliente.resetar(semente=1)
    cliente.chamar("POST", "/missao/alocar-energia", {"destino": "armazenagem", "quantidade": 50, "politica": "pulso"})
    cliente.avancar_ciclo()

    chamado = {"valor": False}
    original_chamar = cliente.chamar

    def _rastrear_chamadas(metodo, rota, json=None):
        if rota == "/pesquisa/em-andamento":
            chamado["valor"] = True
            return [{"carga": "carga-fake"}]
        return original_chamar(metodo, rota, json)

    monkeypatch.setattr(cliente, "chamar", _rastrear_chamadas)

    contexto = estrategia.criar_contexto()
    estado = cliente.consultar_estado()
    evento = {"tipo": "carga_disponivel", "dados": {"carga": "carga-teste"}}
    estrategia.passo(cliente, estado, [evento], contexto)

    assert chamado["valor"] is True
