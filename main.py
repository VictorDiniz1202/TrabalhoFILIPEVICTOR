import os
import json
import re
import requests
import uuid
import logging
from pathlib import Path
from fastapi import FastAPI, Form, Response, Request, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from twilio.twiml.messaging_response import MessagingResponse
from dotenv import load_dotenv
from openai import OpenAI

#Imports dos Modulos
from logger_config import Log
from gerenciador_precos import carregar_precos, salvar_precos, atualizar_um_preco
from agenda_google import listar_proximos_eventos, criar_evento_agenda, autenticar_google
from personas import get_system_prompt, get_director_prompt
from GeradorDeVideo import criar_video_wan, animar_foto_wan

log_setup = Log("BotLog")
logger = log_setup.get_logger("MainAPI")

load_dotenv()

app = FastAPI(title="API Victor AI - Backend Lovable")

# 2. CORS (Permite conexão com o site Lovable)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Em produção, troque "*" pela URL do seu site
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3. CLIENTE AI (GROQ / OPENAI)
try:
    client = OpenAI(
        api_key=os.getenv("GROQ_API_KEY"),
        base_url="https://api.groq.com/openai/v1"
    )
except Exception as e:
    logger.critical(f"Erro Client AI: {e}")

ADMINS = [num.strip() for num in os.getenv("ADMIN_NUMBERS", "").split(",") if num]
WEB_KEY = os.getenv("WEB_API_KEY")
PASTA_IMAGENS = Path("imagens_recebidas")
PASTA_IMAGENS.mkdir(exist_ok=True)

# Função de Download Segura
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


#Rotas do Lovable Dashboard

class LoginRequest(BaseModel):
    password: str

class PriceUpdate(BaseModel):
    corte: float
    barba: float
    combo: float
    sobrancelha: float

class VideoGenRequest(BaseModel):
    prompt: str
    tipo: str = "texto"
    image_url: Optional[str] = None

@app.post("/api/dashboard/login")
async def dashboard_login(dados: LoginRequest):
    if dados.password == "mestre123":
        return {"auth": True, "token": "admin-token-super-seguro"}
    raise HTTPException(status_code=401, detail="Senha incorreta")

@app.get("/api/dashboard/stats")
async def get_stats():
    return {
        "agendamentos_hoje": 4, "receita_estimada": 350.00,
        "videos_gerados": 12, "status_sistema": "Online"
    }

@app.get("/api/dashboard/logs")
async def get_logs():
    log_lines = []
    try:
        from datetime import date
        nome_arquivo = log_setup.log_path / f"BotLog_{date.today()}.log"
        if os.path.exists(nome_arquivo):
            with open(nome_arquivo, "r", encoding="utf-8") as f:
                log_lines = f.readlines()[-50:]
    except Exception as e:
        log_lines = [f"Erro: {str(e)}"]
    return {"logs": log_lines}

@app.get("/api/dashboard/prices")
async def get_prices_api():
    return carregar_precos()

@app.post("/api/dashboard/prices")
async def update_prices_api(novos_precos: PriceUpdate):
    salvar_precos(novos_precos.model_dump())
    return {"status": "success"}

@app.get("/api/dashboard/calendar")
async def get_calendar_events():
    try:
        service = autenticar_google()
        import datetime
        agora = datetime.datetime.utcnow().isoformat() + "Z"
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
    try:
        if req.tipo == "imagem" and req.image_url:
            url = animar_foto_wan(req.image_url, req.prompt)
        else:
            url = criar_video_wan(req.prompt)
        return {"video_url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Definição das Tools
tools_agenda = [
    {"type": "function", "function": {"name": "verificar_agenda", "description": "Verifica agenda.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "agendar_servico", "description": "Agenda serviço.", "parameters": {"type": "object", "properties": {"data_hora": {"type": "string"}, "nome_cliente": {"type": "string"}}, "required": ["data_hora", "nome_cliente"]}}},
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

        eh_admin = From in ADMINS
        
        # Gerenciamento de Modos
        if Body.lower().startswith("/video"):
            if eh_admin:
                modos_usuarios[From] = "video"
                Body = Body[6:].strip() or "Modo Diretor."
            else:
                Body = "Quero saber sobre vídeos."
        elif Body.lower().startswith("/barbeiro"):
            modos_usuarios[From] = "barbeiro"
            Body = Body[9:].strip()

        modo_atual = modos_usuarios.get(From, "barbeiro")
        
        # Seleção de Persona e Tools
        if modo_atual == "video" and eh_admin:
            prompt_sistema = get_director_prompt()
            tools_ativas = tools_video
        else:
            prompt_sistema = get_system_prompt()
            tools_ativas = tools_agenda
            modos_usuarios[From] = "barbeiro"

        # Gestão de Histórico Otimizada (Limpeza Automática)
        if From not in historico_conversas:
            historico_conversas[From] = []
        
        if len(historico_conversas[From]) > 12: # Mantém memória curta e eficiente
            historico_conversas[From] = [historico_conversas[From][0]] + historico_conversas[From][-11:]

        # Garante o System Prompt correto
        if not historico_conversas[From] or historico_conversas[From][0]["content"] != prompt_sistema:
            historico_conversas[From] = [{"role": "system", "content": prompt_sistema}]

        # Mídia
        conteudo_msg = Body
        if num_media > 0 and media_url and eh_admin:
            local_path = salvar_imagem_localmente(media_url)
            if local_path:
                conteudo_msg = f"{Body} [IMAGEM RECEBIDA: {local_path}]"

        historico_conversas[From].append({"role": "user", "content": conteudo_msg})
        logger.info(f"Msg de {From}: {conteudo_msg}")

        # Chamada AI
        resposta = client.chat.completions.create(
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
                if nome_funcao == "verificar_agenda":
                    resultado = listar_proximos_eventos()
                elif nome_funcao == "agendar_servico":
                    resultado = criar_evento_agenda(args.get("data_hora"), args.get("nome_cliente"))
                elif nome_funcao == "alterar_preco_servico":
                    if eh_admin: resultado = atualizar_um_preco(args.get("servico"), args.get("novo_valor"))
                    else: resultado = "Sem permissão."
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

            resp_final = client.chat.completions.create(
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
        
        # Regex para anexar vídeo se houver link
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
    uvicorn.run(app, host="0.0.0.0", port=8000)