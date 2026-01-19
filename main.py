import os
import json
import re
import requests
import uuid
from pathlib import Path
from fastapi import FastAPI, Form, Response, Request, HTTPException, Header
from pydantic import BaseModel
from typing import Optional
from twilio.twiml.messaging_response import MessagingResponse
from dotenv import load_dotenv
from openai import OpenAI
from agenda_google import listar_proximos_eventos, criar_evento_agenda
from GeradorDeVideo import criar_video_wan, animar_foto_wan
from personas import get_system_prompt, get_director_prompt

load_dotenv()
app = FastAPI()

client = OpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)

# Configurações
ADMINS = [num.strip() for num in os.getenv("ADMIN_NUMBERS", "").split(",")]
WEB_KEY = os.getenv("WEB_API_KEY")

#Pasta de Imagens
PASTA_IMAGENS = Path("imagens_recebidas")
PASTA_IMAGENS.mkdir(exist_ok=True)

#Download da imagem
def salvar_imagem_localmente(url_imagem):
    try:
        nome_arquivo = f"wpp_{uuid.uuid4().hex[:8]}.jpg"
        caminho_completo = PASTA_IMAGENS / nome_arquivo
        resposta = requests.get(url_imagem)
        if resposta.status_code == 200:
            with open(caminho_completo, "wb") as f:
                f.write(resposta.content)
            return str(caminho_completo)
    except Exception as e:
        print(f"Erro ao salvar imagem: {e}")
    return None

#Api Pro site

class VideoRequest(BaseModel):
    prompt: str
    image_url: Optional[str] = None
    tipo: str = "texto"

@app.post("/api/v1/gerar-video")
async def api_gerar_video(dados: VideoRequest, x_api_key: str = Header(None)):

    if x_api_key != WEB_KEY:
        raise HTTPException(status_code=401, detail="Senha da API incorreta")

    print(f"🖥️ Site solicitou: {dados.prompt} (Tipo: {dados.tipo})")

    try:
        resultado_url = ""
    
        if dados.tipo == "imagem" and dados.image_url:
            resultado_url = animar_foto_wan(dados.image_url, dados.prompt)
        else:
            resultado_url = criar_video_wan(dados.prompt)
            
        return {
            "status": "sucesso",
            "video_url": resultado_url
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


#  Whatsapp/Twilio

#Criando as ferramentas
tools_agenda = [
    {
        "type": "function", "function": {
            "name": "verificar_agenda", "description": "Verifica agenda.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function", "function": {
            "name": "agendar_servico", "description": "Agenda serviço.",
            "parameters": {
                "type": "object", 
                "properties": {"data_hora": {"type": "string"}, "nome_cliente": {"type": "string"}},
                "required": ["data_hora", "nome_cliente"]
            }
        }
    }
]

tools_video = [
    {
        "type": "function", "function": {
            "name": "gerar_video_marketing", "description": "Cria vídeo texto.",
            "parameters": {
                "type": "object",
                "properties": {"descricao_ideia": {"type": "string"}},
                "required": ["descricao_ideia"]
            }
        }
    },
    {
        "type": "function", "function": {
            "name": "animar_foto_cliente", "description": "Anima foto.",
            "parameters": {
                "type": "object",
                "properties": {"url_imagem": {"type": "string"}, "ideia_movimento": {"type": "string"}},
                "required": ["url_imagem", "ideia_movimento"]
            }
        }
    }
]

historico_conversas = {}
modos_usuarios = {} 

@app.post("/whatsapp")
async def reply_whatsapp(request: Request):
    form_data = await request.form()
    
    Body = form_data.get("Body", "").strip()
    From = form_data.get("From")
    num_media = int(form_data.get("NumMedia", 0))
    media_url = form_data.get("MediaUrl0")

    eh_admin = From in ADMINS
    
    if Body.lower().startswith("/video"):
        if eh_admin:
            modos_usuarios[From] = "video"
            Body = Body[6:].strip()
            if not Body and num_media == 0: Body = "Olá Spielberg, acesso autorizado."
        else:
            Body = "Gostaria de falar sobre vídeos."
    elif Body.lower().startswith("/barbeiro"):
        modos_usuarios[From] = "barbeiro"
        Body = Body[9:].strip()

    modo_atual = modos_usuarios.get(From, "barbeiro")
    
    #Ferramentas(tools)
    tools_ativas = []
    prompt_sistema = ""

    if modo_atual == "video" and eh_admin:
        prompt_sistema = get_director_prompt()
        tools_ativas = tools_video
    else:
        prompt_sistema = get_system_prompt()
        tools_ativas = tools_agenda
        modos_usuarios[From] = "barbeiro"

    #Contexto Para cada cliente.
    ultimo_modo = getattr(reply_whatsapp, f"last_mode_{From}", "barbeiro")
    if ultimo_modo != modo_atual:
        historico_conversas[From] = []
        setattr(reply_whatsapp, f"last_mode_{From}", modo_atual)

    if From not in historico_conversas or not historico_conversas[From]:
        historico_conversas[From] = [{"role": "system", "content": prompt_sistema}]

    conteudo_msg = Body
    if num_media > 0 and media_url and eh_admin:
        salvar_imagem_localmente(media_url)
        conteudo_msg = f"{Body} [IMAGEM DETECTADA: {media_url}]"

    historico_conversas[From].append({"role": "user", "content": conteudo_msg})
    print(f"📩 {From}: {conteudo_msg}")

    try:
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
            
            print(f"🛠️ TOOL: {nome_funcao}")
            resultado = ""

            try:
                if nome_funcao == "verificar_agenda":
                    resultado = listar_proximos_eventos()
                elif nome_funcao == "agendar_servico":
                    resultado = criar_evento_agenda(args.get("data_hora"), args.get("nome_cliente"))
                elif nome_funcao == "gerar_video_marketing":
                    print("⏳ Criando vídeo...")
                    resultado = criar_video_wan(args.get("descricao_ideia"))
                elif nome_funcao == "animar_foto_cliente":
                    print("⏳ Animando foto...")
                    resultado = animar_foto_wan(args.get("url_imagem"), args.get("ideia_movimento"))
                else:
                    resultado = "Função não autorizada."
            except Exception as e:
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
            if not texto_final: texto_final = f"✅ Feito:\n{str(resultado)}"
        else:
            texto_final = msg_ia.content

    except Exception as e:
        print(f"🔥 Erro: {e}")
        texto_final = "Ocorreu um erro interno."

    historico_conversas[From].append({"role": "assistant", "content": texto_final})
    print(f"🤖 Resposta: {texto_final}")

 #Resposta Twilio no whatsapp
    twilio_resp = MessagingResponse()
    msg = twilio_resp.message(texto_final)

    url_pattern = r'(https?://[^\s]+(?:\.mp4|fal\.media|pexels)[^\s]*)'
    urls_encontradas = re.findall(url_pattern, texto_final)
    if urls_encontradas:
        msg.media(urls_encontradas[0])

    return Response(content=str(twilio_resp), media_type="application/xml")
#Plataforma Teste com Uvicorn
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)