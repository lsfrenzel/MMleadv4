"""
Script para inicializar o banco de dados e criar usuário administrador padrão
"""
from database import create_tables, get_db
from models import User, UserRole
from auth import get_password_hash
from sqlalchemy.orm import Session
import os

def create_admin_user():
    """Criar usuário administrador padrão se não existir"""
    db = next(get_db())
    
    try:
        # Verificar se já existe um admin
        admin = db.query(User).filter(User.is_admin == True).first()
        if admin:
            print(f"Administrador já existe: {admin.email}")
            return
        
        # Criar usuário admin padrão
        admin_user = User(
            name="Administrador",
            email="admin@leads.com",
            password_hash=get_password_hash("admin123"),
            is_admin=True,
            role=UserRole.ADMIN,
            is_active=True
        )
        
        db.add(admin_user)
        db.commit()
        
        print("✅ Usuário administrador criado com sucesso!")
        print("Email: admin@leads.com")
        print("Senha: admin123")
        print("⚠️ IMPORTANTE: Altere a senha após o primeiro login!")
        
    except Exception as e:
        print(f"❌ Erro ao criar usuário administrador: {e}")
        db.rollback()
    finally:
        db.close()

def init_database():
    """Inicializar banco de dados"""
    try:
        print("Criando tabelas do banco de dados...")
        create_tables()
        print("✅ Tabelas criadas com sucesso!")
        
        print("Criando usuário administrador...")
        create_admin_user()
        
        print("\n🎉 Inicialização concluída!")
        print("Você pode agora executar o servidor com: python main.py")
        
    except Exception as e:
        print(f"❌ Erro durante a inicialização: {e}")

if __name__ == "__main__":
    # Verificar se DATABASE_URL está configurada
    if not os.getenv("DATABASE_URL"):
        print("❌ Erro: DATABASE_URL não encontrada nas variáveis de ambiente")
        print("Certifique-se de que o banco PostgreSQL está configurado")
        exit(1)
    
    init_database()