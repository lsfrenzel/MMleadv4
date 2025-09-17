from pydantic import BaseModel, EmailStr, validator
from datetime import datetime
from typing import Optional, List
from models import UserRole, LeadStatusEnum

# Schemas de usuário
class UserBase(BaseModel):
    name: str
    email: EmailStr
    is_admin: bool = False
    role: UserRole = UserRole.BROKER

class UserCreate(UserBase):
    password: str
    
    @validator('password')
    def validate_password(cls, v):
        if len(v) < 6:
            raise ValueError('Senha deve ter pelo menos 6 caracteres')
        return v

class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    is_admin: Optional[bool] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None

class UserResponse(UserBase):
    id: int
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse

# Schemas de leads
class LeadBase(BaseModel):
    contact_name: str
    phone: str
    initial_message: Optional[str] = None
    source: str = "Manual"
    notes: Optional[str] = None

class LeadCreate(LeadBase):
    pass

class LeadUpdate(BaseModel):
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    status: Optional[LeadStatusEnum] = None
    notes: Optional[str] = None
    assigned_broker_id: Optional[int] = None

class LeadResponse(LeadBase):
    id: int
    status: LeadStatusEnum
    assigned_broker_id: Optional[int]
    created_at: datetime
    updated_at: Optional[datetime]
    assigned_at: Optional[datetime]
    assigned_broker: Optional[UserResponse]
    
    class Config:
        from_attributes = True

# Schemas de corretores
class BrokerBase(BaseModel):
    distribution_order: int = 0
    is_active: bool = True
    max_leads_per_day: int = 50

class BrokerCreate(BrokerBase):
    user_id: int

class BrokerUpdate(BaseModel):
    distribution_order: Optional[int] = None
    is_active: Optional[bool] = None
    max_leads_per_day: Optional[int] = None

class BrokerResponse(BrokerBase):
    id: int
    user_id: int
    user: UserResponse
    created_at: datetime
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True

# Schema para histórico de distribuição
class LeadDistributionResponse(BaseModel):
    id: int
    lead_id: int
    broker_id: int
    distributed_at: datetime
    distribution_method: str
    lead: LeadResponse
    broker: UserResponse
    
    class Config:
        from_attributes = True

# Schema para webhook do WhatsApp
class WhatsAppWebhook(BaseModel):
    contact_name: str
    phone: str
    message: str
    timestamp: Optional[datetime] = None

# Schemas para dashboard e estatísticas
class DashboardStats(BaseModel):
    total_leads: int
    leads_today: int
    leads_this_week: int
    leads_this_month: int
    leads_by_status: dict
    leads_by_broker: dict
    conversion_rate: float
    average_response_time: Optional[float]

class LeadFilters(BaseModel):
    status: Optional[str] = None
    broker_id: Optional[int] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    source: Optional[str] = None

# Schema para status personalizados
class LeadStatusBase(BaseModel):
    name: str
    color: str = "#6B7280"
    description: Optional[str] = None
    is_active: bool = True
    sort_order: int = 0

class LeadStatusCreate(LeadStatusBase):
    pass

class LeadStatusUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None

class LeadStatusResponse(LeadStatusBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True

# Schema para configurações do sistema
class SystemConfigBase(BaseModel):
    key: str
    value: Optional[str] = None
    description: Optional[str] = None

class SystemConfigCreate(SystemConfigBase):
    pass

class SystemConfigUpdate(BaseModel):
    value: Optional[str] = None
    description: Optional[str] = None

class SystemConfigResponse(SystemConfigBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True