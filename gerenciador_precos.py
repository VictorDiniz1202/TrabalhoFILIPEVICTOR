import json
import os
import logging

logger = logging.getLogger("GerenciadorPrecos")

ARQUIVO_PRECOS = "tabela_precos.json"

# Preços padrão com duração (minutos)
PRECOS_PADRAO = {
    "corte": {"preco": 35.00, "duracao": 30},
    "barba": {"preco": 35.00, "duracao": 30},
    "combo": {"preco": 70.00, "duracao": 50},
    "sobrancelha": {"preco": 10.00, "duracao": 15},
}

def _normalizar_precos(dados: dict) -> dict:
    """Garante formato {'servico': {'preco': float, 'duracao': int}}"""
    normalizado = {}
    for nome, valor in dados.items():
        if isinstance(valor, dict):
            preco = float(valor.get("preco", 0))
            duracao = int(valor.get("duracao", 30))
        else:
            preco = float(valor)
            duracao = 30
        normalizado[nome] = {"preco": preco, "duracao": duracao}
    return normalizado

def carregar_precos():
    """Lê o JSON e retorna o dicionário de preços normalizado."""
    if not os.path.exists(ARQUIVO_PRECOS):
        salvar_precos(PRECOS_PADRAO)
        return PRECOS_PADRAO
    try:
        with open(ARQUIVO_PRECOS, "r", encoding="utf-8") as f:
            dados = json.load(f)
            return _normalizar_precos(dados)
    except Exception as e:
        logger.error(f"Erro ao ler preços: {e}")
        return PRECOS_PADRAO

def salvar_precos(novos_precos):
    """Salva o dicionário no arquivo JSON."""
    try:
        normalizado = _normalizar_precos(novos_precos)
        with open(ARQUIVO_PRECOS, "w", encoding="utf-8") as f:
            json.dump(normalizado, f, indent=4)
        return True
    except Exception as e:
        logger.error(f"Erro ao salvar preços: {e}")
        return False

def atualizar_um_preco(item, valor):
    """Atualiza um item específico (mantém duração se existir)."""
    precos = carregar_precos()
    item_key = item.lower().strip()
    antigo = precos.get(item_key, {"duracao": 30})
    precos[item_key] = {"preco": float(valor), "duracao": int(antigo.get("duracao", 30))}
    if salvar_precos(precos):
        return f"✅ Preço de '{item_key}' atualizado para R$ {float(valor):.2f}."
    else:
        return "⚠️ Erro ao salvar no disco."

def get_texto_tabela():
    """Gera o texto formatado para o Prompt do Victor."""
    precos = carregar_precos()
    texto = "TABELA DE PREÇOS ATUALIZADA:\n"
    for item, dados in precos.items():
        try:
            preco = dados.get("preco", dados if isinstance(dados, (int, float)) else 0)
            dur = dados.get("duracao", 30) if isinstance(dados, dict) else 30
        except AttributeError:
            preco, dur = dados, 30
        texto += f"    - {item.capitalize()}: R$ {preco:.2f} ({dur} min)\n"
    return texto
