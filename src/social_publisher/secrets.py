from __future__ import annotations

from typing import Protocol

import keyring


class SecretStore(Protocol):
    def get(self, reference: str) -> str: ...

    def set(self, reference: str, value: str) -> None: ...

    def exists(self, reference: str) -> bool: ...


class KeyringSecretStore:
    def __init__(self, service_name: str = "local-social-publisher") -> None:
        self.service_name = service_name

    def get(self, reference: str) -> str:
        value = keyring.get_password(self.service_name, reference)
        if value is None:
            raise KeyError(f"secret is not configured: {reference}")
        return value

    def set(self, reference: str, value: str) -> None:
        if not value:
            raise ValueError("secret value cannot be empty")
        keyring.set_password(self.service_name, reference, value)

    def exists(self, reference: str) -> bool:
        return keyring.get_password(self.service_name, reference) is not None


class MemorySecretStore:
    """Test-only secret store with the same contract as the OS keyring."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, reference: str) -> str:
        try:
            return self.values[reference]
        except KeyError as error:
            raise KeyError(f"secret is not configured: {reference}") from error

    def set(self, reference: str, value: str) -> None:
        if not value:
            raise ValueError("secret value cannot be empty")
        self.values[reference] = value

    def exists(self, reference: str) -> bool:
        return reference in self.values
