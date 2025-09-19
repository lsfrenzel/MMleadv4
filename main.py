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
from models import User, Lead, Broker, LeadDistribution, LeadStatus, WhatsAppConnection
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
    update_whatsapp_connection_status, delete_whatsapp_connection
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

# Webhook do WhatsApp Business - Recebimento de mensagens (POST)
@app.post("/api/whatsapp-webhook")
async def whatsapp_webhook(request: Request, db: Session = Depends(get_db)):
    """Recebe mensagens do WhatsApp Business e cria leads automaticamente"""
    try:
        # Obter dados do corpo da requisição
        body = await request.json()
        
        # Processar formato do WhatsApp Business API
        if "entry" in body:
            # Formato padrão do Meta WhatsApp API
            for entry in body.get("entry", []):
                for change in entry.get("changes", []):
                    if change.get("field") == "messages":
                        value = change.get("value", {})
                        
                        # Extrair mensagens
                        for message in value.get("messages", []):
                            # Obter informações do contato
                            contact = {}
                            for contact_info in value.get("contacts", []):
                                if contact_info.get("wa_id") == message.get("from"):
                                    contact = contact_info
                                    break
                            
                            # Criar lead
                            lead_data = LeadCreate(
                                contact_name=contact.get("profile", {}).get("name", f"Cliente {message.get('from', 'Desconhecido')}"),
                                phone=message.get("from", ""),
                                initial_message=message.get("text", {}).get("body", "Mensagem recebida via WhatsApp"),
                                source="WhatsApp Business"
                            )
                            
                            new_lead = create_lead(db, lead_data)
                            
                            # Distribuir automaticamente
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
        
        # Formato simples para testes
        else:
            lead_data = LeadCreate(
                contact_name=body.get("contact_name", "Cliente Desconhecido"),
                phone=body.get("phone", ""),
                initial_message=body.get("message", "Mensagem recebida via WhatsApp"),
                source="WhatsApp Business"
            )
        
            new_lead = create_lead(db, lead_data)
            
            # Distribuir automaticamente
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
        
        return {"status": "success", "message": "Webhook processado com sucesso"}
    
    except Exception as e:
        print(f"Erro no webhook WhatsApp: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao processar webhook: {str(e)}")

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
    """Criar nova conexão de WhatsApp"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    
    try:
        # Criar nova conexão via Maytapi
        result = await maytapi_client.create_phone_connection()
        
        if result.get("status") == "success":
            phone_id = result.get("phone_id")
            if not phone_id:
                raise HTTPException(status_code=500, detail="ID do telefone não retornado pela API")
            
            # Salvar no banco de dados
            connection = create_whatsapp_connection(
                db, 
                phone_id=phone_id,
                auto_respond=connection_data.auto_respond,
                welcome_message=connection_data.welcome_message
            )
            
            # Configurar webhook se necessário
            base_url = str(request.base_url).rstrip('/')
            webhook_url = f"{base_url}/api/maytapi-webhook"
            webhook_result = await maytapi_client.set_webhook(phone_id, webhook_url)
            
            webhook_configured = webhook_result.get("status") == "success"
            update_whatsapp_connection(db, connection.id, 
                                     webhook_configured=webhook_configured,
                                     status="connecting" if webhook_configured else "error")
            
            return connection
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
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    
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
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao enviar mensagem: {str(e)}")

# Webhook Maytapi para receber mensagens
@app.post("/api/maytapi-webhook")
async def maytapi_webhook(request: Request, db: Session = Depends(get_db)):
    """Webhook para receber mensagens da Maytapi"""
    try:
        body = await request.json()
        
        # Processar mensagem da Maytapi
        if body.get("type") == "message":
            phone_id = body.get("phone_id")
            from_number = body.get("user", {}).get("phone")
            message = body.get("message", {}).get("text", "")
            contact_name = body.get("user", {}).get("name", f"Contato {from_number}")
            
            if phone_id and from_number and message:
                # Criar lead automaticamente
                lead_data = LeadCreate(
                    contact_name=contact_name,
                    phone=from_number,
                    initial_message=message,
                    source="WhatsApp Maytapi"
                )
                
                new_lead = create_lead(db, lead_data)
                
                # Distribuir automaticamente
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
                
                # Atualizar último acesso da conexão
                update_whatsapp_connection_status(db, phone_id, "connected")
        
        return {"status": "success"}
    
    except Exception as e:
        print(f"Erro no webhook Maytapi: {str(e)}")
        return {"status": "error", "message": str(e)}

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