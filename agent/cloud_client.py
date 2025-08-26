# FILE: agent/cloud_client.py

import os
import json
import asyncio
from typing import Dict, Any, Optional, List
import httpx
from pathlib import Path

# Custom Exceptions for clarity
class AuthError(Exception): pass
class APIError(Exception): pass

class _AsyncCloudClient:
    """
    The internal, asynchronous client that handles the actual HTTP requests.
    This class is not meant to be used directly by the rest of the application.
    """
    def __init__(self, base_url: str, token: Optional[str]):
        self.base_url = base_url
        self.token = token

    def _get_auth_headers(self) -> Dict[str, str]:
        if not self.token:
            raise AuthError("You are not logged in. Please run `/cloud login` first.")
        return {"Authorization": f"Bearer {self.token}"}

    async def login(self, username: str, password: str) -> str:
        async with httpx.AsyncClient() as client:
            data = {"username": username, "password": password}
            response = await client.post(
                f"{self.base_url}/api/v1/auth/token",
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            if response.status_code == 400:
                raise AuthError("Incorrect username or password.")
            response.raise_for_status()
            return response.json()["access_token"]

    async def list_environments(self) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/api/v1/environments/",
                headers=self._get_auth_headers()
            )
            response.raise_for_status()
            return response.json()

    async def create_environment(self, spec_cpu: float, spec_memory: float, lifetime_hours: int) -> Dict[str, Any]:
        payload = {"spec_cpu": spec_cpu, "spec_memory": spec_memory, "lifetime_hours": lifetime_hours}
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/environments/", json=payload, headers=self._get_auth_headers()
            )
            if response.status_code >= 400:
                try:
                    detail = response.json().get("detail", "Unknown error")
                    raise APIError(f"Failed to create environment: {detail}")
                except json.JSONDecodeError:
                    raise APIError(f"Failed to create environment: {response.text}")
            return response.json()

    async def get_environment_status(self, env_id: str) -> Dict[str, Any]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/api/v1/environments/{env_id}", headers=self._get_auth_headers()
            )
            response.raise_for_status()
            return response.json()


class CloudClient:
    """
    The public, SYNCHRONOUS client for the cloud.dolphindb service.
    This is the class the rest of the application should use.
    It wraps the _AsyncCloudClient using asyncio.run().
    """
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.config_path = Path.home() / ".ddb_agent" / "auth.json"
        self.config_path.parent.mkdir(exist_ok=True)
        self.token = self._load_token()

    @property
    def is_logged_in(self) -> bool:
        """
        Checks if the client has an authentication token.
        This is the primary method to check login status.
        """
        return self.token is not None

    def _load_token(self) -> Optional[str]:
        if not self.config_path.exists(): return None
        try:
            with open(self.config_path, 'r') as f: return json.load(f).get("access_token")
        except (json.JSONDecodeError, IOError): return None

    def _save_token(self, token: str):
        with open(self.config_path, 'w') as f: json.dump({"access_token": token}, f)

    def login(self, username: str, password: str) -> None:
        async_client = _AsyncCloudClient(self.base_url, self.token)
        self.token = asyncio.run(async_client.login(username, password))
        self._save_token(self.token)

    def logout(self):
        if self.config_path.exists(): os.remove(self.config_path)
        self.token = None

    def list_environments(self) -> List[Dict[str, Any]]:
        if not self.is_logged_in:
            raise AuthError("You are not logged in. Please run `/cloud login` first.")
        async_client = _AsyncCloudClient(self.base_url, self.token)
        return asyncio.run(async_client.list_environments())

    def create_environment(self, spec_cpu: float, spec_memory: float, lifetime_hours: int) -> Dict[str, Any]:
        if not self.is_logged_in:
            raise AuthError("You are not logged in. Please run `/cloud login` first.")
        async_client = _AsyncCloudClient(self.base_url, self.token)
        return asyncio.run(async_client.create_environment(spec_cpu, spec_memory, lifetime_hours))

    def get_environment_status(self, env_id: str) -> Dict[str, Any]:
        if not self.is_logged_in:
            raise AuthError("You are not logged in. Please run `/cloud login` first.")
        async_client = _AsyncCloudClient(self.base_url, self.token)
        return asyncio.run(async_client.get_environment_status(env_id))