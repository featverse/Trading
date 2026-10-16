"""Journal d'expériences immuable (append-only, chaîné par hash).

Règles de gouvernance :
- chaque variante testée est enregistrée et compte comme un essai (N du Deflated Sharpe) ;
- les stratégies rejetées ne sont jamais supprimées ;
- toute altération du fichier est détectée par verify().
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GENESIS = "0" * 64


class LedgerTamperedError(RuntimeError):
    pass


class ExperimentLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def entries(self) -> list[dict[str, Any]]:
        with self.path.open(encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    @staticmethod
    def _hash(body: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def append(self, kind: str, payload: dict[str, Any], trials: int = 0) -> dict[str, Any]:
        if trials < 0:
            raise ValueError("trials >= 0")
        existing = self.entries()
        prev = existing[-1]["hash"] if existing else GENESIS
        body = {
            "seq": len(existing),
            "time": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "trials": trials,
            "payload": payload,
            "prev_hash": prev,
        }
        entry = {**body, "hash": self._hash(body)}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        return entry

    def verify(self) -> None:
        prev = GENESIS
        for i, entry in enumerate(self.entries()):
            body = {k: v for k, v in entry.items() if k != "hash"}
            if entry.get("seq") != i or entry.get("prev_hash") != prev or self._hash(body) != entry.get("hash"):
                raise LedgerTamperedError(f"Journal altéré à l'entrée {i}.")
            prev = entry["hash"]

    def total_trials(self) -> int:
        self.verify()
        return sum(e["trials"] for e in self.entries())

    def strategy_names(self) -> set[str]:
        return {e["payload"]["name"] for e in self.entries() if e["kind"] == "hypothesis"}
