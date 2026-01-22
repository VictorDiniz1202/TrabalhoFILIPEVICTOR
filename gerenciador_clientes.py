import json
import os
import logging
import uuid

ARQUIVO_CLIENTES = "base_clientes.json"
ARQUIVO_AGENDAMENTOS = "base_agendamentos_internos.json"

logger = logging.getLogger("GerenciadorClientes")

HORARIOS_PADRAO = {
    "padrao": {"inicio": "09:00", "fim": "19:00"},
    "dias": {
        "0": {"inicio": "09:00", "fim": "19:00"},
        "1": {"inicio": "09:00", "fim": "19:00"},
        "2": {"inicio": "09:00", "fim": "19:00"},
        "3": {"inicio": "09:00", "fim": "19:00"},
        "4": {"inicio": "09:00", "fim": "19:00"},
        "5": {"inicio": "09:00", "fim": "19:00"},
        "6": {"inicio": "09:00", "fim": "19:00"},
    },
}

def get_cliente_padrao(email, senha, telefone, nome_barbearia, nome_bot, tipo_agenda="interna"):
    return {
        "id": str(uuid.uuid4()),
        "email": email,
        "senha": senha,
        "telefone_whatsapp": telefone,
        "pagamento": {
            "ativo": True,
            "plano": "beta_free",
            "vencimento": None
        },
        "creditos_video": 0,
        "config": {
            "nome_barbearia": nome_barbearia,
            "nome_bot": nome_bot,
            "tipo_agenda": tipo_agenda,
            "criar_videos": True,
            "horarios_atendimento": HORARIOS_PADRAO
        },
        "equipe": [
            {"nome": "Principal", "id_google_calendar": "primary"}
        ],
        "precos": {
            "corte": {"preco": 35.00, "duracao": 30},
            "barba": {"preco": 35.00, "duracao": 30},
            "combo": {"preco": 70.00, "duracao": 50},
            "sobrancelha": {"preco": 15.00, "duracao": 15}
        }
    }

def carregar_base():
    if not os.path.exists(ARQUIVO_CLIENTES):
        with open(ARQUIVO_CLIENTES, "w", encoding="utf-8") as f:
            json.dump({}, f)
        return {}
    try:
        with open(ARQUIVO_CLIENTES, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def salvar_base(dados):
    with open(ARQUIVO_CLIENTES, "w", encoding="utf-8") as f:
        json.dump(dados, f, indent=4)

# --- FUNCOES PUBLICAS DE CLIENTE ---

def registrar_cliente(email, senha, telefone, nome_barbearia, nome_bot, tipo_agenda="interna"):
    base = carregar_base()
    if email in base:
        return False, "E-mail já cadastrado."

    base[email] = get_cliente_padrao(email, senha, telefone, nome_barbearia, nome_bot, tipo_agenda)
    salvar_base(base)
    return True, base[email]

def autenticar_cliente(email, senha):
    base = carregar_base()
    cliente = base.get(email)
    if cliente and cliente["senha"] == senha:
        return cliente
    return None

def buscar_cliente_por_telefone(telefone_wpp):
    base = carregar_base()
    for email, dados in base.items():
        if dados.get("telefone_whatsapp") == telefone_wpp:
            return dados
    return None

def buscar_cliente_por_email(email):
    base = carregar_base()
    return base.get(email)

def atualizar_dados_cliente(email, novos_dados):
    base = carregar_base()
    if email in base:
        base[email].update(novos_dados)
        salvar_base(base)
        return True
    return False

def atualizar_horarios_atendimento(email_dono, horarios):
    base = carregar_base()
    if email_dono in base:
        cfg = base[email_dono].get("config", {})
        cfg["horarios_atendimento"] = horarios
        base[email_dono]["config"] = cfg
        salvar_base(base)
        return True
    return False

# --- FUNCOES DE EQUIPE E AGENDA ---

def adicionar_barbeiro(email_dono, nome_barbeiro, id_calendario_google="primary"):
    base = carregar_base()
    if email_dono in base:
        base[email_dono]["equipe"].append({
            "nome": nome_barbeiro,
            "id_google_calendar": id_calendario_google
        })
        salvar_base(base)
        return True
    return False

# --- AGENDA INTERNA (JSON) ---

def carregar_agendamentos_internos():
    if not os.path.exists(ARQUIVO_AGENDAMENTOS):
        with open(ARQUIVO_AGENDAMENTOS, "w", encoding="utf-8") as f:
            json.dump({}, f)
    try:
        with open(ARQUIVO_AGENDAMENTOS, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def salvar_agendamento_interno(email_dono, barbeiro_nome, data_hora, cliente_nome, servico=None, duracao=30, google_event_id=None, calendar_id=None):
    agendamentos = carregar_agendamentos_internos()

    if email_dono not in agendamentos:
        agendamentos[email_dono] = []

    novo_evento = {
        "id": str(uuid.uuid4()),
        "barbeiro": barbeiro_nome,
        "start": data_hora,
        "title": f"{cliente_nome} - {barbeiro_nome}",
        "cliente": cliente_nome,
        "servico": servico or "Agendamento",
        "duracao": int(duracao or 30),
        "google_event_id": google_event_id,
        "calendar_id": calendar_id
    }

    agendamentos[email_dono].append(novo_evento)

    with open(ARQUIVO_AGENDAMENTOS, "w", encoding="utf-8") as f:
        json.dump(agendamentos, f, indent=4)

    return True, f"Agendado com sucesso para {cliente_nome} com {barbeiro_nome}!"

def cancelar_agendamento_interno(email_dono, agendamento_id):
    agendamentos = carregar_agendamentos_internos()
    if email_dono not in agendamentos:
        return False, None

    removido = None
    novos = []
    for a in agendamentos[email_dono]:
        if a.get("id") == agendamento_id and removido is None:
            removido = a
            continue
        novos.append(a)

    if removido is None:
        return False, None

    agendamentos[email_dono] = novos
    with open(ARQUIVO_AGENDAMENTOS, "w", encoding="utf-8") as f:
        json.dump(agendamentos, f, indent=4)

    return True, removido

def listar_agenda_interna(email_dono):
    agendamentos = carregar_agendamentos_internos()
    return agendamentos.get(email_dono, [])

# --- FUNCOES FINANCEIRAS ---

def ativar_pagamento_cliente(email):
    base = carregar_base()
    if email in base:
        base[email]["pagamento"]["ativo"] = True
        base[email]["pagamento"]["plano"] = "pro"
        salvar_base(base)
        return True, base[email]
    return False, None

def adicionar_creditos_video(email, quantidade):
    base = carregar_base()
    if email in base:
        saldo_atual = base[email].get("creditos_video", 0)
        base[email]["creditos_video"] = saldo_atual + int(quantidade)
        salvar_base(base)
        return True, base[email]
    return False, None

def descontar_credito_video(email):
    base = carregar_base()
    if email in base:
        saldo_atual = base[email].get("creditos_video", 0)
        if saldo_atual > 0:
            base[email]["creditos_video"] = saldo_atual - 1
            salvar_base(base)
            return True
    return False
