import json
import requests
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

BASE_URL = "http://localhost:8000"
MEU_WEBHOOK_URL = "http://localhost:9000/webhooks/eventos"

# 1. Configurações da Fila e Memória
PRIORIDADE_MINERAL = {
    "cristal_marciano_raro": 3,
    "gelo_de_agua": 1,
    "jarosita": 2,
    "silica_de_alta_pureza": 4,
    "hematita": 5
}

fila_pesquisa = []
pesquisador_ocupado = False

# NOSSO CADERNINHO DE MEMÓRIA: Guarda qual mineral tem em cada jazida
memoria_jazidas = {} 

# ==========================================
# LÓGICA DO PESQUISADOR
# ==========================================

def processar_fila():
    """Tenta enviar a primeira carga da fila para análise, se o slot estiver livre."""
    global pesquisador_ocupado
    
    if not pesquisador_ocupado and len(fila_pesquisa) > 0:
        prioridade, carga_id = fila_pesquisa.pop(0)
        print(f"\n🔬 [PESQUISA] Iniciando análise rápida da carga: {carga_id}")
        
        resposta = requests.post(f"{BASE_URL}/pesquisa/iniciar-analise", json={
            "identificador_da_carga": carga_id,
            "tipo_de_analise": "rapida"
        })
        
        if resposta.ok:
            pesquisador_ocupado = True
        else:
            print(f"⚠️ [ERRO] Falha ao iniciar análise. O laboratório já estava ocupado.")
            fila_pesquisa.insert(0, (prioridade, carga_id)) # Devolve pro topo da fila

def tratar_analise_concluida(carga_id):
    """Executa o funil de Qualidade -> Aprovação -> Venda."""
    global pesquisador_ocupado
    print(f"\n✅ [PESQUISA] Análise da {carga_id} terminou. Verificando qualidade...")

    res_class = requests.post(f"{BASE_URL}/pesquisa/classificar-carga", json={"identificador_da_carga": carga_id})
    if not res_class.ok:
        return
    
    qualidade = res_class.json().get("qualidade", 0)
    print(f"📊 [QUALIDADE] Nota da carga {carga_id}: {qualidade}")

    if qualidade < 40.0:
        print(f"🗑️ [DESCARTE] Qualidade péssima. Rejeitando {carga_id}.")
        requests.post(f"{BASE_URL}/pesquisa/rejeitar-carga", json={"identificador_da_carga": carga_id})
    else:
        print(f"👍 [APROVAÇÃO] Aprovando {carga_id} na política comercial.")
        requests.post(f"{BASE_URL}/pesquisa/aprovar-carga", json={
            "identificador_da_carga": carga_id,
            "politica": "comercial"
        })

        print("💰 [VENDA] Pedindo autorização da Missão...")
        res_auth = requests.post(f"{BASE_URL}/missao/autorizar-missao", json={
            "operacao": "preparar_distribuicao",
            "central_solicitante": "pesquisa",
            "classe": "rapida"
        })
        
        if res_auth.ok:
            id_auth = res_auth.json().get("id_autorizacao")
            requests.post(f"{BASE_URL}/pesquisa/preparar-distribuicao", json={
                "identificador_da_carga": carga_id,
                "id_autorizacao": id_auth
            })
            print(f"🚀 [SUCESSO] Carga {carga_id} distribuída!")

    pesquisador_ocupado = False
    processar_fila()

# ==========================================
# SERVIDOR DE EVENTOS (WEBHOOKS)
# ==========================================

class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        tamanho = int(self.headers.get("Content-Length", "0"))
        corpo = self.rfile.read(tamanho)
        evento = json.loads(corpo.decode("utf-8"))

        tipo_evento = evento.get("tipo")
        dados = evento.get("dados", {})

        # 1. Quando o laboratório descobre o que tem na jazida:
        if tipo_evento == "sondagem_de_jazida_concluida":
            jazida_id = dados.get("jazida")
            estimativa = dados.get("estimativa_de_composicao", {})
            
            if estimativa:
                # Pega a primeira chave do dicionário (ex: "hematita" de {"hematita": "alta"})
                mineral = list(estimativa.keys())[0]
                memoria_jazidas[jazida_id] = mineral
                print(f"🗺️ [MEMÓRIA] Anotado: A {jazida_id} contém {mineral}!")

        # 2. Quando a carga finalmente sai da terra:
        elif tipo_evento == "extracao_concluida":
            carga_id = dados.get("carga")
            jazida_id = dados.get("jazida")
            
            # O bot olha no caderninho para saber o mineral. Se não souber, anota "desconhecido"
            mineral_da_carga = memoria_jazidas.get(jazida_id, "desconhecido")
            prioridade = PRIORIDADE_MINERAL.get(mineral_da_carga, 99)
            
            fila_pesquisa.append((prioridade, carga_id))
            fila_pesquisa.sort()
            
            print(f"📦 [NOVA CARGA] {carga_id} ({mineral_da_carga}) entrou na fila. Prioridade: {prioridade}")
            processar_fila()

        # 3. Quando o laboratório termina a análise:
        elif tipo_evento == "analise_concluida":
            carga_id = dados.get("carga")
            tratar_analise_concluida(carga_id)

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format, *args):
        pass # Desativa os logs poluentes no terminal

def iniciar_servidor_webhooks():
    servidor = HTTPServer(("0.0.0.0", 9000), WebhookHandler)
    print("🎧 Bot escutando o jogo na porta 9000...")
    servidor.serve_forever()

# ==========================================
# INÍCIO DO SCRIPT
# ==========================================

if __name__ == "__main__":
    thread_servidor = threading.Thread(target=iniciar_servidor_webhooks, daemon=True)
    thread_servidor.start()

    print("\nRegistrando o bot na Missão...")
    try:
        requests.post(f"{BASE_URL}/missao/registrar-webhook", json={"url": MEU_WEBHOOK_URL})
        print("✅ Bot registrado! O laboratório está pronto para trabalhar.\n")
    except requests.exceptions.ConnectionError:
        print("❌ ERRO: O jogo (porta 8000) não está rodando.")
        exit()

    while True:
        time.sleep(1)
