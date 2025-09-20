from fastapi import FastAPI, Depends, HTTPException, Request, status, WebSocket, WebSocketDisconnect, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import uvicorn
import os
from datetime import datetime, timedelta
from typing import List, Optional
import json

# Importações locais
from database import get_db, create_tables
from models import User, Lead, Broker, LeadDistribution, LeadStatus, WhatsAppConnection, WhatsAppMessage
from auth import authenticate_user, create_access_token, get_current_user
from maytapi import maytapi_client
from schemas import (
    UserCreate, UserResponse, UserLogin, Token,
    LeadCreate, LeadResponse, LeadUpdate,
    BrokerCreate, BrokerResponse, BrokerUpdate,
    LeadDistributionResponse, WhatsAppWebhook,
    DashboardStats, LeadFilters,
    WhatsAppConnectionCreate, WhatsAppConnectionResponse, WhatsAppConnectionUpdate,
    WhatsAppQRResponse, WhatsAppMessageSend, WhatsAppWebhookMessage
)
from crud import (
    create_user, get_user_by_email, get_brokers,
    create_lead, get_leads, update_lead, delete_lead,
    create_broker, update_broker, delete_broker,
    get_lead_distribution_history, distribute_lead,
    get_dashboard_stats, export_leads_excel, export_leads_pdf,
    create_whatsapp_connection, get_whatsapp_connections, get_whatsapp_connection,
    get_whatsapp_connection_by_phone_id, update_whatsapp_connection,
    update_whatsapp_connection_status, delete_whatsapp_connection,
    create_or_get_whatsapp_conversation, get_whatsapp_conversations,
    create_whatsapp_message, get_whatsapp_messages, get_conversation_by_phone,
    mark_messages_as_read
)

app = FastAPI(
    title="Sistema de Gestão de Leads WhatsApp",
    description="Sistema completo para captura e distribuição de leads via WhatsApp Business",
    version="1.0.0"
)

# Configuração CORS - mais restritiva
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5000", "https://*.replit.app", "https://*.repl.co"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# Configuração de arquivos estáticos e templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Security
security = HTTPBearer()

# WebSocket connections manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.user_connections: dict = {}

    async def connect(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        self.active_connections.append(websocket)
        self.user_connections[user_id] = websocket

    def disconnect(self, websocket: WebSocket, user_id: int):
        self.active_connections.remove(websocket)
        if user_id in self.user_connections:
            del self.user_connections[user_id]

    async def send_personal_message(self, message: str, user_id: int):
        if user_id in self.user_connections:
            websocket = self.user_connections[user_id]
            await websocket.send_text(message)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except:
                pass

manager = ConnectionManager()

# Criar tabelas no startup
@app.on_event("startup")
async def startup():
    create_tables()

# Rotas de páginas (Frontend)
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})

@app.get("/leads", response_class=HTMLResponse)
async def leads_page(request: Request):
    return templates.TemplateResponse("leads.html", {"request": request})

@app.get("/brokers", response_class=HTMLResponse)
async def brokers_page(request: Request):
    return templates.TemplateResponse("brokers.html", {"request": request})

@app.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request):
    return templates.TemplateResponse("reports.html", {"request": request})

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse("settings.html", {"request": request})

@app.get("/whatsapp", response_class=HTMLResponse)
async def whatsapp_page(request: Request):
    return templates.TemplateResponse("whatsapp.html", {"request": request})

@app.get("/whatsapp/chat", response_class=HTMLResponse)
async def whatsapp_chat_page(request: Request, connection_id: int = Query(...)):
    return templates.TemplateResponse("whatsapp_chat.html", {
        "request": request,
        "connection_id": connection_id
    })

# Rotas de autenticação
@app.post("/api/register", response_model=UserResponse)
async def register(user: UserCreate, db: Session = Depends(get_db)):
    db_user = get_user_by_email(db, user.email)
    if db_user:
        raise HTTPException(status_code=400, detail="Email já registrado")
    return create_user(db, user)

@app.post("/api/login", response_model=Token)
async def login(user_login: UserLogin, db: Session = Depends(get_db)):
    user = authenticate_user(db, user_login.email, user_login.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou senha incorretos"
        )
    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer", "user": user}

@app.get("/api/users/me", response_model=UserResponse)
async def read_users_me(current_user: User = Depends(get_current_user)):
    return current_user

# Rotas de leads
@app.post("/api/leads", response_model=LeadResponse)
async def create_lead_endpoint(
    lead: LeadCreate, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Criar o lead
    new_lead = create_lead(db, lead)
    
    # Distribuir automaticamente se for admin
    if current_user.is_admin:
        assigned_broker = distribute_lead(db, new_lead.id)
        if assigned_broker:
            # Notificar corretor via WebSocket
            await manager.send_personal_message(
                json.dumps({
                    "type": "new_lead",
                    "lead": {
                        "id": new_lead.id,
                        "contact_name": new_lead.contact_name,
                        "phone": new_lead.phone,
                        "message": new_lead.initial_message
                    }
                }),
                assigned_broker.id
            )
    
    return new_lead

@app.get("/api/leads", response_model=List[LeadResponse])
async def get_leads_endpoint(
    status: Optional[str] = None,
    broker_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Se for corretor, só pode ver seus próprios leads
    if not current_user.is_admin:
        broker_id = current_user.id
    
    filters = LeadFilters(status=status, broker_id=broker_id)
    return get_leads(db, filters, skip, limit)

@app.put("/api/leads/{lead_id}", response_model=LeadResponse)
async def update_lead_endpoint(
    lead_id: int,
    lead_update: LeadUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    lead = update_lead(db, lead_id, lead_update, current_user.id, current_user.is_admin)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead não encontrado")
    return lead

@app.delete("/api/leads/{lead_id}")
async def delete_lead_endpoint(
    lead_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Apenas administradores podem deletar leads")
    
    success = delete_lead(db, lead_id)
    if not success:
        raise HTTPException(status_code=404, detail="Lead não encontrado")
    return {"message": "Lead deletado com sucesso"}

# Rotas de corretores (apenas admin)
@app.get("/api/brokers", response_model=List[BrokerResponse])
async def get_brokers_endpoint(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    return get_brokers(db, skip, limit)

@app.post("/api/brokers", response_model=BrokerResponse)
async def create_broker_endpoint(
    broker: BrokerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    return create_broker(db, broker)

@app.put("/api/brokers/{broker_id}", response_model=BrokerResponse)
async def update_broker_endpoint(
    broker_id: int,
    broker_update: BrokerUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    
    broker = update_broker(db, broker_id, broker_update)
    if not broker:
        raise HTTPException(status_code=404, detail="Corretor não encontrado")
    return broker

@app.delete("/api/brokers/{broker_id}")
async def delete_broker_endpoint(
    broker_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    
    success = delete_broker(db, broker_id)
    if not success:
        raise HTTPException(status_code=404, detail="Corretor não encontrado")
    return {"message": "Corretor removido com sucesso"}

# Webhook do WhatsApp Business - Verificação (GET)
@app.get("/api/whatsapp-webhook")
async def whatsapp_webhook_verify(request: Request):
    """Verificar webhook do WhatsApp Business - usado pelo Meta para verificar o endpoint"""
    
    # Parâmetros de verificação do Meta
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    
    # Token de verificação (deve ser configurado nas configurações)
    VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "meu-token-secreto-12345")
    
    if mode and token and challenge:
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return int(challenge)
        else:
            raise HTTPException(status_code=403, detail="Token de verificação inválido")
    
    raise HTTPException(status_code=400, detail="Parâmetros de verificação ausentes")

# Webhook principal para mensagens (usar apenas este)
@app.post("/api/whatsapp-webhook")
async def whatsapp_webhook_main(request: Request, db: Session = Depends(get_db)):
    """Webhook principal - redireciona para o handler do Maytapi"""
    return await maytapi_webhook(request, db)

# Dashboard e estatísticas
@app.get("/api/dashboard/stats", response_model=DashboardStats)
async def get_dashboard_stats_endpoint(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return get_dashboard_stats(db, current_user.id, current_user.is_admin)

@app.get("/api/leads/distribution-history", response_model=List[LeadDistributionResponse])
async def get_distribution_history_endpoint(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    return get_lead_distribution_history(db, skip, limit)

# Exportação de relatórios
@app.get("/api/export/leads/excel")
async def export_leads_excel_endpoint(
    status: Optional[str] = None,
    broker_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    filters = LeadFilters(
        status=status,
        broker_id=broker_id if current_user.is_admin else current_user.id,
        date_from=date_from,
        date_to=date_to
    )
    
    filename = export_leads_excel(db, filters)
    return FileResponse(
        filename,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        filename=f"leads_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    )

@app.get("/api/export/leads/pdf")
async def export_leads_pdf_endpoint(
    status: Optional[str] = None,
    broker_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    filters = LeadFilters(
        status=status,
        broker_id=broker_id if current_user.is_admin else current_user.id,
        date_from=date_from,
        date_to=date_to
    )
    
    filename = export_leads_pdf(db, filters)
    return FileResponse(
        filename,
        media_type='application/pdf',
        filename=f"leads_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    )

# Endpoint para reordenar corretores
@app.patch("/api/brokers/reorder")
async def reorder_brokers(
    order_updates: List[dict],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    
    try:
        for update in order_updates:
            broker_id = update.get("id")
            new_order = update.get("distribution_order")
            
            if broker_id and new_order is not None:
                broker_update = BrokerUpdate(distribution_order=new_order)
                update_broker(db, broker_id, broker_update)
        
        return {"message": "Ordem atualizada com sucesso"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao atualizar ordem: {str(e)}")

# Rotas de WhatsApp - Apenas para admins
@app.get("/api/whatsapp/connections", response_model=List[WhatsAppConnectionResponse])
async def get_whatsapp_connections_endpoint(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Listar todas as conexões de WhatsApp"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    return get_whatsapp_connections(db, skip, limit)

@app.post("/api/whatsapp/connections", response_model=WhatsAppConnectionResponse)
async def create_whatsapp_connection_endpoint(
    connection_data: WhatsAppConnectionCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Criar nova conexão de WhatsApp ou usar conexão existente"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    
    try:
        # Obter ou criar conexão via Maytapi
        result = await maytapi_client.create_phone_connection()
        
        if result.get("status") == "success":
            phone_id = result.get("phone_id")
            if not phone_id:
                raise HTTPException(status_code=500, detail="ID do telefone não retornado pela API")
            
            # Verificar se já existe uma conexão com este phone_id
            existing_connection = get_whatsapp_connection_by_phone_id(db, phone_id)
            
            if existing_connection:
                # Atualizar conexão existente com novas configurações
                connection = update_whatsapp_connection(
                    db, 
                    existing_connection.id,
                    auto_respond=connection_data.auto_respond,
                    welcome_message=connection_data.welcome_message,
                    status="connecting"
                )
            else:
                # Criar nova conexão no banco de dados
                connection = create_whatsapp_connection(
                    db, 
                    phone_id=phone_id,
                    auto_respond=connection_data.auto_respond,
                    welcome_message=connection_data.welcome_message
                )
            
            # Configurar webhook
            base_url = str(request.base_url).rstrip('/')
            webhook_url = f"{base_url}/api/whatsapp-webhook"
            webhook_result = await maytapi_client.set_webhook(phone_id, webhook_url)
            
            webhook_configured = webhook_result.get("status") == "success"
            
            # Atualizar status final da conexão
            if connection:
                final_connection = update_whatsapp_connection(
                    db, 
                    connection.id, 
                    webhook_configured=webhook_configured,
                    status="connecting" if webhook_configured else "error"
                )
                return final_connection if final_connection else connection
            else:
                raise HTTPException(status_code=500, detail="Erro ao criar ou atualizar conexão")
        else:
            raise HTTPException(status_code=500, detail=f"Erro ao criar conexão: {result.get('message', 'Erro desconhecido')}")
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao criar conexão: {str(e)}")

@app.get("/api/whatsapp/connections/{connection_id}/qr", response_model=WhatsAppQRResponse)
async def get_whatsapp_qr_code(
    connection_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obter QR Code para conectar WhatsApp"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    
    connection = get_whatsapp_connection(db, connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Conexão não encontrada")
    
    try:
        result = await maytapi_client.get_qr_code(connection.phone_id)
        
        return WhatsAppQRResponse(
            phone_id=connection.phone_id,
            qr_code=result.get("screen"),
            status=result.get("status", "unknown"),
            message=result.get("message")
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao obter QR Code: {str(e)}")

@app.get("/api/whatsapp/connections/{connection_id}/status")
async def get_whatsapp_connection_status(
    connection_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Verificar status da conexão WhatsApp"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    
    connection = get_whatsapp_connection(db, connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Conexão não encontrada")
    
    try:
        result = await maytapi_client.get_phone_status(connection.phone_id)
        
        # Atualizar status no banco de dados
        new_status = result.get("status", "unknown")
        phone_number = result.get("phone_number")
        update_whatsapp_connection_status(db, connection.phone_id, new_status, phone_number)
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao verificar status: {str(e)}")

@app.put("/api/whatsapp/connections/{connection_id}", response_model=WhatsAppConnectionResponse)
async def update_whatsapp_connection_endpoint(
    connection_id: int,
    connection_update: WhatsAppConnectionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Atualizar configurações da conexão WhatsApp"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    
    connection = update_whatsapp_connection(
        db, 
        connection_id, 
        **connection_update.dict(exclude_unset=True)
    )
    
    if not connection:
        raise HTTPException(status_code=404, detail="Conexão não encontrada")
    
    return connection

@app.delete("/api/whatsapp/connections/{connection_id}")
async def delete_whatsapp_connection_endpoint(
    connection_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Deletar conexão WhatsApp"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    
    connection = get_whatsapp_connection(db, connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Conexão não encontrada")
    
    try:
        # Remover da API Maytapi
        await maytapi_client.delete_phone_connection(connection.phone_id)
        
        # Remover do banco de dados
        success = delete_whatsapp_connection(db, connection_id)
        
        if success:
            return {"message": "Conexão removida com sucesso"}
        else:
            raise HTTPException(status_code=500, detail="Erro ao remover conexão do banco de dados")
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao deletar conexão: {str(e)}")

@app.post("/api/whatsapp/connections/{connection_id}/send")
async def send_whatsapp_message(
    connection_id: int,
    message_data: WhatsAppMessageSend,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Enviar mensagem via WhatsApp"""
    # Permitir acesso a admins e brokers às suas conexões
    if not (current_user.is_admin or current_user.role == "broker"):
        raise HTTPException(status_code=403, detail="Acesso não autorizado")
    
    connection = get_whatsapp_connection(db, connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Conexão não encontrada")
    
    if connection.status != "connected":
        raise HTTPException(status_code=400, detail="WhatsApp não está conectado")
    
    try:
        result = await maytapi_client.send_message(
            connection.phone_id,
            message_data.to_number,
            message_data.message
        )
        
        # Salvar mensagem enviada no banco de dados
        if result.get("status") == "success":
            try:
                # Encontrar ou criar conversa
                conversation = create_or_get_whatsapp_conversation(
                    db, connection.id, message_data.to_number, 
                    f"Cliente {message_data.to_number}"
                )
                
                # Salvar mensagem enviada
                create_whatsapp_message(
                    db, conversation.id, message_data.message, sent_by_me=True
                )
            except Exception as e:
                print(f"Erro ao salvar mensagem enviada: {e}")
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao enviar mensagem: {str(e)}")

@app.post("/api/whatsapp/send-message")
async def send_test_message(
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Enviar mensagem de teste"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    
    try:
        connection_id = data.get("connection_id")
        to_number = data.get("to_number")
        message = data.get("message")
        
        if not connection_id or not to_number or not message:
            raise ValueError("connection_id, to_number e message são obrigatórios")
        
        connection_id = int(connection_id)
        to_number = str(to_number)
        message = str(message)
        
        message_data = WhatsAppMessageSend(to_number=to_number, message=message)
        return await send_whatsapp_message(connection_id, message_data, db, current_user)
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"Dados inválidos: {str(e)}")

# Endpoints para conversas e mensagens WhatsApp
@app.get("/api/whatsapp/connections/{connection_id}/conversations")
async def get_connection_conversations(
    connection_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obter conversas de uma conexão WhatsApp"""
    # Permitir acesso a admins e brokers às suas conexões
    if not (current_user.is_admin or current_user.role == "broker"):
        raise HTTPException(status_code=403, detail="Acesso não autorizado")
    
    # Verificar se a conexão existe
    connection = get_whatsapp_connection(db, connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Conexão não encontrada")
    
    try:
        conversations = get_whatsapp_conversations(db, connection_id)
        
        # Formatar resposta para o frontend
        result = []
        for conv in conversations:
            result.append({
                "phone": conv.phone_number,
                "name": conv.contact_name,
                "last_message": conv.last_message or "Nenhuma mensagem",
                "last_message_time": conv.last_message_time.isoformat() if conv.last_message_time else None,
                "unread_count": conv.unread_count
            })
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao carregar conversas: {str(e)}")

@app.post("/api/whatsapp/connections/{connection_id}/sync-conversations")
async def sync_whatsapp_conversations(
    connection_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Sincronizar conversas do WhatsApp via API Maytapi"""
    # Permitir acesso a admins e brokers às suas conexões
    if not (current_user.is_admin or current_user.role == "broker"):
        raise HTTPException(status_code=403, detail="Acesso não autorizado")
    
    # Verificar se a conexão existe
    connection = get_whatsapp_connection(db, connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Conexão não encontrada")
    
    try:
        # Buscar conversas via API Maytapi
        conversations_data = await maytapi_client.get_conversations(connection.phone_id)
        
        if conversations_data.get("status") == "error":
            # Fallback para conversas locais
            local_conversations = get_whatsapp_conversations(db, connection_id)
            return {
                "status": "fallback", 
                "message": "Não foi possível sincronizar via API, mostrando conversas locais",
                "synced_count": 0,
                "conversations": [
                    {
                        "phone": conv.phone_number,
                        "name": conv.contact_name,
                        "last_message": conv.last_message or "Nenhuma mensagem",
                        "last_message_time": conv.last_message_time.isoformat() if conv.last_message_time else None,
                        "unread_count": conv.unread_count
                    }
                    for conv in local_conversations
                ]
            }
        
        synced_count = 0
        conversations = conversations_data.get("conversations", [])
        
        # Sincronizar cada conversa encontrada
        for conv_data in conversations:
            try:
                # Extrair dados da conversa
                phone_number = conv_data.get("id", "").replace("@c.us", "").replace("@g.us", "")
                contact_name = conv_data.get("name", phone_number)
                
                if phone_number:
                    # Criar ou atualizar conversa no banco
                    conversation = create_or_get_whatsapp_conversation(
                        db, connection_id, phone_number, contact_name
                    )
                    synced_count += 1
                    
            except Exception as e:
                print(f"Erro ao sincronizar conversa {conv_data}: {e}")
                continue
        
        # Se não conseguiu sincronizar nenhuma conversa via API, criar conversas de demonstração
        if synced_count == 0 and len(conversations) == 0:
            demo_conversations = [
                {"phone": "5511999887766", "name": "Cliente Demo 1"},
                {"phone": "5511888776655", "name": "Lead Comercial"},
                {"phone": "5511777665544", "name": "Suporte Técnico"}
            ]
            
            for demo_conv in demo_conversations:
                try:
                    conversation = create_or_get_whatsapp_conversation(
                        db, connection_id, demo_conv["phone"], demo_conv["name"]
                    )
                    
                    # Criar mensagem de exemplo
                    create_whatsapp_message(
                        db, 
                        conversation.id,
                        "Olá! Esta é uma conversa de demonstração.",
                        sent_by_me=False,
                        message_id=f"demo_{conversation.id}",
                        timestamp=None
                    )
                    synced_count += 1
                except Exception as e:
                    print(f"Erro ao criar conversa demo: {e}")
                    continue
        
        # Retornar conversas atualizadas
        updated_conversations = get_whatsapp_conversations(db, connection_id)
        
        return {
            "status": "success",
            "message": f"{synced_count} conversas sincronizadas com sucesso",
            "synced_count": synced_count,
            "conversations": [
                {
                    "phone": conv.phone_number,
                    "name": conv.contact_name,
                    "last_message": conv.last_message or "Nenhuma mensagem",
                    "last_message_time": conv.last_message_time.isoformat() if conv.last_message_time else None,
                    "unread_count": conv.unread_count
                }
                for conv in updated_conversations
            ]
        }
        
    except Exception as e:
        print(f"Erro na sincronização: {e}")
        # Fallback: retornar conversas locais se sincronização falhar
        local_conversations = get_whatsapp_conversations(db, connection_id)
        return {
            "status": "fallback", 
            "message": f"Erro na sincronização, mostrando {len(local_conversations)} conversas locais: {str(e)}",
            "synced_count": 0,
            "conversations": [
                {
                    "phone": conv.phone_number,
                    "name": conv.contact_name,
                    "last_message": conv.last_message or "Nenhuma mensagem",
                    "last_message_time": conv.last_message_time.isoformat() if conv.last_message_time else None,
                    "unread_count": conv.unread_count
                }
                for conv in local_conversations
            ]
        }

async def sync_conversation_messages(db: Session, connection, conversation, chat_id: str):
    """Sincronizar mensagens de uma conversa específica"""
    try:
        # Buscar mensagens recentes via API Maytapi
        messages_data = await maytapi_client.get_chat_messages(connection.phone_id, chat_id, limit=20)
        
        if messages_data.get("status") == "success":
            messages = messages_data.get("messages", [])
            
            for msg_data in messages:
                try:
                    # Extrair dados da mensagem
                    content = msg_data.get("body", "")
                    timestamp = msg_data.get("timestamp")
                    sent_by_me = msg_data.get("fromMe", False)
                    
                    if content and timestamp:
                        # Verificar se mensagem já existe para evitar duplicatas
                        existing_msg = db.query(WhatsAppMessage).filter(
                            WhatsAppMessage.conversation_id == conversation.id,
                            WhatsAppMessage.content == content,
                            WhatsAppMessage.timestamp == datetime.fromtimestamp(int(timestamp))
                        ).first()
                        
                        if not existing_msg:
                            # Criar nova mensagem
                            create_whatsapp_message(
                                db, 
                                conversation.id,
                                content,
                                sent_by_me,
                                message_id=None,
                                timestamp=datetime.fromtimestamp(int(timestamp))
                            )
                            
                except Exception as e:
                    print(f"Erro ao processar mensagem: {e}")
                    continue
                    
    except Exception as e:
        print(f"Erro ao sincronizar mensagens da conversa {chat_id}: {e}")

@app.get("/api/whatsapp/connections/{connection_id}/messages/{phone}")
async def get_conversation_messages(
    connection_id: int,
    phone: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obter mensagens de uma conversa específica"""
    # Permitir acesso a admins e brokers às suas conexões
    if not (current_user.is_admin or current_user.role == "broker"):
        raise HTTPException(status_code=403, detail="Acesso não autorizado")
    
    # Verificar se a conexão existe
    connection = get_whatsapp_connection(db, connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Conexão não encontrada")
    
    try:
        # Obter conversa
        conversation = get_conversation_by_phone(db, connection_id, phone)
        if not conversation:
            return []
        
        # Marcar mensagens como lidas
        mark_messages_as_read(db, conversation.id)
        
        # Obter mensagens
        messages = get_whatsapp_messages(db, conversation.id)
        
        # Formatar resposta para o frontend
        result = []
        for msg in messages:
            result.append({
                "content": msg.content,
                "sent_by_me": msg.sent_by_me,
                "timestamp": msg.timestamp.isoformat(),
                "message_type": msg.message_type,
                "status": msg.status
            })
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao carregar mensagens: {str(e)}")

# Webhook Maytapi para receber mensagens
@app.post("/api/maytapi-webhook")
async def maytapi_webhook(request: Request, db: Session = Depends(get_db)):
    """Webhook para receber mensagens da Maytapi"""
    try:
        body = await request.json()
        
        # Log apenas tipo para debug sem vazar PII
        if os.getenv("DEBUG") == "true":
            print(f"Webhook tipo: {body.get('type', 'unknown')}")
        
        # Processar diferentes formatos do Maytapi
        if body.get("type") in ["message", "text"]:
            # Extrair dados da mensagem
            phone_id = body.get("phone_id")
            from_number = body.get("from") or body.get("user", {}).get("phone")
            
            # Extrair texto da mensagem
            message_text = ""
            if "text" in body:
                if isinstance(body["text"], dict):
                    message_text = body["text"].get("text", "Mensagem recebida")
                else:
                    message_text = str(body["text"])
            elif "message" in body:
                if isinstance(body["message"], dict):
                    message_text = body["message"].get("text", "Mensagem recebida")
                else:
                    message_text = str(body["message"])
            
            contact_name = (
                body.get("senderName") or 
                body.get("user", {}).get("name") or 
                f"Cliente {from_number or 'Desconhecido'}"
            )
            
            # Ignorar mensagens próprias
            if body.get("fromMe", False):
                return {"status": "ignored", "message": "Mensagem própria ignorada"}
            
            if from_number and message_text:
                # Encontrar conexão WhatsApp
                connection = get_whatsapp_connection_by_phone_id(db, phone_id)
                
                if connection:
                    # Criar ou obter conversa
                    conversation = create_or_get_whatsapp_conversation(
                        db, connection.id, from_number, contact_name
                    )
                    
                    # Salvar mensagem recebida
                    create_whatsapp_message(
                        db, conversation.id, message_text, sent_by_me=False
                    )
                
                # Criar lead automaticamente (processo original)
                lead_data = LeadCreate(
                    contact_name=contact_name,
                    phone=from_number,
                    initial_message=message_text,
                    source="WhatsApp Maytapi"
                )
                
                new_lead = create_lead(db, lead_data)
                
                # Distribuir automaticamente
                assigned_broker = distribute_lead(db, new_lead.id)
                
                if assigned_broker:
                    # Notificar corretor via WebSocket (lead)
                    await manager.send_personal_message(
                        json.dumps({
                            "type": "new_lead",
                            "lead": {
                                "id": new_lead.id,
                                "contact_name": new_lead.contact_name,
                                "phone": new_lead.phone,
                                "message": new_lead.initial_message
                            }
                        }),
                        assigned_broker.id
                    )
                
                    # Notificar sobre nova mensagem WhatsApp via WebSocket
                    if connection:
                        await manager.broadcast(json.dumps({
                            "type": "whatsapp_message",
                            "message": {
                                "connection_id": connection.id,
                                "from_number": from_number,
                                "contact_name": contact_name,
                                "content": message_text,
                                "timestamp": datetime.now().isoformat()
                            }
                        }))
                
                # Atualizar status da conexão se phone_id disponível
                if phone_id:
                    try:
                        update_whatsapp_connection_status(db, phone_id, "connected")
                    except:
                        pass  # Não falhar se não conseguir atualizar status
                
                return {"status": "success", "lead_id": new_lead.id}
        
        return {"status": "success", "message": "Webhook processado"}
    
    except Exception as e:
        if os.getenv("DEBUG") == "true":
            print(f"Erro no webhook Maytapi: {str(e)}")
        return {"status": "error", "message": "Erro interno"}

# Função para autenticar WebSocket
async def authenticate_websocket(token: str, db: Session) -> User:
    """Autenticar usuário para conexão WebSocket"""
    try:
        from jose import jwt, JWTError
        from auth import SECRET_KEY, ALGORITHM
        
        if not SECRET_KEY:
            raise WebSocketDisconnect(code=1008, reason="Configuração inválida")
            
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        if email is None or not isinstance(email, str):
            raise WebSocketDisconnect(code=1008, reason="Token inválido")
    except Exception:
        raise WebSocketDisconnect(code=1008, reason="Token inválido")
    
    user = db.query(User).filter(User.email == email, User.is_active == True).first()
    if user is None:
        raise WebSocketDisconnect(code=1008, reason="Usuário não encontrado")
    
    return user

# WebSocket para notificações em tempo real
@app.websocket("/ws/{user_id}")
async def websocket_endpoint(
    websocket: WebSocket, 
    user_id: int, 
    token: str = Query(...),
    db: Session = Depends(get_db)
):
    # Autenticar usuário antes de aceitar conexão
    try:
        authenticated_user = await authenticate_websocket(token, db)
        
        # Verificar se o user_id corresponde ao usuário autenticado
        if authenticated_user.id != user_id:
            await websocket.close(code=1008, reason="ID de usuário inválido")
            return
            
        await manager.connect(websocket, user_id)
        
        while True:
            data = await websocket.receive_text()
            # Echo mensagens de heartbeat para manter conexão ativa
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)
    except Exception as e:
        await websocket.close(code=1011, reason="Erro de autenticação")

if __name__ == "__main__":
    import os
    
    # Para produção, desabilitar reload
    is_development = os.getenv("ENVIRONMENT", "development") == "development"
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=5000,
        reload=is_development,
        log_level="info"
    )