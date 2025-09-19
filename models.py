from sqlalchemy import Integer, String, Boolean, DateTime, Text, ForeignKey, Enum
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.sql import func
from database import Base
import enum
from datetime import datetime
from typing import Optional

class UserRole(str, enum.Enum):
    ADMIN = "admin"
    BROKER = "broker"

class LeadStatusEnum(str, enum.Enum):
    NOVO = "novo"
    EM_ANDAMENTO = "em_andamento"  
    FECHADO = "fechado"
    PERDIDO = "perdido"

class User(Base):
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.BROKER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now())
    
    # Relacionamentos
    assigned_leads: Mapped[list["Lead"]] = relationship("Lead", back_populates="assigned_broker")
    distribution_history: Mapped[list["LeadDistribution"]] = relationship("LeadDistribution", back_populates="broker")

class Lead(Base):
    __tablename__ = "leads"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    contact_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    initial_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(50), default="Manual")
    status: Mapped[LeadStatusEnum] = mapped_column(Enum(LeadStatusEnum), default=LeadStatusEnum.NOVO)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Chaves estrangeiras
    assigned_broker_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now())
    assigned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Relacionamentos
    assigned_broker: Mapped[Optional["User"]] = relationship("User", back_populates="assigned_leads")
    distribution_history: Mapped[list["LeadDistribution"]] = relationship("LeadDistribution", back_populates="lead")

class Broker(Base):
    __tablename__ = "brokers"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    distribution_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    max_leads_per_day: Mapped[int] = mapped_column(Integer, default=50)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now())
    
    # Relacionamento com usuário
    user: Mapped["User"] = relationship("User")

class LeadDistribution(Base):
    __tablename__ = "lead_distributions"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    lead_id: Mapped[int] = mapped_column(Integer, ForeignKey("leads.id"), nullable=False)
    broker_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    distributed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    distribution_method: Mapped[str] = mapped_column(String(50), default="automatic")  # automatic, manual
    
    # Relacionamentos
    lead: Mapped["Lead"] = relationship("Lead", back_populates="distribution_history")
    broker: Mapped["User"] = relationship("User", back_populates="distribution_history")

class LeadStatus(Base):
    __tablename__ = "lead_statuses"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    color: Mapped[str] = mapped_column(String(7), default="#6B7280")  # Cor hex para UI
    description: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now())

class WhatsAppConnection(Base):
    __tablename__ = "whatsapp_connections"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    phone_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    phone_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="disconnected")  # disconnected, connecting, connected, error
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    webhook_configured: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Configurações
    auto_respond: Mapped[bool] = mapped_column(Boolean, default=False)
    welcome_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now())

class SystemConfig(Base):
    __tablename__ = "system_configs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now())