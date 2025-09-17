from fastapi import FastAPI, Depends, HTTPException, Request, status, WebSocket, WebSocketDisconnect
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
from models import User, Lead, Broker, LeadDistribution, LeadStatus
from auth import authenticate_user, create_access_token, get_current_user
from schemas import (
    UserCreate, UserResponse, UserLogin, Token,
    LeadCreate, LeadResponse, LeadUpdate,
    BrokerCreate, BrokerResponse, BrokerUpdate,
    LeadDistributionResponse, WhatsAppWebhook,
    DashboardStats, LeadFilters
)
from crud import (
    create_user, get_user_by_email, get_brokers,
    create_lead, get_leads, update_lead, delete_lead,
    create_broker, update_broker, delete_broker,
    get_lead_distribution_history, distribute_lead,
    get_dashboard_stats, export_leads_excel, export_leads_pdf
)

app = FastAPI(
    title="Sistema de Gestão de Leads WhatsApp",
    description="Sistema completo para captura e distribuição de leads via WhatsApp Business",
    version="1.0.0"
)

# Configuração CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
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

# Webhook do WhatsApp Business
@app.post("/api/whatsapp-webhook")
async def whatsapp_webhook(webhook_data: WhatsAppWebhook, db: Session = Depends(get_db)):
    """Recebe mensagens do WhatsApp Business e cria leads automaticamente"""
    try:
        # Criar lead baseado na mensagem recebida
        lead_data = LeadCreate(
            contact_name=webhook_data.contact_name,
            phone=webhook_data.phone,
            initial_message=webhook_data.message,
            source="WhatsApp Business"
        )
        
        new_lead = create_lead(db, lead_data)
        
        # Distribuir automaticamente para o próximo corretor
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
        
        return {"status": "success", "lead_id": new_lead.id}
    
    except Exception as e:
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

# WebSocket para notificações em tempo real
@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int, db: Session = Depends(get_db)):
    await manager.connect(websocket, user_id)
    try:
        while True:
            data = await websocket.receive_text()
            # Echo mensagens de heartbeat para manter conexão ativa
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=5000,
        reload=True,
        log_level="info"
    )