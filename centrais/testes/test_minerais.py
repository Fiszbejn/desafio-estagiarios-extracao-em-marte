from centrais.comum.minerais import e_valioso, raridade, valor_por_unidade


def test_hematita_e_barata_e_comum():
    assert valor_por_unidade("hematita") == 5.0
    assert raridade("hematita") == 0.1
    assert e_valioso("hematita") is False


def test_cristal_marciano_raro_e_valioso():
    assert valor_por_unidade("cristal_marciano_raro") == 200.0
    assert raridade("cristal_marciano_raro") == 0.95
    assert e_valioso("cristal_marciano_raro") is True


def test_mineral_desconhecido_nao_quebra():
    assert valor_por_unidade("mineral_inexistente") == 0.0
    assert e_valioso("mineral_inexistente") is False
