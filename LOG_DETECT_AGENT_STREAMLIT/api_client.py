"""Backend client for the Streamlit dashboard."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests


@dataclass(slots=True)
class BackendClient:
    """HTTP client that keeps backend integration identical to the Vue frontend."""

    base_url: str
    timeout: float = 30.0

    @classmethod
    def from_env(cls) -> "BackendClient":
        return cls(base_url=os.getenv("API_BASE_URL", "http://localhost:8000"))

    def _url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"

    def health(self) -> dict[str, Any]:
        response = requests.get(self._url("/health"), timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def services(self) -> list[str]:
        response = requests.get(self._url("/services"), timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        return payload.get("services", [])

    def analyze(self, service_name: str, save_to_chromadb: bool) -> dict[str, Any]:
        payload = {
            "service_name": service_name,
            "goal": f"{service_name} service log anomaly investigation",
            "save_to_chromadb": save_to_chromadb,
        }
        response = requests.post(self._url("/analyze"), json=payload, timeout=self.timeout)
        response.raise_for_status()
        return response.json()
