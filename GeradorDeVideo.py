import os
import json
import time
import fal_client
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# --- CONFIGURAÇÃO ---
MODO_TESTE = False #Modo Teste, Caso true, não chama a API real, apenas simula

client_groq = OpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)

def refinar_prompt_com_ia(ideia_bruta, tipo_geracao="text"):
    print(f"🧠 [IA] Refinando prompt ({tipo_geracao}): '{ideia_bruta}'...")
    
    if MODO_TESTE:
        return {"prompt": ideia_bruta, "negative_prompt": "test"}

    #Seleciona qual Persona deve utilizar
    if tipo_geracao == "image":
        #Supervisor VFX
        system_prompt = """
        ATUE COMO: Um Supervisor de VFX (Efeitos Visuais) especialista em animar imagens estáticas (Image-to-Video) usando Wan 2.1.
        
        SUA TAREFA:
        Receber uma descrição de movimento desejado e criar um prompt técnico que PRESERVE a imagem original mas adicione vida.
        
        REGRAS CRÍTICAS PARA ANIMAÇÃO DE FOTO:
        1. PRESERVAÇÃO: O prompt deve focar no movimento, não na descrição do sujeito (pois o sujeito já está na foto).
        2. FÍSICA E DETALHES: Adicione detalhes como "wind blowing hair", "subtle breathing chest movement", "blinking eyes", "clouds moving".
        3. CÂMERA: Adicione movimentos de câmera que dão profundidade ("slow dolly in", "parallax effect", "pan right").
        4. SE O USUÁRIO FOR VAGO (ex: "anima aí"): Invente um movimento sutil e elegante (ex: "Slow motion, subtle wind, cinematic zoom").
        
        ESTRUTURA DO JSON:
        {
            "prompt": "Descrição técnica em INGLÊS focada em AÇÃO e MOVIMENTO...",
            "negative_prompt": "morphing, distortion, bad anatomy, changing face, static, low frame rate"
        }
        """
    else:
        #Diretor de Cinema
        system_prompt = """
        ATUE COMO: Um Diretor de Cinema especialista em IA Generativa.
        
        SUA TAREFA:
        Transformar uma ideia simples em um Roteiro Visual Completo.
        
        ELEMENTOS OBRIGATÓRIOS:
        1. VISUAL: Descreva o sujeito e o cenário com riqueza de detalhes (texturas, cores).
        2. LUZ: Especifique a iluminação (Cinematic, Volumetric, Neon, Golden Hour).
        3. LENTE: Especifique a câmera (85mm, Wide Angle, Drone shot, 4k).
        4. MOVIMENTO: Descreva a ação (Running, Slow motion, Walking towards camera).
        
        ESTRUTURA DO JSON:
        {
            "prompt": "Prompt masterclass detalhado em inglês...",
            "negative_prompt": "cartoon, blur, watermark, bad quality, distortion"
        }
        """

    try:
        response = client_groq.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Pedido do usuário: {ideia_bruta}"}
            ],
            temperature=0.6,
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"⚠️ Erro no refinamento: {e}")
        return {"prompt": ideia_bruta + ", high quality, cinematic motion", "negative_prompt": "distortion"}


def criar_video_wan(ideia_usuario):
    
    if MODO_TESTE:
        print(f"⚠️ [TESTE] T2V Simulado.")
        time.sleep(2)
        return "https://videos.pexels.com/video-files/855564/855564-hd_1920_1080_25fps.mp4"

    dados = refinar_prompt_com_ia(ideia_usuario, tipo_geracao="text")
    
    print(f"🎨 Prompt T2V: {dados['prompt'][:50]}...")
    
    try:
        handler = fal_client.submit(
            "fal-ai/wan-2.1-t2v-1.3b",
            arguments={
                "prompt": dados["prompt"],
                "negative_prompt": dados.get("negative_prompt", ""),
                "aspect_ratio": "16:9",
                "num_inference_steps": 30, 
                "guidance_scale": 5.0
            },
        )
        result = handler.get()
        return result['video']['url']
    except Exception as e:
        return f"Erro no vídeo: {str(e)}"


def animar_foto_wan(url_imagem, ideia_movimento):
    
    if MODO_TESTE:
        print(f"⚠️ [TESTE] I2V Simulado.")
        time.sleep(2)
        return "https://videos.pexels.com/video-files/4763826/4763826-uhd_2560_1440_24fps.mp4"

    if not ideia_movimento or len(ideia_movimento) < 3:
        ideia_movimento = "Make it alive, subtle cinematic movement."

    dados = refinar_prompt_com_ia(ideia_movimento, tipo_geracao="image")
    
    print(f"🎨 Prompt I2V (VFX): {dados['prompt'][:50]}...")

    try:
        handler = fal_client.submit(
            "fal-ai/wan-2.1-i2v-1.3b",
            arguments={
                "image_url": url_imagem,
                "prompt": dados["prompt"],
                "negative_prompt": dados.get("negative_prompt", ""),
                "aspect_ratio": "16:9", 
                "num_inference_steps": 30,
                "guidance_scale": 5.0
            },
        )
        result = handler.get()
        return result['video']['url']
    except Exception as e:
        return f"Erro na animação: {str(e)}"