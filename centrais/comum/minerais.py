from __future__ import annotations

CATALOGO: dict[str, dict[str, float]] = {
    "hematita": {"valor_por_unidade": 5.0, "raridade": 0.1},
    "silica_de_alta_pureza": {"valor_por_unidade": 20.0, "raridade": 0.3},
    "jarosita": {"valor_por_unidade": 35.0, "raridade": 0.6},
    "gelo_de_agua": {"valor_por_unidade": 40.0, "raridade": 0.5},
    "cristal_marciano_raro": {"valor_por_unidade": 200.0, "raridade": 0.95},
}
LIMIAR_DE_RARIDADE_PARA_PRESERVACAO = 0.5


def valor_por_unidade(mineral: str) -> float:
    return CATALOGO.get(mineral, {}).get("valor_por_unidade", 0.0)


def raridade(mineral: str) -> float:
    return CATALOGO.get(mineral, {}).get("raridade", 0.0)


def e_valioso(mineral: str) -> bool:
    return raridade(mineral) >= LIMIAR_DE_RARIDADE_PARA_PRESERVACAO
