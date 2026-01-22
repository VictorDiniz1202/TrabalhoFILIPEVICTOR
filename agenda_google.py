import os
import datetime
import logging
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build, Resource
from googleapiclient.errors import HttpError

from logger_config import Log

log_setup = Log("BotLog")
logger = log_setup.get_logger("AgendaGoogle")

SCOPES = ["https://www.googleapis.com/auth/calendar"]
_SERVICE_CACHE = None

# Define fuso horário fixo (Brasil/São Paulo)
SAO_PAULO_TZ = datetime.timezone(datetime.timedelta(hours=-3))

def _to_rfc3339(dt: datetime.datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=SAO_PAULO_TZ)
    return dt.isoformat()

def autenticar_google() -> Resource:
    global _SERVICE_CACHE

    # Se já tiver conexão em memória e o token não expirou, usa ela
    if _SERVICE_CACHE:
        return _SERVICE_CACHE

    pasta_atual = os.path.dirname(os.path.abspath(__file__))
    caminho_credentials = os.path.join(pasta_atual, "credentials.json")
    caminho_token = os.path.join(pasta_atual, "token.json")

    creds = None

    try:
        # 1. Tenta carregar o token existente (que o site gerou ou o login anterior gerou)
        if os.path.exists(caminho_token):
            creds = Credentials.from_authorized_user_file(caminho_token, SCOPES)

        # 2. Valida o token
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("Token expirado. Tentando renovar automaticamente...")
                creds.refresh(Request())
            else:
                # Se não tem token, precisamos logar.
                # Nota: Em produção (servidor), isso aqui falharia se tentasse abrir navegador.
                # Mas como temos o login via Site agora, o token.json deve existir.
                logger.info("Token inválido ou inexistente. Tentando fluxo local...")
                
                if not os.path.exists(caminho_credentials):
                    raise FileNotFoundError("Arquivo credentials.json não encontrado!")

                flow = InstalledAppFlow.from_client_secrets_file(caminho_credentials, SCOPES)
                creds = flow.run_local_server(port=0)

            # Salva o token renovado/novo
            with open(caminho_token, "w") as token:
                token.write(creds.to_json())

        _SERVICE_CACHE = build("calendar", "v3", credentials=creds)
        return _SERVICE_CACHE

    except Exception as e:
        logger.error(f"Falha crítica na autenticação Google: {e}")
        # Reseta o cache para forçar nova tentativa na próxima
        _SERVICE_CACHE = None
        raise e

def listar_proximos_eventos(calendar_id: str = "primary") -> str:
    try:
        service = autenticar_google()
        
        # Pega hora atual em UTC e formata para o padrão do Google
        agora = datetime.datetime.utcnow().isoformat() + "Z"

        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=agora,
            maxResults=10,
            singleEvents=True,
            orderBy="startTime"
        ).execute()

        events = events_result.get("items", [])

        if not events:
            return f"A agenda ({calendar_id}) está livre nos próximos dias."

        resposta = f"📅 Agenda ({calendar_id}):\n"
        for event in events:
            start = event["start"].get("dateTime", event["start"].get("date"))
            try:
                # Tenta formatar bonitinho
                data_obj = datetime.datetime.fromisoformat(start)
                data_formatada = data_obj.strftime("%d/%m às %H:%M")
            except:
                data_formatada = start

            resposta += f"- {data_formatada}: {event.get('summary', 'Ocupado')}\n"

        return resposta

    except HttpError as error:
        logger.error(f"Erro de API ao listar eventos ({calendar_id}): {error}")
        return "Erro de permissão ou conexão ao consultar a agenda."
    except Exception as e:
        logger.error(f"Erro inesperado ao listar: {e}")
        return "Erro técnico ao acessar agenda."

def criar_evento_agenda(data_hora_iso: str, nome_cliente: str, calendar_id: str = "primary", duracao_min: int = 45) -> str:
    """
    Cria o evento e retorna UMA STRING de sucesso ou lança EXCEÇÃO se falhar.
    """
    try:
        # 1. Parsing da data
        try:
            inicio_dt = datetime.datetime.fromisoformat(data_hora_iso)
        except ValueError:
            raise ValueError("Formato de data inválido fornecido pela IA.")

        service = autenticar_google()
        
        # Calcula fim do corte
        fim_dt = inicio_dt + datetime.timedelta(minutes=duracao_min)

        event_body = {
            "summary": f"✂️ {nome_cliente}",
            "description": "Agendado via Victor AI (WhatsApp)",
            "start": {
                "dateTime": inicio_dt.isoformat(), 
                "timeZone": "America/Sao_Paulo"
            },
            "end": {
                "dateTime": fim_dt.isoformat(), 
                "timeZone": "America/Sao_Paulo"
            },
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": 30},
                ],
            },
        }

        logger.info(f"Enviando agendamento para Calendar ID: {calendar_id}")
        
        event = service.events().insert(
            calendarId=calendar_id, 
            body=event_body
        ).execute()
        
        link = event.get("htmlLink")
        return f"✅ Agendamento confirmado!\n📅 {inicio_dt.strftime('%d/%m às %H:%M')}\n🔗 Ver no Google: {link}"

    except HttpError as error:
        # Se o erro for 404, o email do barbeiro está errado ou não existe
        if error.resp.status == 404:
            logger.error(f"Calendário não encontrado: {calendar_id}")
            raise Exception(f"Não encontrei a agenda do e-mail {calendar_id}. Verifique o cadastro.")
        
        # Se o erro for 403, falta permissão
        if error.resp.status == 403:
            logger.error(f"Sem permissão no calendário: {calendar_id}")
            raise Exception(f"O barbeiro ({calendar_id}) precisa aceitar o convite de compartilhamento da agenda.")

        logger.error(f"Erro Google API: {error}")
        raise Exception(f"Erro no Google Agenda: {error}")

    except Exception as e:
        logger.error(f"Erro genérico ao agendar: {e}")
        raise e

if __name__ == "__main__":
    # Teste rápido se rodar direto o arquivo
    try:
        print(listar_proximos_eventos())
    except Exception as e:
        print(f"Erro no teste: {e}")