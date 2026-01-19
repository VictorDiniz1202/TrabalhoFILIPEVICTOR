import streamlit as st
import requests
import os
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="Wan 2.1 Studio", page_icon="🎬", layout="centered")

st.title("🎬 Wan 2.1 - Painel de Teste")
st.markdown("Use esta interface para testar a geração de vídeos isoladamente (via API do Site).")

with st.sidebar:
    st.header("⚙️ Configuração da API")
    #.ENV
    api_url_padrao = "http://localhost:8000/api/v1/gerar-video"
    api_key_padrao = os.getenv("WEB_API_KEY", "")

    api_url = st.text_input("URL da API:", value=api_url_padrao)
    api_key = st.text_input("Senha (x-api-key):", value=api_key_padrao, type="password")
    
    st.info("Certifique-se de que o 'main.py' está rodando no terminal!")


tab1, tab2 = st.tabs(["📝 Texto para Vídeo", "🖼️ Foto para Vídeo"])

with tab1:
    st.subheader("Criar Vídeo a partir de uma Ideia")
    prompt_texto = st.text_area("Descreva sua ideia:", placeholder="Ex: Um carro esportivo correndo na chuva cyberpunk...")
    
    if st.button("🎬 Gerar Vídeo (Texto)", type="primary"):
        if not prompt_texto:
            st.warning("Digite uma descrição primeiro.")
        else:
            with st.status("Processando...", expanded=True) as status:
                try:
                    status.write("conectando ao servidor...")
                    
                    # Chamando API
                    response = requests.post(
                        api_url,
                        headers={"x-api-key": api_key},
                        json={
                            "prompt": prompt_texto,
                            "tipo": "texto"
                        }
                    )
                    
                    if response.status_code == 200:
                        status.write("✅ Vídeo gerado! Baixando player...")
                        dados = response.json()
                        video_url = dados["video_url"]
                        
                        st.success("Vídeo renderizado com sucesso!")
                        st.video(video_url)
                        st.code(video_url, language="text")
                        
                        status.update(label="Concluído!", state="complete", expanded=False)
                    else:
                        status.update(label="Erro!", state="error")
                        st.error(f"Erro na API: {response.status_code} - {response.text}")

                except requests.exceptions.ConnectionError:
                    st.error("🚨 O servidor não está rodando! Execute 'python main.py'.")

# Animaçao de Fotos
with tab2:
    st.subheader("Animar uma Imagem Existente")
    st.markdown("*Para testar, cole o link de uma imagem pública (ex: Unsplash, Pexels ou Google Images).*")
    
    url_imagem = st.text_input("Cole a URL da Imagem:", placeholder="https://...")
    prompt_movimento = st.text_input("O que deve acontecer? (Opcional)", placeholder="Ex: Zoom lento, sorrir, piscar...")
    
    #Analise da imagem
    if url_imagem:
        try:
            st.image(url_imagem, caption="Imagem de Entrada", width=300)
        except:
            st.warning("URL de imagem inválida ou inacessível.")

    if st.button("✨ Animar Foto", type="primary"):
        if not url_imagem:
            st.warning("Você precisa colar a URL de uma imagem.")
        else:
            with st.status("Processando Animação...", expanded=True) as status:
                try:
                    status.write("Enviando para o Wan I2V...")
                    
                    response = requests.post(
                        api_url,
                        headers={"x-api-key": api_key},
                        json={
                            "prompt": prompt_movimento if prompt_movimento else "Cinematic movement",
                            "image_url": url_imagem,
                            "tipo": "imagem"
                        }
                    )
                    
                    if response.status_code == 200:
                        dados = response.json()
                        video_url = dados["video_url"]
                        
                        st.success("Animação concluída!")
                        st.video(video_url)
                        
                        status.update(label="Concluído!", state="complete", expanded=False)
                    else:
                        st.error(f"Erro na API: {response.text}")

                except requests.exceptions.ConnectionError:
                    st.error("🚨 O servidor main.py não está rodando!")