from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass

import httpx

BASE_URL = "http://localhost:8000"

MINERAIS = {
    "hematita": {
        "valor": 5.0,
        "raridade": 0.10,
        "taxa_degradacao": 0.20,
        "sensibilidade_transporte": 0.10,
    },
    "silica_de_alta_pureza": {
        "valor": 20.0,
        "raridade": 0.30,
        "taxa_degradacao": 0.40,
        "sensibilidade_transporte": 0.30,
    },
    "jarosita": {
        "valor": 35.0,
        "raridade": 0.60,
        "taxa_degradacao": 0.70,
        "sensibilidade_transporte": 0.60,
    },
    "gelo_de_agua": {
        "valor": 40.0,
        "raridade": 0.50,
        "taxa_degradacao": 0.90,
        "sensibilidade_transporte": 0.50,
    },
    "cristal_marciano_raro": {
        "valor": 200.0,
        "raridade": 0.95,
        "taxa_degradacao": 0.30,
        "sensibilidade_transporte": 0.40,
    },
}

MODOS = {
    "economico": {
        "mult_energia": 0.85,
        "mult_duracao": 2.0,
        "mult_degradacao": 2.5,
    },
    "normal": {
        "mult_energia": 1.0,
        "mult_duracao": 1.0,
        "mult_degradacao": 1.0,
    },
    "rapido": {
        "mult_energia": 1.05,
        "mult_duracao": 0.5,
        "mult_degradacao": 0.5,
    },
}

# Pesos simples para transformar energia/desgaste em uma penalidade comparável.
# Não precisam ser "perfeitos": servem para escolher rotas de forma consistente.
PESO_ENERGIA = 2.0
PESO_DESGASTE = 4.0


@dataclass
class Plano:
    carga: str
    mineral: str
    quantidade: float
    unidade: str
    rota: str
    perfil_rota: str
    modo: str
    duracao: int
    perda_qualidade_estimada: float
    energia_estimada: float
    desgaste_estimado: float
    valor_bruto: float
    valor_perdido_estimado: float
    custo_score: float


class CentralTransporte:
    def __init__(self, base_url: str = BASE_URL):
        self.cliente = httpx.Client(base_url=base_url, timeout=5.0)
        # Balanceia o uso dos dois veículos durante a execução deste script.
        self.usos = {"transportadora-1": 0, "transportadora-2": 0}
        self.reservadas: set[str] = set()

    def fechar(self) -> None:
        self.cliente.close()

    def _get(self, rota: str, **kwargs):
        resposta = self.cliente.get(rota, **kwargs)
        resposta.raise_for_status()
        return resposta.json()

    def _post(self, rota: str, payload: dict):
        resposta = self.cliente.post(rota, json=payload)
        resposta.raise_for_status()
        return resposta.json()

    def buscar_carga(self, carga_id: str) -> dict:
        cargas = self._get("/transporte/cargas-disponiveis")
        for carga in cargas:
            if carga["identificador"] == carga_id:
                return carga
        raise ValueError(f"Carga {carga_id!r} não encontrada.")

    def escolher_unidade(self) -> str:
        unidades = self._get("/transporte/transportadores")
        disponiveis = [
            u["identificador"]
            for u in unidades
            if u.get("estado") == "disponivel"
            and u["identificador"] not in self.reservadas
        ]

        if not disponiveis:
            raise RuntimeError("Nenhuma transportadora disponível agora.")

        # Usa primeiro a menos utilizada para preservar desgaste de longo prazo.
        return min(disponiveis, key=lambda u: self.usos.get(u, 0))

    def _avaliar(self, carga: dict, rota: dict, modo: str, unidade: str) -> Plano:
        dados_mineral = MINERAIS[carga["mineral"]]
        dados_modo = MODOS[modo]

        duracao = max(
            1,
            round(rota["tempo_base"] * dados_modo["mult_duracao"]),
        )

        # Replica a parte importante da degradação usada pelo simulador:
        # taxa mineral × sensibilidade ao transporte × raridade × modo × rota × ciclos.
        fator_raridade = 1.0 + dados_mineral["raridade"] * 30.0

        perda_por_ciclo = (
            dados_mineral["taxa_degradacao"]
            * dados_mineral["sensibilidade_transporte"]
            * fator_raridade
            * dados_modo["mult_degradacao"]
            * rota["multiplicador_degradacao"]
        )

        perda_total = min(100.0, perda_por_ciclo * duracao)

        valor_bruto = carga["quantidade"] * dados_mineral["valor"]
        valor_perdido = valor_bruto * (perda_total / 100.0)

        energia = rota["custo_energia_base"] * dados_modo["mult_energia"]

        desgaste = (
            1.0
            / dados_modo["mult_duracao"]
            * rota["multiplicador_desgaste"]
        )

        # Menor score = melhor opção.
        custo_score = (
            valor_perdido
            + energia * PESO_ENERGIA
            + desgaste * PESO_DESGASTE
        )

        return Plano(
            carga=carga["identificador"],
            mineral=carga["mineral"],
            quantidade=carga["quantidade"],
            unidade=unidade,
            rota=rota["identificador"],
            perfil_rota=rota["perfil"],
            modo=modo,
            duracao=duracao,
            perda_qualidade_estimada=perda_total,
            energia_estimada=energia,
            desgaste_estimado=desgaste,
            valor_bruto=valor_bruto,
            valor_perdido_estimado=valor_perdido,
            custo_score=custo_score,
        )

    def planejar(self, carga_id: str) -> Plano:
        carga = self.buscar_carga(carga_id)

        if carga["mineral"] not in MINERAIS:
            raise ValueError(f"Mineral desconhecido: {carga['mineral']}")

        if carga["quantidade"] > 100:
            raise ValueError(
                "Carga acima da capacidade das transportadoras (100)."
            )

        unidade = self.escolher_unidade()

        planejamento = self._get(
            "/transporte/planejar-transporte",
            params={"identificador_da_carga": carga_id},
        )

        ids_validos = set(planejamento["rotas_disponiveis"])
        rotas = [
            r
            for r in self._get("/transporte/rotas")
            if r["identificador"] in ids_validos
            and r.get("condicao") == "livre"
            and r["capacidade_maxima"] >= carga["quantidade"]
        ]

        if not rotas:
            raise RuntimeError("Nenhuma rota válida para esta carga.")

        candidatos: list[Plano] = []

        for rota in rotas:
            for modo in MODOS:
                # Evita econômico para materiais importantes/sensíveis.
                if (
                    modo == "economico"
                    and carga["mineral"] != "hematita"
                ):
                    continue

                candidatos.append(
                    self._avaliar(carga, rota, modo, unidade)
                )

        if not candidatos:
            raise RuntimeError("Nenhuma combinação rota/modo disponível.")

        return min(candidatos, key=lambda p: p.custo_score)

    def energia_transporte(self) -> float:
        estado = self._get("/missao/estado")
        return float(estado["energia"]["transporte"])

    def executar(self, plano: Plano) -> None:
        saldo = self.energia_transporte()

        # Margem porque o servidor encarece a viagem conforme desgaste real
        # da unidade, que não aparece em GET /transportadores.
        energia_com_margem = plano.energia_estimada * 1.50

        if saldo < energia_com_margem:
            falta = math.ceil(energia_com_margem - saldo)
            raise RuntimeError(
                f"Energia de Transporte possivelmente insuficiente. "
                f"Saldo={saldo:.2f}. Peça pelo menos +{falta} à Central de Missão."
            )

        # Só pede autorização quando rota/unidade/modo já estão definidos.
        autorizacao = self._post(
            "/missao/autorizar-missao",
            {
                "operacao": "iniciar_viagem",
                "central_solicitante": "transporte",
                "classe": "rapida",
            },
        )["id_autorizacao"]

        self.reservadas.add(plano.unidade)

        try:
            self._post(
                "/transporte/carregar",
                {
                    "identificador_da_unidade": plano.unidade,
                    "identificador_da_carga": plano.carga,
                },
            )

            self._post(
                "/transporte/iniciar-viagem",
                {
                    "identificador_da_unidade": plano.unidade,
                    "identificador_da_rota": plano.rota,
                    "identificador_da_carga": plano.carga,
                    "id_autorizacao": autorizacao,
                    "modo": plano.modo,
                },
            )

            self.usos[plano.unidade] = self.usos.get(plano.unidade, 0) + 1

        except Exception:
            self.reservadas.discard(plano.unidade)
            raise

    def concluir(self, unidade: str, carga: str) -> None:
        # Use somente depois de receber transporte_concluido.
        self._post(
            "/transporte/descarregar",
            {
                "identificador_da_unidade": unidade,
                "identificador_da_carga": carga,
            },
        )
        self._post(
            "/transporte/retornar-unidade",
            {"identificador_da_unidade": unidade},
        )
        self.reservadas.discard(unidade)


def imprimir_plano(plano: Plano) -> None:
    print("\n=== MELHOR PLANO DE TRANSPORTE ===")
    print(f"Carga:       {plano.carga}")
    print(f"Mineral:     {plano.mineral}")
    print(f"Quantidade:  {plano.quantidade}")
    print(f"Unidade:     {plano.unidade}")
    print(f"Rota:        {plano.rota} ({plano.perfil_rota})")
    print(f"Modo:        {plano.modo}")
    print(f"Duração:     ~{plano.duracao} ciclos")
    print(f"Energia:     ~{plano.energia_estimada:.2f}")
    print(f"Desgaste:    ~{plano.desgaste_estimado:.2f}")
    print(
        f"Perda estimada de qualidade no trajeto: "
        f"~{plano.perda_qualidade_estimada:.2f} pontos"
    )
    print(f"Valor bruto: {plano.valor_bruto:.2f}")
    print(
        f"Valor potencial perdido no trajeto: "
        f"~{plano.valor_perdido_estimado:.2f}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Planejador otimizado da Central de Transporte"
    )
    parser.add_argument(
        "carga",
        help="ID da carga, por exemplo carga-1",
    )
    parser.add_argument(
        "--executar",
        action="store_true",
        help="Além de planejar, pede autorização, carrega e inicia a viagem.",
    )
    parser.add_argument(
        "--concluir-unidade",
        help="Depois de transporte_concluido, descarrega a carga e libera esta unidade.",
    )
    parser.add_argument(
        "--url",
        default=BASE_URL,
        help=f"URL da API (padrão: {BASE_URL})",
    )

    args = parser.parse_args()

    central = CentralTransporte(args.url)

    try:
        if args.concluir_unidade:
            central.concluir(args.concluir_unidade, args.carga)
            print(
                f"\nDescarga de {args.carga} e retorno de "
                f"{args.concluir_unidade} enviados."
            )
            return

        plano = central.planejar(args.carga)
        imprimir_plano(plano)

        if args.executar:
            central.executar(plano)
            print(
                "\nComandos enviados. Agora aguarde/processe os ciclos e "
                "confirme o evento 'transporte_concluido' antes de descarregar."
            )

    except (httpx.HTTPError, ValueError, RuntimeError) as erro:
        print(f"\nERRO: {erro}")
        sys.exit(1)

    finally:
        central.fechar()


if __name__ == "__main__":
    main()
