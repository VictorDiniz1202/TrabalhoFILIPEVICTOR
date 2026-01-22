import os
import asyncio
import json
import re
import requests
import uuid
import logging
from pathlib import Path
from datetime import date, datetime

# ✅ 1. Importação do Stripe e Google Auth
import stripe
from google_auth_oauthlib.flow import Flow # <--- IMPORTANTE PARA O LOGIN

from fastapi import FastAPI, Form, Response, Request, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from twilio.twiml.messaging_response import MessagingResponse
from dotenv import load_dotenv
from openai import OpenAI

# --- SEUS MÓDULOS LOCAIS ---
from logger_config import Log
from gerenciador_precos import carregar_precos, salvar_precos, atualizar_um_preco, get_texto_tabela
from agenda_google import listar_proximos_eventos, criar_evento_agenda, autenticar_google
from personas import system_prompt, get_director_prompt
from GeradorDeVideo import criar_video_wan, animar_foto_wan

# --- GERENCIADOR DE CLIENTES (SaaS) ---
from gerenciador_clientes import (
    registrar_cliente, autenticar_cliente, buscar_cliente_por_telefone, 
    atualizar_dados_cliente, ativar_pagamento_cliente,
    adicionar_creditos_video, descontar_credito_video,
    salvar_agendamento_interno, listar_agenda_interna
)

# --- CONFIGURAÇÃO INICIAL ---
load_dotenv()

# Configura Stripe
stripe.api_key = os.getenv("STRIPE_API_KEY")

# Configuração de Logs
log_setup = Log("BotLog")
logger = log_setup.get_logger("MainAPI")

# ✅ Permite HTTP para testes locais do Google (Oauth)
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

app = FastAPI(title="API Victor AI - Backend SaaS")

# 1. CORS
origins = [
    "http://localhost:5173",
    "http://localhost:3000",
    "*" 
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. CLIENTE AI (GROQ / OPENAI)
try:
    client = OpenAI(
        api_key=os.getenv("GROQ_API_KEY"),
        base_url="https://api.groq.com/openai/v1"
    )
except Exception as e:
    logger.critical(f"Erro Client AI: {e}")

# 3. VARIÁVEIS DE AMBIENTE E PASTAS
ADMINS = [num.strip() for num in os.getenv("ADMIN_NUMBERS", "").split(",") if num]
PASTA_IMAGENS = Path("imagens_recebidas")
PASTA_IMAGENS.mkdir(exist_ok=True)

# --- MODELOS DE DADOS (Pydantic) ---

class LoginData(BaseModel):
    email: str
    password: str

class RegisterData(BaseModel):
    email: str
    password: str
    phone: str
    nome_barbearia: str
    nome_bot: str
    tipo_agenda: str = "interna" 

class PriceUpdate(BaseModel):
    corte: float
    barba: float
    combo: float
    sobrancelha: float
    email_dono: Optional[str] = None 

class TeamUpdate(BaseModel):
    email_dono: str
    equipe: List[dict] 

class VideoGenRequest(BaseModel):
    prompt: str
    tipo: str = "texto"
    image_url: Optional[str] = None
    email_user: Optional[str] = None 

# --- FUNÇÕES AUXILIARES ---
def salvar_imagem_localmente(url_imagem: str) -> Optional[str]:
    try:
        nome_arquivo = f"wpp_{uuid.uuid4().hex[:8]}.jpg"
        caminho_completo = PASTA_IMAGENS / nome_arquivo
        logger.info(f"Baixando imagem: {url_imagem}")
        resposta = requests.get(url_imagem, timeout=10)
        if resposta.status_code == 200:
            with open(caminho_completo, "wb") as f:
                f.write(resposta.content)
            return str(caminho_completo)
    except Exception as e:
        logger.error(f"Erro download imagem: {e}")
    return None

# ==========================================
# ROTAS DE AUTENTICAÇÃO
# ==========================================

@app.post("/api/auth/register")
async def register(data: RegisterData):
    clean_phone = data.phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not clean_phone.startswith("+"): clean_phone = f"+{clean_phone}"
    if "whatsapp:" not in clean_phone: clean_phone = f"whatsapp:{clean_phone}"

    sucesso, info = registrar_cliente(
        data.email, 
        data.password, 
        clean_phone, 
        data.nome_barbearia, 
        data.nome_bot,
        data.tipo_agenda
    )
    
    if not sucesso:
        raise HTTPException(status_code=400, detail=info)
    
    logger.info(f"Novo cliente registrado: {data.email} ({data.nome_barbearia}) - Agenda: {data.tipo_agenda}")
    return {"status": "success", "user": info}

@app.post("/api/auth/login")
async def login(data: LoginData):
    user = autenticar_cliente(data.email, data.password)
    if not user:
        raise HTTPException(status_code=401, detail="E-mail ou senha incorretos")
    return {"status": "success", "user": user}

# ==========================================
# ✅ NOVAS ROTAS: CONEXÃO GOOGLE AGENDA (OAuth2)
# ==========================================
@app.get("/api/auth/google/login")
async def google_login(email_user: str):
    """Gera o link para o usuário autorizar o Google Agenda"""
    try:
        # Verifica se credentials.json existe
        if not os.path.exists('credentials.json'):
            raise HTTPException(status_code=500, detail="Arquivo credentials.json não encontrado no servidor.")

        flow = Flow.from_client_secrets_file(
            'credentials.json',
            scopes=['https://www.googleapis.com/auth/calendar'],
            redirect_uri='http://localhost:8000/api/auth/google/callback'
        )
        
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            state=email_user
        )
        
        return {"url": authorization_url}
    except Exception as e:
        logger.error(f"Erro ao gerar link Google: {e}")
        raise HTTPException(status_code=500, detail=f"Erro Google Auth: {str(e)}")

@app.get("/api/auth/google/callback")
async def google_callback(code: str, state: str):
    """Recebe o código do Google e salva o token"""
    try:
        flow = Flow.from_client_secrets_file(
            'credentials.json',
            scopes=['https://www.googleapis.com/auth/calendar'],
            redirect_uri='http://localhost:8000/api/auth/google/callback'
        )
        
        flow.fetch_token(code=code)
        credentials = flow.credentials
        
        # ✅ SALVA O NOVO TOKEN (Isso corrige o 'invalid_grant')
        with open("token.json", "w") as token_file:
            token_file.write(credentials.to_json())
        
        logger.info(f"Token Google renovado com sucesso para: {state}")
                
        # Redireciona de volta para o site
        return Response(status_code=302, headers={"Location": "http://localhost:5173/equipe?status=google_success"})

    except Exception as e:
        logger.error(f"Erro no callback do Google: {e}")
        return {"error": str(e)}

# ==========================================
# ROTAS DE PAGAMENTO
# ==========================================

@app.post("/api/payment/subscription")
async def checkout_subscription(data: LoginData):
    try:
        if not stripe.api_key or not os.getenv("STRIPE_PRICE_ID_SUBSCRIPTION"):
            logger.warning("Stripe OFF. Simulando ativação de Assinatura.")
            ativar_pagamento_cliente(data.email)
            return {"status": "simulated", "url": "http://localhost:5173/dashboard?sucesso=simulacao_bot"}

        checkout_session = stripe.checkout.Session.create(
            line_items=[{'price': os.getenv("STRIPE_PRICE_ID_SUBSCRIPTION"), 'quantity': 1}],
            mode='subscription',
            success_url="http://localhost:5173/dashboard?sucesso=bot",
            cancel_url="http://localhost:5173/assinatura",
            metadata={"email_cliente": data.email, "tipo": "assinatura_bot"}
        )
        return {"status": "success", "url": checkout_session.url}
    except Exception as e:
        logger.error(f"Erro Stripe Sub: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/payment/buy-credits")
async def checkout_credits(data: LoginData):
    try:
        if not stripe.api_key or not os.getenv("STRIPE_PRICE_ID_CREDITS"):
            logger.warning("Stripe OFF. Simulando compra de créditos.")
            adicionar_creditos_video(data.email, 10)
            return {"status": "simulated", "url": "http://localhost:5173/studio?sucesso=simulacao_creditos"}

        checkout_session = stripe.checkout.Session.create(
            line_items=[{'price': os.getenv("STRIPE_PRICE_ID_CREDITS"), 'quantity': 1}],
            mode='payment',
            success_url="http://localhost:5173/studio?sucesso=creditos",
            cancel_url="http://localhost:5173/studio",
            metadata={
                "email_cliente": data.email, 
                "tipo": "compra_creditos",
                "qtd": 10 
            }
        )
        return {"status": "success", "url": checkout_session.url}
    except Exception as e:
        logger.error(f"Erro Stripe Credits: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/webhook/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get('stripe-signature')
    endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except: return Response(status_code=400)

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        metadata = session.get("metadata", {})
        email = metadata.get("email_cliente")
        tipo_compra = metadata.get("tipo")

        if email:
            if tipo_compra == "assinatura_bot":
                logger.info(f"✅ Assinatura Chatbot ativada: {email}")
                ativar_pagamento_cliente(email)
            elif tipo_compra == "compra_creditos":
                qtd = int(metadata.get("qtd", 10))
                logger.info(f"✅ {qtd} Créditos adicionados: {email}")
                adicionar_creditos_video(email, qtd)

    return {"status": "success"}

# ==========================================
# ROTAS DO DASHBOARD
# ==========================================

@app.get("/api/dashboard/stats")
async def get_stats():
    return {"agendamentos_hoje": 4, "receita_estimada": 350.00, "videos_gerados": 12, "status_sistema": "Online 🟢"}

@app.get("/api/dashboard/logs")
async def get_logs():
    log_lines = []
    try:
        nome_arquivo = log_setup.log_path / f"BotLog_{date.today()}.log"
        if os.path.exists(nome_arquivo):
            with open(nome_arquivo, "r", encoding="utf-8") as f:
                log_lines = f.readlines()[-50:] 
    except Exception as e:
        log_lines = [f"Erro ao ler logs: {str(e)}"]
    return {"logs": log_lines}

@app.get("/api/dashboard/prices")
async def get_prices_api():
    return carregar_precos()

@app.post("/api/dashboard/prices")
async def update_prices_api(novos_precos: PriceUpdate):
    print(f"🔥 RECEBIDO DO DASHBOARD: {novos_precos}")
    dados_dict = novos_precos.model_dump(exclude={"email_dono"})
    sucesso_arquivo = salvar_precos(dados_dict)
    
    if novos_precos.email_dono:
        atualizar_dados_cliente(novos_precos.email_dono, {"precos": dados_dict})

    if sucesso_arquivo:
        return {"status": "success", "message": "Preços atualizados!"}
    else:
        raise HTTPException(status_code=500, detail="Erro ao salvar arquivo JSON")

@app.post("/api/dashboard/team")
async def update_team_api(dados: TeamUpdate):
    sucesso = atualizar_dados_cliente(dados.email_dono, {"equipe": dados.equipe})
    
    if sucesso:
        logger.info(f"Equipe atualizada para {dados.email_dono}: {len(dados.equipe)} membros")
        return {"status": "success"}
    else:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

@app.get("/api/dashboard/agenda")
async def get_agenda_internal_api(email: str):
    from gerenciador_clientes import listar_agenda_interna
    eventos = listar_agenda_interna(email)
    return eventos

@app.get("/api/dashboard/calendar")
async def get_calendar_events():
    try:
        service = autenticar_google()
        agora = datetime.utcnow().isoformat() + "Z"
        events = service.events().list(calendarId="primary", timeMin=agora, maxResults=20, singleEvents=True, orderBy="startTime").execute()
        items = events.get("items", [])
        
        eventos_limpos = []
        for event in items:
            start = event["start"].get("dateTime", event["start"].get("date"))
            eventos_limpos.append({
                "id": event["id"], "title": event["summary"],
                "start": start, "description": event.get("description", "")
            })
        return eventos_limpos
    except Exception as e:
        logger.error(f"Erro calendario API: {e}")
        return []

@app.post("/api/dashboard/generate-video")
async def generate_video_dashboard(req: VideoGenRequest):
    if not req.email_user:
        raise HTTPException(status_code=400, detail="Usuário não identificado.")

    tem_saldo = descontar_credito_video(req.email_user)
    if not tem_saldo:
        raise HTTPException(status_code=402, detail="Sem créditos. Recarregue no Studio.")

    try:
        if req.tipo == "imagem" and req.image_url:
            url = animar_foto_wan(req.image_url, req.prompt)
        else:
            url = criar_video_wan(req.prompt)
        return {"video_url": url}
    except Exception as e:
        adicionar_creditos_video(req.email_user, 1)
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# LÓGICA DO WHATSAPP + AI
# ==========================================

tools_agenda = [
    {
        "type": "function", 
        "function": {
            "name": "verificar_agenda", 
            "description": "Verifica horários disponíveis.", 
            "parameters": {
                "type": "object", 
                "properties": {
                    "nome_barbeiro": {"type": "string", "description": "Nome do barbeiro (opcional)"},
                    "data": {"type": "string", "description": "Data para verificar (AAAA-MM-DD). Opcional."} 
                }
            }
        }
    },
    {
        "type": "function", 
        "function": {
            "name": "agendar_servico", 
            "description": "Agenda serviço.", 
            "parameters": {
                "type": "object", 
                "properties": {
                    "data_hora": {"type": "string"}, 
                    "nome_cliente": {"type": "string"},
                    "nome_barbeiro": {"type": "string", "description": "Nome do barbeiro escolhido (ou Principal)"}
                }, 
                "required": ["data_hora", "nome_cliente"]
            }
        }
    },
    {"type": "function", "function": {"name": "alterar_preco_servico", "description": "ADMIN ONLY. Altera preços.", "parameters": {"type": "object", "properties": {"servico": {"type": "string"}, "novo_valor": {"type": "number"}}, "required": ["servico", "novo_valor"]}}}
]

tools_video = [
    {"type": "function", "function": {"name": "gerar_video_marketing", "description": "Cria vídeo texto.", "parameters": {"type": "object", "properties": {"descricao_ideia": {"type": "string"}}, "required": ["descricao_ideia"]}}},
    {"type": "function", "function": {"name": "animar_foto_cliente", "description": "Anima foto.", "parameters": {"type": "object", "properties": {"url_imagem": {"type": "string"}, "ideia_movimento": {"type": "string"}}, "required": ["url_imagem", "ideia_movimento"]}}}
]

historico_conversas = {}
modos_usuarios = {} 

@app.post("/whatsapp")
async def reply_whatsapp(request: Request):
    try:
        form_data = await request.form()
        Body = form_data.get("Body", "").strip()
        From = form_data.get("From")
        num_media = int(form_data.get("NumMedia", 0))
        media_url = form_data.get("MediaUrl0")

        if not From: return Response("Sender missing")

        cliente_saas = buscar_cliente_por_telefone(From)
        
        if cliente_saas:
            pass # Liberado

        # Define Variáveis Dinâmicas
        if cliente_saas:
            nome_bot = cliente_saas["config"].get("nome_bot", "Assistente")
            nome_barbearia = cliente_saas["config"].get("nome_barbearia", "Barbearia")
            tipo_agenda = cliente_saas["config"].get("tipo_agenda", "interna")
            
            equipe = cliente_saas.get("equipe", [])
            nomes_equipe = ", ".join([m["nome"] for m in equipe])
            
            p = cliente_saas.get("precos", {})
            tabela_atual = f"TABELA {nome_barbearia.upper()}:\n"
            for k, v in p.items(): tabela_atual += f"- {k}: R$ {v}\n"
        else:
            nome_bot = "Victor AI"
            nome_barbearia = "Barbearia Modelo"
            nomes_equipe = "Principal"
            tabela_atual = get_texto_tabela()
            tipo_agenda = "interna"

        eh_admin = (From in ADMINS) or (cliente_saas is not None)

        if Body.lower().startswith("/video"):
            pode_usar_video = eh_admin
            if cliente_saas and not cliente_saas["config"].get("criar_videos", True):
                pode_usar_video = False
            
            if pode_usar_video:
                modos_usuarios[From] = "video"
                Body = Body[6:].strip() or "Modo Diretor."
            else:
                Body = "Seu plano atual não inclui a criação de vídeos."
        
        elif Body.lower().startswith("/barbeiro"):
            modos_usuarios[From] = "barbeiro"
            Body = Body[9:].strip()

        modo_atual = modos_usuarios.get(From, "barbeiro")
        
        if modo_atual == "video" and eh_admin:
            prompt_sistema = get_director_prompt()
            tools_ativas = tools_video
        else:
            prompt_sistema = system_prompt()
            contexto_atual = (
                "[DADOS ATUAIS]\n"
                f"- Nome do bot: {nome_bot}\n"
                f"- Barbearia: {nome_barbearia}\n"
                f"- Profissionais: {nomes_equipe}\n"
                f"- Tipo de agenda: {tipo_agenda}\n"
                f"{tabela_atual}"
            )
            prompt_sistema = f"{prompt_sistema}\n\n{contexto_atual}"
            tools_ativas = tools_agenda
            modos_usuarios[From] = "barbeiro"

        if From not in historico_conversas:
            historico_conversas[From] = []
        
        if len(historico_conversas[From]) > 12:
            historico_conversas[From] = [historico_conversas[From][0]] + historico_conversas[From][-11:]

        if not historico_conversas[From] or historico_conversas[From][0]["role"] != "system":
            historico_conversas[From].insert(0, {"role": "system", "content": prompt_sistema})
        else:
            historico_conversas[From][0]["content"] = prompt_sistema

        conteudo_msg = Body
        if num_media > 0 and media_url and eh_admin:
            local_path = await asyncio.to_thread(salvar_imagem_localmente, media_url)
            if local_path:
                conteudo_msg = f"{Body} [IMAGEM RECEBIDA: {local_path}]"

        historico_conversas[From].append({"role": "user", "content": conteudo_msg})
        logger.info(f"Msg de {From} ({nome_barbearia}): {conteudo_msg}")

        # Chamada AI
        resposta = await asyncio.to_thread(
            client.chat.completions.create,
            model="llama-3.3-70b-versatile",
            messages=historico_conversas[From],
            tools=tools_ativas if tools_ativas else None,
            tool_choice="auto" if tools_ativas else None,
            temperature=0.3
        )
        msg_ia = resposta.choices[0].message
        texto_final = ""

        if msg_ia.tool_calls:
            tool_call = msg_ia.tool_calls[0]
            nome_funcao = tool_call.function.name
            args = json.loads(tool_call.function.arguments)
            logger.info(f"Tool: {nome_funcao} | Args: {args}")
            
            try:
                # ✅ LÓGICA DE AGENDA HÍBRIDA & DINÂMICA
                if nome_funcao in ["agendar_servico", "verificar_agenda"]:
                    nome_barbeiro_req = args.get("nome_barbeiro", "Principal")
                    
                    # Default: Agenda Mestre
                    id_calendar = "primary"
                    nome_real = "Principal"
                    
                    # ✅ BUSCA DINÂMICA DO ID DO BARBEIRO NA EQUIPE
                    if cliente_saas:
                        for membro in cliente_saas.get("equipe", []):
                            if membro["nome"].lower() in nome_barbeiro_req.lower():
                                id_calendar = membro.get("id_google_calendar", "primary")
                                nome_real = membro["nome"]
                                break
                    
                    if nome_funcao == "agendar_servico":
                        # 1. Salva no Backup Interno (JSON)
                        salvar_agendamento_interno(
                            cliente_saas["email"] if cliente_saas else "demo",
                            nome_real,
                            args.get("data_hora"),
                            args.get("nome_cliente")
                        )

                        # 2. Tenta salvar no Google Calendar
                        msg_retorno = ""
                        if tipo_agenda == "google" or id_calendar != "primary":
                            try:
                                logger.info(f"Tentando agendar no Google para: {id_calendar}")
                                resultado_google = criar_evento_agenda(
                                    args.get("data_hora"), 
                                    f"{args.get('nome_cliente')} ({nome_real})",
                                    calendar_id=id_calendar
                                )
                                msg_retorno = resultado_google 
                            except Exception as e_google:
                                logger.error(f"Falha no Google: {e_google}")
                                msg_retorno = f"Agendado com sucesso no sistema interno para {nome_real}. (Obs: Erro na sync Google)"
                        else:
                            msg_retorno = f"Agendado com sucesso no sistema da barbearia para {nome_real}!"

                        resultado = msg_retorno
                    
                    elif nome_funcao == "verificar_agenda":
                        if tipo_agenda == "google":
                            resultado = listar_proximos_eventos(calendar_id=id_calendar)
                        else:
                            agendamentos = listar_agenda_interna(cliente_saas["email"] if cliente_saas else "demo")
                            # Filtra apenas do barbeiro certo
                            agendamentos_barbeiro = [a for a in agendamentos if a["barbeiro"] == nome_real]
                            
                            # Filtro opcional por Data
                            data_filtro = args.get("data")
                            if data_filtro:
                                agendamentos_barbeiro = [a for a in agendamentos_barbeiro if a["start"].startswith(data_filtro)]

                            if not agendamentos_barbeiro:
                                resultado = f"Agenda do {nome_real} está livre{' nesta data' if data_filtro else ''}."
                            else:
                                resultado = f"Ocupado em: " + ", ".join([a["start"] for a in agendamentos_barbeiro])

                elif nome_funcao == "alterar_preco_servico":
                    if eh_admin: 
                        resultado = atualizar_um_preco(args.get("servico"), args.get("novo_valor"))
                        if cliente_saas:
                             p = cliente_saas.get("precos", {})
                             item_key = args.get("servico").lower().strip()
                             p[item_key] = float(args.get("novo_valor"))
                             atualizar_dados_cliente(cliente_saas["email"], {"precos": p})
                    else: 
                        resultado = "Sem permissão."
                elif nome_funcao == "gerar_video_marketing":
                    resultado = criar_video_wan(args.get("descricao_ideia"))
                elif nome_funcao == "animar_foto_cliente":
                    resultado = animar_foto_wan(args.get("url_imagem"), args.get("ideia_movimento"))
                else:
                    resultado = "Função desconhecida."
            except Exception as e:
                logger.error(f"Erro Tool {nome_funcao}: {e}")
                resultado = f"Erro técnico: {str(e)}"

            historico_conversas[From].append(msg_ia)
            historico_conversas[From].append({
                "role": "tool", "tool_call_id": tool_call.id,
                "name": nome_funcao, "content": str(resultado)
            })

            resp_final = await asyncio.to_thread(
                client.chat.completions.create,
                model="llama-3.3-70b-versatile",
                messages=historico_conversas[From]
            )
            texto_final = resp_final.choices[0].message.content
            if not texto_final: texto_final = f"✅ Concluído:\n{str(resultado)}"
        else:
            texto_final = msg_ia.content

        historico_conversas[From].append({"role": "assistant", "content": texto_final})
        
        twilio_resp = MessagingResponse()
        msg = twilio_resp.message(texto_final)
        
        url_pattern = r'(https?://[^\s]+(?:\.mp4|fal\.media|pexels)[^\s]*)'
        urls_encontradas = re.findall(url_pattern, texto_final)
        if urls_encontradas:
            msg.media(urls_encontradas[0])

        return Response(content=str(twilio_resp), media_type="application/xml")

    except Exception as e:
        logger.error(f"ERRO CRÍTICO WHATSAPP: {e}", exc_info=True)
        return Response(content=str(MessagingResponse().message("Erro interno.")), media_type="application/xml")

if __name__ == "__main__":
    import uvicorn
    print("🚀 Servidor Victor AI SAAS rodando na porta 8000...")
    uvicorn.run(app, host="0.0.0.0", port=8000)