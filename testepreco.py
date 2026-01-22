import requests

# URL do seu bot
url = "http://localhost:8000/api/dashboard/prices"

# Dados de teste (simulando o site)
novos_dados = {
    "corte": 99.90,
    "barba": 50.00,
    "combo": 120.00,
    "sobrancelha": 25.00
}

try:
    print(f"📡 Tentando enviar dados para: {url}")
    resposta = requests.post(url, json=novos_dados)
    
    print(f"Status Code: {resposta.status_code}")
    print(f"Resposta: {resposta.text}")
    
    if resposta.status_code == 200:
        print("✅ SUCESSO! O Python aceitou a mudança.")
    else:
        print("❌ ERRO! O Python recusou.")
        
except Exception as e:
    print(f"❌ FALHA TOTAL: {e}")
    print("Dica: Verifique se o uvicorn main:app está rodando.")