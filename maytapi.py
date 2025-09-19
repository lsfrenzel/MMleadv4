"""
Integração com Maytapi WhatsApp Business API
"""
import os
import httpx
import asyncio
from typing import Dict, List, Optional, Any
from fastapi import HTTPException
import json

class MaytapiClient:
    def __init__(self):
        self.product_id = None
        self.token = None
        self.base_url = "https://api.maytapi.com/api"
        self.headers = None
        self._initialized = False
    
    def _ensure_initialized(self):
        """Inicializar cliente de forma lazy com verificação de credenciais"""
        if self._initialized:
            return True
            
        self.product_id = os.getenv("MAYTAPI_PRODUCT_ID")
        self.token = os.getenv("MAYTAPI_TOKEN")
        
        if not self.product_id or not self.token:
            return False
        
        self.headers = {
            "x-maytapi-key": self.token,
            "Content-Type": "application/json"
        }
        self._initialized = True
        return True
    
    async def get_phone_list(self) -> Dict:
        """Listar todos os telefones conectados"""
        if not self._ensure_initialized():
            return {"status": "error", "message": "Credenciais Maytapi não configuradas"}
            
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/{self.product_id}/listPhones",
                    headers=self.headers
                )
                response.raise_for_status()
                data = response.json()
                return {"status": "success", "data": data.get("data", [])}
        except Exception as e:
            print(f"Erro ao listar telefones: {e}")
            return {"status": "error", "message": str(e)}
    
    async def get_phone_status(self, phone_id: str) -> Dict:
        """Verificar status de um telefone específico"""
        if not self._ensure_initialized():
            return {"status": "error", "message": "Credenciais Maytapi não configuradas"}
            
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/{self.product_id}/{phone_id}/status",
                    headers=self.headers
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            print(f"Erro ao verificar status do telefone {phone_id}: {e}")
            return {"status": "error", "message": str(e)}
    
    async def get_qr_code(self, phone_id: str) -> Dict:
        """Obter QR Code para conectar WhatsApp"""
        if not self._ensure_initialized():
            return {"status": "error", "message": "Credenciais Maytapi não configuradas"}
            
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/{self.product_id}/{phone_id}/screen",
                    headers=self.headers
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            print(f"Erro ao obter QR Code para {phone_id}: {e}")
            return {"status": "error", "message": str(e)}
    
    async def send_message(self, phone_id: str, to_number: str, message: str) -> Dict:
        """Enviar mensagem via WhatsApp"""
        if not self._ensure_initialized():
            return {"status": "error", "message": "Credenciais Maytapi não configuradas"}
            
        try:
            payload = {
                "to_number": to_number,
                "message": message,
                "type": "text"
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/{self.product_id}/{phone_id}/sendMessage",
                    headers=self.headers,
                    json=payload
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            print(f"Erro ao enviar mensagem: {e}")
            return {"status": "error", "message": str(e)}
    
    async def create_phone_connection(self) -> Dict:
        """Criar nova conexão de telefone"""
        if not self._ensure_initialized():
            return {"status": "error", "message": "Credenciais Maytapi não configuradas"}
            
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/{self.product_id}/addPhone",
                    headers=self.headers
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            print(f"Erro ao criar conexão: {e}")
            return {"status": "error", "message": str(e)}
    
    async def delete_phone_connection(self, phone_id: str) -> Dict:
        """Remover conexão de telefone"""
        if not self._ensure_initialized():
            return {"status": "error", "message": "Credenciais Maytapi não configuradas"}
            
        try:
            async with httpx.AsyncClient() as client:
                response = await client.delete(
                    f"{self.base_url}/{self.product_id}/{phone_id}",
                    headers=self.headers
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            print(f"Erro ao remover conexão {phone_id}: {e}")
            return {"status": "error", "message": str(e)}
    
    async def set_webhook(self, phone_id: str, webhook_url: str) -> Dict:
        """Configurar webhook para receber mensagens"""
        if not self._ensure_initialized():
            return {"status": "error", "message": "Credenciais Maytapi não configuradas"}
            
        try:
            payload = {
                "webhook": webhook_url
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/{self.product_id}/{phone_id}/setWebhook",
                    headers=self.headers,
                    json=payload
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            print(f"Erro ao configurar webhook: {e}")
            return {"status": "error", "message": str(e)}

# Cliente global
maytapi_client = MaytapiClient()