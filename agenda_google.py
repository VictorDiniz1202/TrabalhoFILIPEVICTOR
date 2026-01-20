import os
import datetime
import logging
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build, Resource
from googleapiclient.errors import HttpError

#Log Padrao
from logger_config import Log

#Log especifico pro modulo
log_setup = Log("BotLog")
logger = log_setup.get_logger("AgendaGoogle")

SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Variável global para armazenar a conexão (Cache)
# Isso evita conectar no Google toda vez que alguém manda mensagem
_SERVICE_CACHE = None

def autenticar_google() -> Resource:
    global _SERVICE_CACHE
    
    # Retorna o serviço em cache se já autenticado
    if _SERVICE_CACHE:
        return _SERVICE_CACHE

    pasta_atual = os.path.dirname(os.path.abspath(__file__))
    caminho_credentials = os.path.join(pasta_atual, "credentials.json")
    caminho_token = os.path.join(pasta_atual, "token.json")

    creds = None
    
    try:
        if os.path.exists(caminho_token):
            creds = Credentials.from_authorized_user_file(caminho_token, SCOPES)
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("Token expirado. Atualizando credenciais...")
                creds.refresh(Request())
            else:
                logger.info("Iniciando novo fluxo de autenticação (OAuth)...")
                if not os.path.exists(caminho_credentials):
                    error_msg = f"Arquivo credentials.json não encontrado em: {caminho_credentials}"
                    logger.critical(error_msg)
                    raise FileNotFoundError(error_msg)

                flow = InstalledAppFlow.from_client_secrets_file(caminho_credentials, SCOPES)
                creds = flow.run_local_server(port=0)
            
            #token
            with open(caminho_token, "w") as token:
                token.write(creds.to_json())
        
        #Salvando o serviço no cache global
        _SERVICE_CACHE = build("calendar", "v3", credentials=creds)
        logger.info("Conexão com Google Calendar estabelecida com sucesso.")
        return _SERVICE_CACHE

    except Exception as e:
        logger.error(f"Falha crítica na autenticação: {e}")
        raise

def listar_proximos_eventos() -> str:
    #listanda 10 eventos da agenda, caso queira mudar so mudar a variavel maxResults
    try:
        service = autenticar_google()
        agora = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        
        events_result = service.events().list(
            calendarId="primary", 
            timeMin=agora,
            maxResults=10, 
            singleEvents=True,
            orderBy="startTime"
        ).execute()
        
        events = events_result.get("items", [])

        if not events:
            return "A agenda está totalmente livre nos próximos dias."

        resposta = "📅 **Horários já Ocupados:**\n"
        for event in events:
            start = event["start"].get("dateTime", event["start"].get("date"))
            
            #Formataçao da data
            try:
                data_obj = datetime.datetime.fromisoformat(start)
                data_formatada = data_obj.strftime("%d/%m às %H:%M")
            except ValueError:
                data_formatada = start #Se nao conseguir formatar, deixa o original

            resposta += f"- {data_formatada}: {event['summary']}\n"
        
        return resposta

    except HttpError as error:
        logger.error(f"Erro de API ao listar eventos: {error}")
        return "Erro ao consultar a agenda no Google."
    except Exception as e:
        logger.error(f"Erro inesperado ao listar: {e}")
        return "Erro técnico ao acessar agenda."

def criar_evento_agenda(data_hora_iso: str, nome_cliente: str) -> str:
    try:
        try:
            inicio_dt = datetime.datetime.fromisoformat(data_hora_iso)
        except ValueError:
            logger.warning(f"Formato de data inválido recebido: {data_hora_iso}")#Evita crash no bot caso a data venha errada
            return "Erro: Data em formato inválido. Use AAAA-MM-DDTHH:MM:SS"

        service = autenticar_google()
        
        # Fim do evento 1 hora depois do início, variavel hours pode ser alterada para mudar a duraçao padrao
        fim_dt = inicio_dt + datetime.timedelta(hours=1)
        
        event_body = {
            'summary': f'Cliente: {nome_cliente}',
            'location': 'Barbearia/Petshop', #Generico para teste
            'description': 'Agendamento automático via Chatbot WhatsApp',
            'start': {
                'dateTime': data_hora_iso,
                'timeZone': 'America/Sao_Paulo',
            },
            'end': {
                'dateTime': fim_dt.isoformat(),
                'timeZone': 'America/Sao_Paulo',
            },
        }

        logger.info(f"Tentando agendar para {nome_cliente} às {data_hora_iso}")
        
        event = service.events().insert(calendarId='primary', body=event_body).execute()
        
        link = event.get('htmlLink')
        logger.info(f"Evento criado com sucesso: {link}")
        return f"✅ Agendado com sucesso para {nome_cliente}! Verifique aqui: {link}"

    except HttpError as error:
        logger.error(f"Erro da Google API ao criar evento: {error}")
        return f"Falha no Google Agenda: {error}"
    except Exception as e:
        logger.error(f"Erro genérico ao agendar: {e}")
        return "Ocorreu um erro interno ao tentar agendar."

if __name__ == "__main__":
    print(listar_proximos_eventos())