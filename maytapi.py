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
        self.product_id = os.getenv("MAYTAPI_PRODUCT_ID")
        self.token = os.getenv("MAYTAPI_TOKEN")
        self.base_url = "https://api.maytapi.com/api"
        self.headers = None
        self._initialized = False
        
        # Inicializar imediatamente se as credenciais estiverem disponíveis
        if self.product_id and self.token:
            self.headers = {
                "x-maytapi-key": self.token,
                "Content-Type": "application/json"
            }
            self._initialized = True
    
    def _ensure_initialized(self):
        """Verificar se o cliente está inicializado com credenciais válidas"""
        if self._initialized:
            return True
            
        # Tentar carregar credenciais novamente
        self.product_id = os.getenv("MAYTAPI_PRODUCT_ID")
        self.token = os.getenv("MAYTAPI_TOKEN")
        
        if not self.product_id or not self.token:
            print(f"Credenciais Maytapi: Product ID={self.product_id}, Token={'presente' if self.token else 'ausente'}")
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
                
                # A API listPhones retorna diretamente um array
                if isinstance(data, list):
                    return {"status": "success", "data": data}
                elif data.get("success"):
                    return {"status": "success", "data": data.get("data", [])}
                else:
                    return {"status": "error", "message": data.get("message", "Erro ao listar telefones")}
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
                
                # Verificar o tipo de conteúdo da resposta
                content_type = response.headers.get("content-type", "")
                
                if "image" in content_type:
                    # Resposta é uma imagem binária - converter para base64
                    import base64
                    image_data = response.content
                    base64_image = base64.b64encode(image_data).decode('utf-8')
                    data_uri = f"data:{content_type};base64,{base64_image}"
                    
                    return {
                        "status": "success",
                        "screen": data_uri,
                        "message": "QR Code obtido com sucesso"
                    }
                else:
                    # Resposta é JSON
                    try:
                        data = response.json()
                        if data.get("success"):
                            return {
                                "status": "success",
                                "screen": data.get("data", {}).get("screen"),
                                "message": "QR Code obtido com sucesso"
                            }
                        else:
                            return {
                                "status": "error",
                                "message": data.get("message", "Erro ao obter QR Code")
                            }
                    except:
                        # Se não conseguir fazer JSON, tentar como texto
                        return {
                            "status": "error",
                            "message": f"Resposta inesperada da API: {response.text[:100]}"
                        }
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
        """Criar nova conexão de telefone ou usar telefone existente"""
        if not self._ensure_initialized():
            return {"status": "error", "message": "Credenciais Maytapi não configuradas"}
            
        try:
            # Primeiro, verificar se já existe um telefone disponível
            phone_list = await self.get_phone_list()
            if phone_list.get("status") == "success" and phone_list.get("data"):
                # Usar o primeiro telefone disponível
                existing_phone = phone_list["data"][0]
                phone_id = str(existing_phone.get("id"))
                
                return {
                    "status": "success",
                    "phone_id": phone_id,
                    "message": f"Usando telefone existente: {phone_id}",
                    "existing": True
                }
            
            # Se não há telefones, tentar criar um novo
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/{self.product_id}/addPhone",
                    headers=self.headers
                )
                response.raise_for_status()
                data = response.json()
                
                # Converter formato da resposta Maytapi para formato padrão
                if data.get("success"):
                    return {
                        "status": "success",
                        "phone_id": str(data.get("data", {}).get("id")),
                        "message": "Conexão criada com sucesso"
                    }
                else:
                    return {
                        "status": "error", 
                        "message": data.get("message", "Erro desconhecido")
                    }
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