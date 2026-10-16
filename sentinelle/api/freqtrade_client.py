"""Client minimal de l'API REST de Freqtrade (authentification HTTP Basic).

À VÉRIFIER dans la doc de la version déployée : chemins `/api/v1/...` et format des
réponses (`balance.total`, liste `status`). `stopentry` s'appelait `stopbuy` dans les
anciennes versions : on essaie les deux.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx


class FreqtradeError(RuntimeError):
    pass


class FreqtradeAPI(Protocol):
    def balance_usdt(self) -> float: ...
    def profit_total_usdt(self) -> float: ...
    def open_trades(self) -> list[dict[str, Any]]: ...
    def closed_trades(self, limit: int = 50) -> list[dict[str, Any]]: ...
    def stop_entries(self) -> None: ...
    def exit_all(self) -> None: ...


class FreqtradeClient:
    def __init__(self, base_url: str, username: str, password: str, timeout: float = 5.0):
        self.http = httpx.Client(base_url=base_url.rstrip("/") + "/api/v1", auth=(username, password), timeout=timeout)

    def _call(self, method: str, path: str, **kwargs) -> Any:
        try:
            resp = self.http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise FreqtradeError(f"Freqtrade injoignable : {exc}") from exc
        if resp.status_code >= 400:
            raise FreqtradeError(f"Freqtrade {path} → HTTP {resp.status_code}")
        return resp.json()

    def balance_usdt(self) -> float:
        return float(self._call("GET", "/balance")["total"])

    def profit_total_usdt(self) -> float:
        # Profit cumulé (positions fermées + ouvertes). À VÉRIFIER : champ `profit_all_coin`.
        return float(self._call("GET", "/profit")["profit_all_coin"])

    def open_trades(self) -> list[dict[str, Any]]:
        return list(self._call("GET", "/status"))

    def closed_trades(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(self._call("GET", "/trades", params={"limit": limit}).get("trades", []))

    def stop_entries(self) -> None:
        try:
            self._call("POST", "/stopentry")
        except FreqtradeError:
            self._call("POST", "/stopbuy")

    def exit_all(self) -> None:
        self._call("POST", "/forceexit", json={"tradeid": "all"})
