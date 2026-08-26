from centrais.missao.orquestrador import executar as executar_missao


def executar_avaliacao(cliente, limite_de_ciclos: int) -> None:
    # TODO(time): plugar aqui as demais centrais (extracao, armazenagem,
    # transporte, pesquisa) quando expuserem uma funcao "passo por ciclo"
    # compativel com este mesmo `cliente`. Hoje so a Missao roda.
    executar_missao(cliente, limite_de_ciclos)
