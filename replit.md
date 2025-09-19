# WhatsApp Lead Management System

## Project Overview
This is a complete WhatsApp lead management system built with FastAPI (backend) and HTML/JavaScript (frontend). The application captures leads from WhatsApp Business API webhooks and distributes them to brokers automatically.

## Architecture
- **Backend**: FastAPI with SQLAlchemy and PostgreSQL
- **Frontend**: HTML templates with Bootstrap, JavaScript
- **Database**: PostgreSQL (Replit managed)
- **Real-time**: WebSocket connections for live notifications

## Key Features
- WhatsApp Business API webhook integration
- Automatic lead distribution to brokers
- Real-time notifications via WebSocket
- User authentication with JWT tokens
- Admin and broker role management
- Export functionality (Excel/PDF)
- Dashboard with statistics

## Recent Changes (Dec 19, 2025)
- ✅ Successfully imported from GitHub
- ✅ Set up PostgreSQL database connection
- ✅ Installed all Python dependencies via uv
- ✅ Initialized database tables
- ✅ Created admin user (admin@leads.com / admin123)
- ✅ Configured workflow to run on port 5000
- ✅ Set up deployment configuration (autoscale)
- ✅ Application fully functional and tested

## Configuration
### Environment Variables Required:
- `SECRET_KEY`: JWT token secret (configured in workflow)
- `WHATSAPP_VERIFY_TOKEN`: WhatsApp webhook verification token
- `DATABASE_URL`: PostgreSQL connection (auto-configured by Replit)

### Default Admin User:
- **Email**: admin@leads.com  
- **Password**: admin123
- **⚠️ IMPORTANT**: Change password after first login

## File Structure
- `main.py`: FastAPI application entry point
- `database.py`: Database configuration and connection
- `models.py`: SQLAlchemy database models
- `auth.py`: Authentication and JWT handling
- `crud.py`: Database operations
- `schemas.py`: Pydantic models for API
- `templates/`: HTML templates (Jinja2)
- `static/`: CSS and JavaScript files
- `init_db.py`: Database initialization script

## Development
The application runs on port 5000 and is configured to accept all hosts for Replit's proxy system. The workflow automatically starts the server with proper environment variables.

## Deployment
Configured for autoscale deployment which automatically handles scaling based on traffic. The deployment uses the same command as development but in production environment.