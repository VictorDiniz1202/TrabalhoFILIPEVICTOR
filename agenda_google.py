import os.path
import datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

#Permissoes na agenda
SCOPES = ["https://www.googleapis.com/auth/calendar"]

import os

def autenticar_google():

    pasta_atual = os.path.dirname(os.path.abspath(__file__))
    
    caminho_credentials = os.path.join(pasta_atual, "credentials.json")
    caminho_token = os.path.join(pasta_atual, "token.json")

    creds = None
    
    if os.path.exists(caminho_token):
        creds = Credentials.from_authorized_user_file(caminho_token, SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(caminho_credentials):
                raise FileNotFoundError(f"❌ ERRO CRÍTICO: Não encontrei o arquivo em: {caminho_credentials}")

            flow = InstalledAppFlow.from_client_secrets_file(
                caminho_credentials, SCOPES
            )
            creds = flow.run_local_server(port=0)
        
        with open(caminho_token, "w") as token:
            token.write(creds.to_json())
            
    return build("calendar", "v3", credentials=creds)

def listar_proximos_eventos():
    service = autenticar_google()
    agora = datetime.datetime.utcnow().isoformat() + "Z"
    
    #Pega 10 eventos para ver se tem disponibilidade
    events_result = service.events().list(
        calendarId="primary", timeMin=agora,
        maxResults=10, singleEvents=True,
        orderBy="startTime"
    ).execute()
    events = events_result.get("items", [])

    if not events:
        return "A agenda está totalmente livre nos próximos dias."

    resposta = "📅 **Horários já Ocupados:**\n"
    for event in events:
        start = event["start"].get("dateTime", event["start"].get("date"))
        resposta += f"- {start}: {event['summary']}\n"
    
    return resposta

def criar_evento_agenda(data_hora_iso, nome_paciente):
    try:
        service = autenticar_google()
        
        event = {
            'summary': f'Consulta: {nome_paciente}',
            'location': 'Hospital Santa Clara',
            'description': 'Agendamento via WhatsApp Bot',
            'start': {
                'dateTime': data_hora_iso,
                'timeZone': 'America/Sao_Paulo',
            },
            'end': {
                'dateTime': (datetime.datetime.fromisoformat(data_hora_iso) + datetime.timedelta(hours=1)).isoformat(),
                'timeZone': 'America/Sao_Paulo',
            },
        }

        event = service.events().insert(calendarId='primary', body=event).execute()
        return f"✅ Agendado com sucesso! Link: {event.get('htmlLink')}"
    except Exception as e:
        return f"Erro ao agendar: {e}"

if __name__ == "__main__":
    print(listar_proximos_eventos())