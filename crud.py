from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, and_, or_, desc, asc
from datetime import datetime, timedelta
from typing import List, Optional
import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
import os

# Importações locais
from models import User, Lead, Broker, LeadDistribution, LeadStatus, LeadStatusEnum, WhatsAppConnection
from schemas import (
    UserCreate, LeadCreate, LeadUpdate, BrokerCreate, BrokerUpdate,
    LeadFilters, DashboardStats
)
from auth import get_password_hash

# CRUD de usuários
def create_user(db: Session, user: UserCreate) -> User:
    """Criar novo usuário"""
    db_user = User(
        name=user.name,
        email=user.email,
        password_hash=get_password_hash(user.password),
        is_admin=user.is_admin,
        role=user.role
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def get_user_by_email(db: Session, email: str) -> Optional[User]:
    """Buscar usuário por email"""
    return db.query(User).filter(User.email == email).first()

def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
    """Buscar usuário por ID"""
    return db.query(User).filter(User.id == user_id).first()

# CRUD de leads
def create_lead(db: Session, lead: LeadCreate) -> Lead:
    """Criar novo lead"""
    db_lead = Lead(
        contact_name=lead.contact_name,
        phone=lead.phone,
        initial_message=lead.initial_message,
        source=lead.source,
        notes=lead.notes
    )
    db.add(db_lead)
    db.commit()
    db.refresh(db_lead)
    return db_lead

def get_leads(db: Session, filters: LeadFilters, skip: int = 0, limit: int = 100) -> List[Lead]:
    """Buscar leads com filtros"""
    query = db.query(Lead).options(joinedload(Lead.assigned_broker))
    
    # Aplicar filtros
    if filters.status:
        try:
            # Converter string para enum se necessário
            status_enum = LeadStatusEnum(filters.status) if isinstance(filters.status, str) else filters.status
            query = query.filter(Lead.status == status_enum)
        except ValueError:
            # Se o status não for válido, ignorar filtro
            pass
    
    if filters.broker_id:
        query = query.filter(Lead.assigned_broker_id == filters.broker_id)
    
    if filters.source:
        query = query.filter(Lead.source == filters.source)
    
    if filters.date_from:
        try:
            date_from = datetime.fromisoformat(filters.date_from)
            query = query.filter(Lead.created_at >= date_from)
        except ValueError:
            pass
    
    if filters.date_to:
        try:
            date_to = datetime.fromisoformat(filters.date_to)
            query = query.filter(Lead.created_at <= date_to)
        except ValueError:
            pass
    
    return query.order_by(desc(Lead.created_at)).offset(skip).limit(limit).all()

def get_lead_by_id(db: Session, lead_id: int) -> Optional[Lead]:
    """Buscar lead por ID"""
    return db.query(Lead).options(joinedload(Lead.assigned_broker)).filter(Lead.id == lead_id).first()

def update_lead(db: Session, lead_id: int, lead_update: LeadUpdate, user_id: int, is_admin: bool) -> Optional[Lead]:
    """Atualizar lead"""
    query = db.query(Lead).filter(Lead.id == lead_id)
    
    # Se não for admin, só pode editar leads atribuídos a ele
    if not is_admin:
        query = query.filter(Lead.assigned_broker_id == user_id)
    
    db_lead = query.first()
    if not db_lead:
        return None
    
    # Atualizar campos fornecidos
    update_data = lead_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_lead, field, value)
    
    # updated_at será atualizado automaticamente pelo onupdate
    db.commit()
    db.refresh(db_lead)
    return db_lead

def delete_lead(db: Session, lead_id: int) -> bool:
    """Deletar lead"""
    db_lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not db_lead:
        return False
    
    db.delete(db_lead)
    db.commit()
    return True

# CRUD de corretores
def get_brokers(db: Session, skip: int = 0, limit: int = 100) -> List[Broker]:
    """Buscar corretores"""
    return (db.query(Broker)
            .options(joinedload(Broker.user))
            .filter(Broker.is_active == True)
            .order_by(asc(Broker.distribution_order))
            .offset(skip)
            .limit(limit)
            .all())

def create_broker(db: Session, broker: BrokerCreate) -> Broker:
    """Criar novo corretor"""
    db_broker = Broker(
        user_id=broker.user_id,
        distribution_order=broker.distribution_order,
        is_active=broker.is_active,
        max_leads_per_day=broker.max_leads_per_day
    )
    db.add(db_broker)
    db.commit()
    db.refresh(db_broker)
    return db_broker

def update_broker(db: Session, broker_id: int, broker_update: BrokerUpdate) -> Optional[Broker]:
    """Atualizar corretor"""
    db_broker = db.query(Broker).filter(Broker.id == broker_id).first()
    if not db_broker:
        return None
    
    update_data = broker_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_broker, field, value)
    
    # updated_at será atualizado automaticamente pelo onupdate
    db.commit()
    db.refresh(db_broker)
    return db_broker

def delete_broker(db: Session, broker_id: int) -> bool:
    """Deletar corretor"""
    db_broker = db.query(Broker).filter(Broker.id == broker_id).first()
    if not db_broker:
        return False
    
    db.delete(db_broker)
    db.commit()
    return True

# Distribuição de leads
def distribute_lead(db: Session, lead_id: int) -> Optional[User]:
    """Distribuir lead para o próximo corretor na ordem"""
    # Buscar próximo corretor ativo na ordem de distribuição
    brokers = (db.query(Broker)
               .options(joinedload(Broker.user))
               .filter(Broker.is_active == True)
               .order_by(asc(Broker.distribution_order))
               .all())
    
    if not brokers:
        return None
    
    # Verificar quantos leads cada corretor recebeu hoje
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    
    for broker in brokers:
        # Contar leads distribuídos hoje para este corretor
        leads_today = (db.query(LeadDistribution)
                      .filter(
                          LeadDistribution.broker_id == broker.user_id,
                          LeadDistribution.distributed_at >= today
                      )
                      .count())
        
        # Verificar se não excedeu o limite diário
        if leads_today < broker.max_leads_per_day:
            # Atribuir lead ao corretor
            lead = db.query(Lead).filter(Lead.id == lead_id).first()
            if lead:
                lead.assigned_broker_id = broker.user_id
                lead.assigned_at = datetime.utcnow()
                
                # Registrar histórico de distribuição
                distribution = LeadDistribution(
                    lead_id=lead_id,
                    broker_id=broker.user_id,
                    distribution_method="automatic"
                )
                
                db.add(distribution)
                db.commit()
                
                return broker.user
    
    return None

def get_lead_distribution_history(db: Session, skip: int = 0, limit: int = 100) -> List[LeadDistribution]:
    """Buscar histórico de distribuição de leads"""
    return (db.query(LeadDistribution)
            .options(joinedload(LeadDistribution.lead), joinedload(LeadDistribution.broker))
            .order_by(desc(LeadDistribution.distributed_at))
            .offset(skip)
            .limit(limit)
            .all())

# Dashboard e estatísticas
def get_dashboard_stats(db: Session, user_id: int, is_admin: bool) -> DashboardStats:
    """Obter estatísticas para o dashboard"""
    now = datetime.utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)
    
    # Query base de leads
    query = db.query(Lead)
    if not is_admin:
        query = query.filter(Lead.assigned_broker_id == user_id)
    
    # Total de leads
    total_leads = query.count()
    
    # Leads hoje
    leads_today = query.filter(Lead.created_at >= today).count()
    
    # Leads esta semana
    leads_this_week = query.filter(Lead.created_at >= week_ago).count()
    
    # Leads este mês
    leads_this_month = query.filter(Lead.created_at >= month_ago).count()
    
    # Leads por status
    leads_by_status = {}
    for status in LeadStatusEnum:
        count = query.filter(Lead.status == status).count()
        leads_by_status[status.value] = count
    
    # Leads por corretor (apenas para admin)
    leads_by_broker = {}
    if is_admin:
        broker_stats = (db.query(User.name, func.count(Lead.id))
                       .outerjoin(Lead, User.id == Lead.assigned_broker_id)
                       .filter(User.role == "broker")
                       .group_by(User.id, User.name)
                       .all())
        
        for name, count in broker_stats:
            if name:  # Verificar se name não é None
                leads_by_broker[name] = count
    
    # Taxa de conversão (leads fechados / total de leads)
    closed_leads = query.filter(Lead.status == LeadStatusEnum.FECHADO).count()
    conversion_rate = (closed_leads / total_leads * 100) if total_leads > 0 else 0
    
    return DashboardStats(
        total_leads=total_leads,
        leads_today=leads_today,
        leads_this_week=leads_this_week,
        leads_this_month=leads_this_month,
        leads_by_status=leads_by_status,
        leads_by_broker=leads_by_broker,
        conversion_rate=conversion_rate,
        average_response_time=None  # Pode ser implementado posteriormente
    )

# Exportação de relatórios
def export_leads_excel(db: Session, filters: LeadFilters) -> str:
    """Exportar leads para Excel"""
    leads = get_leads(db, filters, skip=0, limit=10000)  # Máximo 10k leads
    
    # Preparar dados para DataFrame
    data = []
    for lead in leads:
        data.append({
            'ID': lead.id,
            'Nome do Contato': lead.contact_name,
            'Telefone': lead.phone,
            'Status': lead.status.value,
            'Mensagem': lead.initial_message or '',
            'Fonte': lead.source,
            'Corretor': lead.assigned_broker.name if lead.assigned_broker else 'Não atribuído',
            'Criado em': lead.created_at.strftime('%d/%m/%Y %H:%M'),
            'Atribuído em': lead.assigned_at.strftime('%d/%m/%Y %H:%M') if lead.assigned_at else '',
            'Observações': lead.notes or ''
        })
    
    # Criar DataFrame e exportar
    df = pd.DataFrame(data)
    filename = f"leads_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    df.to_excel(filename, index=False, engine='openpyxl')
    
    return filename

def export_leads_pdf(db: Session, filters: LeadFilters) -> str:
    """Exportar leads para PDF"""
    leads = get_leads(db, filters, skip=0, limit=1000)  # Máximo 1k leads para PDF
    
    filename = f"leads_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    doc = SimpleDocTemplate(filename, pagesize=letter)
    
    # Estilos
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        spaceAfter=30,
        alignment=1  # Centralizado
    )
    
    # Conteúdo do PDF
    story = []
    
    # Título
    title = Paragraph("Relatório de Leads", title_style)
    story.append(title)
    story.append(Spacer(1, 20))
    
    # Preparar dados da tabela
    data = [['ID', 'Nome', 'Telefone', 'Status', 'Corretor', 'Criado em']]
    
    for lead in leads:
        row = [
            str(lead.id),
            lead.contact_name[:20] + '...' if len(lead.contact_name) > 20 else lead.contact_name,
            lead.phone,
            lead.status.value,
            lead.assigned_broker.name[:15] + '...' if lead.assigned_broker and len(lead.assigned_broker.name) > 15 else (lead.assigned_broker.name if lead.assigned_broker else 'N/A'),
            lead.created_at.strftime('%d/%m/%Y')
        ]
        data.append(row)
    
    # Criar tabela
    table = Table(data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    
    story.append(table)
    
    # Gerar PDF
    doc.build(story)
    
    return filename

# CRUD de WhatsApp Connections
def create_whatsapp_connection(db: Session, phone_id: str, auto_respond: bool = False, welcome_message: Optional[str] = None) -> WhatsAppConnection:
    """Criar nova conexão de WhatsApp"""
    db_connection = WhatsAppConnection(
        phone_id=phone_id,
        auto_respond=auto_respond,
        welcome_message=welcome_message,
        status="disconnected"
    )
    db.add(db_connection)
    db.commit()
    db.refresh(db_connection)
    return db_connection

def get_whatsapp_connections(db: Session, skip: int = 0, limit: int = 100) -> List[WhatsAppConnection]:
    """Listar conexões de WhatsApp"""
    return db.query(WhatsAppConnection).offset(skip).limit(limit).all()

def get_whatsapp_connection(db: Session, connection_id: int) -> Optional[WhatsAppConnection]:
    """Buscar conexão de WhatsApp por ID"""
    return db.query(WhatsAppConnection).filter(WhatsAppConnection.id == connection_id).first()

def get_whatsapp_connection_by_phone_id(db: Session, phone_id: str) -> Optional[WhatsAppConnection]:
    """Buscar conexão de WhatsApp por phone_id"""
    return db.query(WhatsAppConnection).filter(WhatsAppConnection.phone_id == phone_id).first()

def update_whatsapp_connection(db: Session, connection_id: int, **kwargs) -> Optional[WhatsAppConnection]:
    """Atualizar conexão de WhatsApp"""
    connection = db.query(WhatsAppConnection).filter(WhatsAppConnection.id == connection_id).first()
    if connection:
        for key, value in kwargs.items():
            if hasattr(connection, key):
                setattr(connection, key, value)
        connection.updated_at = datetime.now()
        db.commit()
        db.refresh(connection)
    return connection

def update_whatsapp_connection_status(db: Session, phone_id: str, status: str, phone_number: Optional[str] = None) -> Optional[WhatsAppConnection]:
    """Atualizar status da conexão WhatsApp"""
    connection = db.query(WhatsAppConnection).filter(WhatsAppConnection.phone_id == phone_id).first()
    if connection:
        connection.status = status
        connection.last_seen = datetime.now()
        if phone_number:
            connection.phone_number = phone_number
        db.commit()
        db.refresh(connection)
    return connection

def delete_whatsapp_connection(db: Session, connection_id: int) -> bool:
    """Deletar conexão de WhatsApp"""
    connection = db.query(WhatsAppConnection).filter(WhatsAppConnection.id == connection_id).first()
    if connection:
        db.delete(connection)
        db.commit()
        return True
    return False