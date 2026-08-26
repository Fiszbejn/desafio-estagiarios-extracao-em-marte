import json
import requests
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer


BASE_URL = "http://localhost:8000"
MEU_WEBHOOK_URL = "http://localhost:9000/webhooks/eventos"


# ==========================================
# CONFIGURAÇÕES DA EXTRAÇÃO
# ==========================================

# Quanto menor o número, maior a prioridade.
PRIORIDADE_MINERAL = {
    "hematita": 1,
    "cristal_marciano_raro": 2,
    "jarosita": 3,
    "silica_de_alta_pureza": 4,
    "gelo_de_agua": 5,
}


# Mineradoras:
# - leve: rápida, capacidade 35
# - precisa: mais lenta, capacidade 25
#
# Para minerais valiosos, damos preferência à precisa.
# Para minerais comuns, damos preferência à leve.
PREFERENCIA_MINERADORA = {
    "hematita": "precisa",
    "cristal_marciano_raro": "precisa",
    "jarosita": "leve",
    "silica_de_alta_pureza": "precisa",
    "gelo_de_agua": "leve",
}


fila_extracao = []
operacoes_ativas = {}


# ==========================================
# CONSULTAS À CENTRAL
# ==========================================

def consultar_jazidas():
    """Retorna as jazidas disponíveis."""
    resposta = requests.get(
        f"{BASE_URL}/extracao/jazidas",
        timeout=5
    )

    resposta.raise_for_status()

    return resposta.json()


def consultar_mineradoras():
    """Retorna as mineradoras disponíveis."""
    resposta = requests.get(
        f"{BASE_URL}/extracao/mineradoras",
        timeout=5
    )

    resposta.raise_for_status()

    return resposta.json()


# ==========================================
# ESCOLHA DE RECURSOS
# ==========================================

def escolher_jazida(jazidas):
    """
    Escolhe a jazida com maior prioridade de mineral.

    Entre minerais iguais, escolhe a jazida com maior
    quantidade disponível.
    """

    disponiveis = [
        jazida
        for jazida in jazidas
        if jazida.get("estado") == "disponivel"
        and jazida.get("quantidade_disponivel", 0) > 0
    ]

    if not disponiveis:
        return None

    disponiveis.sort(
        key=lambda jazida: (
            PRIORIDADE_MINERAL.get(
                jazida.get("mineral"),
                99
            ),
            -jazida.get("quantidade_disponivel", 0)
        )
    )

    return disponiveis[0]


def escolher_mineradora(mineral, mineradoras):
    """
    Escolhe uma mineradora disponível compatível com o mineral.

    Minerais valiosos -> mineradora precisa.
    Minerais comuns -> mineradora leve.
    """

    disponiveis = [
        mineradora
        for mineradora in mineradoras
        if mineradora.get("estado") == "disponivel"
    ]

    if not disponiveis:
        return None

    tipo_preferido = PREFERENCIA_MINERADORA.get(
        mineral,
        "leve"
    )

    preferidas = [
        mineradora
        for mineradora in disponiveis
        if mineradora.get("tipo") == tipo_preferido
    ]

    if preferidas:
        return max(
            preferidas,
            key=lambda mineradora:
                mineradora.get("capacidade", 0)
        )

    # Caso a mineradora preferida não esteja disponível,
    # usa qualquer outra mineradora disponível.
    return max(
        disponiveis,
        key=lambda mineradora:
            mineradora.get("capacidade", 0)
    )


# ==========================================
# INICIAR EXTRAÇÃO
# ==========================================

def iniciar_extracao(jazida, mineradora):
    """
    Envia uma ordem de extração para a central.
    """

    jazida_id = jazida["identificador"]
    mineradora_id = mineradora["identificador"]

    mineral = jazida.get("mineral", "desconhecido")

    capacidade = mineradora.get("capacidade", 0)
    quantidade_disponivel = jazida.get(
        "quantidade_disponivel",
        0
    )

    quantidade = min(
        capacidade,
        quantidade_disponivel
    )

    if quantidade <= 0:
        return False

    # Minerais valiosos recebem uma extração mais cuidadosa.
    if mineral in (
        "hematita",
        "cristal_marciano_raro",
        "silica_de_alta_pureza"
    ):
        modo = "cuidadoso"
        perfil = "mapeadora"
    else:
        modo = "normal"
        perfil = "superficial"

    payload = {
        "identificador_da_unidade": mineradora_id,
        "identificador_da_jazida": jazida_id,
        "quantidade": quantidade,
        "modo": modo,
        "perfil_de_escavacao": perfil,
    }

    print(
        f"\n⛏️ [EXTRAÇÃO] Enviando operação:"
        f"\n   Jazida: {jazida_id}"
        f"\n   Mineral: {mineral}"
        f"\n   Mineradora: {mineradora_id}"
        f"\n   Quantidade: {quantidade}"
        f"\n   Modo: {modo}"
        f"\n   Perfil: {perfil}"
    )

    resposta = requests.post(
        f"{BASE_URL}/extracao/iniciar-extracao",
        json=payload,
        timeout=5
    )

    if resposta.ok and resposta.json().get("aceito"):
        operacoes_ativas[mineradora_id] = {
            "jazida": jazida_id,
            "mineral": mineral,
            "quantidade": quantidade,
        }

        print(
            f"✅ [EXTRAÇÃO] Operação aceita "
            f"para {mineradora_id}."
        )

        return True

    print(
        "⚠️ [ERRO] A central recusou a operação."
    )

    return False


# ==========================================
# PROCESSAMENTO DA FILA
# ==========================================

def processar_fila():
    """
    Tenta executar as próximas operações enquanto
    existirem mineradoras disponíveis.
    """

    if not fila_extracao:
        return

    try:
        mineradoras = consultar_mineradoras()
    except requests.RequestException as erro:
        print(
            f"⚠️ [ERRO] Não foi possível consultar "
            f"as mineradoras: {erro}"
        )
        return

    disponiveis = [
        mineradora
        for mineradora in mineradoras
        if mineradora.get("estado") == "disponivel"
    ]

    while fila_extracao and disponiveis:
        operacao = fila_extracao.pop(0)

        jazida = operacao["jazida"]
        mineral = jazida.get("mineral", "desconhecido")

        mineradora = escolher_mineradora(
            mineral,
            disponiveis
        )

        if mineradora is None:
            fila_extracao.insert(0, operacao)
            break

        sucesso = iniciar_extracao(
            jazida,
            mineradora
        )

        if sucesso:
            disponiveis.remove(mineradora)
        else:
            fila_extracao.insert(0, operacao)
            break


# ==========================================
# DESCOBRIR NOVAS OPERAÇÕES
# ==========================================

def atualizar_fila():
    """
    Consulta as jazidas disponíveis e coloca operações
    novas na fila.
    """

    try:
        jazidas = consultar_jazidas()
    except requests.RequestException as erro:
        print(
            f"⚠️ [ERRO] Não foi possível consultar "
            f"as jazidas: {erro}"
        )
        return

    # Ignora jazidas que já possuem uma extração ativa.
    jazidas_em_operacao = {
        operacao["jazida"]
        for operacao in operacoes_ativas.values()
    }

    novas_operacoes = []

    for jazida in jazidas:
        jazida_id = jazida.get("identificador")

        if jazida.get("estado") != "disponivel":
            continue

        if jazida_id in jazidas_em_operacao:
            continue

        if jazida.get("quantidade_disponivel", 0) <= 0:
            continue

        # Evita inserir a mesma jazida várias vezes.
        ja_na_fila = any(
            item["jazida"]["identificador"] == jazida_id
            for item in fila_extracao
        )

        if ja_na_fila:
            continue

        novas_operacoes.append({
            "jazida": jazida
        })

    fila_extracao.extend(novas_operacoes)

    # Ordena pela prioridade do mineral.
    fila_extracao.sort(
        key=lambda operacao: (
            PRIORIDADE_MINERAL.get(
                operacao["jazida"].get("mineral"),
                99
            ),
            -operacao["jazida"].get(
                "quantidade_disponivel",
                0
            )
        )
    )

    for operacao in novas_operacoes:
        jazida = operacao["jazida"]

        mineral = jazida.get(
            "mineral",
            "desconhecido"
        )

        prioridade = PRIORIDADE_MINERAL.get(
            mineral,
            99
        )

        print(
            f"📦 [FILA] Jazida "
            f"{jazida['identificador']} "
            f"({mineral}) entrou na fila. "
            f"Prioridade: {prioridade}"
        )

    processar_fila()


# ==========================================
# TRATAMENTO DE CONCLUSÃO
# ==========================================

def tratar_extracao_concluida(dados):
    """
    Trata o evento extracao_concluida.
    """

    carga_id = dados.get("carga")
    jazida_id = dados.get("jazida")
    mineradora_id = dados.get("unidade")

    quantidade = dados.get("quantidade", 0)
    desgaste = dados.get(
        "desgaste_da_unidade",
        0
    )

    operacao = operacoes_ativas.pop(
        mineradora_id,
        None
    )

    mineral = (
        operacao.get("mineral")
        if operacao
        else "desconhecido"
    )

    print(
        f"\n✅ [EXTRAÇÃO CONCLUÍDA]"
        f"\n   Carga: {carga_id}"
        f"\n   Jazida: {jazida_id}"
        f"\n   Mineral: {mineral}"
        f"\n   Unidade: {mineradora_id}"
        f"\n   Quantidade: {quantidade}"
        f"\n   Desgaste: {desgaste}"
    )

    print(
        "📦 [CARGA] A carga foi criada e pode agora "
        "seguir para Transporte, Armazenagem e Pesquisa."
    )

    # A unidade ficou em "aguardando".
    # Solicitamos o retorno para a base.
    retornar_mineradora(mineradora_id)

    # Tenta iniciar outra operação.
    processar_fila()


# ==========================================
# RETORNO DA MINERADORA
# ==========================================

def retornar_mineradora(mineradora_id):
    """
    Solicita o retorno da mineradora para a base.
    """

    print(
        f"↩️ [RETORNO] Solicitando retorno "
        f"da {mineradora_id}..."
    )

    resposta = requests.post(
        f"{BASE_URL}/extracao/retornar-unidade",
        json={
            "identificador_da_unidade":
                mineradora_id
        },
        timeout=5
    )

    if resposta.ok and resposta.json().get("aceito"):
        print(
            f"✅ [RETORNO] {mineradora_id} "
            f"retornará para a base."
        )
    else:
        print(
            f"⚠️ [ERRO] Não foi possível "
            f"retornar {mineradora_id}."
        )


# ==========================================
# TRATAMENTO DE INTERRUPÇÃO
# ==========================================

def tratar_extracao_interrompida(dados):
    """
    Trata o evento extracao_interrompida.
    """

    mineradora_id = dados.get("unidade")
    jazida_id = dados.get("jazida")

    operacoes_ativas.pop(
        mineradora_id,
        None
    )

    print(
        f"\n🛑 [EXTRAÇÃO INTERROMPIDA]"
        f"\n   Unidade: {mineradora_id}"
        f"\n   Jazida: {jazida_id}"
    )

    # Tenta reutilizar a mineradora.
    processar_fila()


# ==========================================
# SERVIDOR DE WEBHOOKS
# ==========================================

class WebhookHandler(BaseHTTPRequestHandler):

    def do_POST(self):

        try:
            tamanho = int(
                self.headers.get(
                    "Content-Length",
                    "0"
                )
            )

            corpo = self.rfile.read(tamanho)

            evento = json.loads(
                corpo.decode("utf-8")
            )

            tipo_evento = evento.get("tipo")
            dados = evento.get("dados", {})

            print(
                f"\n📡 [EVENTO] Recebido: "
                f"{tipo_evento}"
            )

            if tipo_evento == "extracao_concluida":
                tratar_extracao_concluida(
                    dados
                )

            elif tipo_evento == "extracao_interrompida":
                tratar_extracao_interrompida(
                    dados
                )

            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        except Exception as erro:

            print(
                f"❌ [WEBHOOK] Erro ao processar evento: "
                f"{erro}"
            )

            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"erro")

    def log_message(self, format, *args):
        # Desativa logs automáticos do HTTPServer.
        pass


def iniciar_servidor_webhooks():

    servidor = HTTPServer(
        ("0.0.0.0", 9000),
        WebhookHandler
    )

    print(
        "🎧 Bot escutando eventos "
        "na porta 9000..."
    )

    servidor.serve_forever()


# ==========================================
# LOOP DE MONITORAMENTO
# ==========================================

def loop_extracao():

    while True:

        try:
            atualizar_fila()

        except requests.exceptions.ConnectionError:
            print(
                "❌ [ERRO] A Central de Extração "
                "não está disponível."
            )

        except Exception as erro:
            print(
                f"⚠️ [ERRO] Monitoramento: {erro}"
            )

        time.sleep(5)


# ==========================================
# INÍCIO DO SCRIPT
# ==========================================

if __name__ == "__main__":

    # Servidor de webhook.
    thread_servidor = threading.Thread(
        target=iniciar_servidor_webhooks,
        daemon=True
    )

    thread_servidor.start()

    print(
        "\n⛏️ Inicializando bot da "
        "Central de Extração..."
    )

    # Testa a conexão.
    try:
        resposta = requests.get(
            f"{BASE_URL}/extracao/mineradoras",
            timeout=5
        )

        resposta.raise_for_status()

        print(
            "✅ Central de Extração encontrada."
        )

    except requests.exceptions.ConnectionError:

        print(
            "❌ ERRO: A Central de Extração "
            "(porta 8000) não está rodando."
        )

        exit()

    # Registra o webhook na Missão.
    try:

        resposta = requests.post(
            f"{BASE_URL}/missao/registrar-webhook",
            json={
                "url": MEU_WEBHOOK_URL
            },
            timeout=5
        )

        if resposta.ok:
            print(
                "✅ Webhook registrado na Missão."
            )
        else:
            print(
                "⚠️ Não foi possível registrar "
                "o webhook."
            )

    except requests.RequestException as erro:

        print(
            f"⚠️ Erro ao registrar webhook: {erro}"
        )

    print(
        "✅ Bot de extração pronto.\n"
    )

    # Primeira sincronização.
    atualizar_fila()

    # Mantém o bot rodando.
    loop_extracao()