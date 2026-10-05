"""Verification-only process guard: permit loopback, audit outbound attempts."""
import ipaddress
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def install(log_path):
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def audit(event, args):
        if event not in ("socket.connect", "socket.getaddrinfo"):
            return
        address = args[1] if event == "socket.connect" else (args[0], args[1])
        host = address[0] if isinstance(address, tuple) else str(address)
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host in ("localhost", None)
        row = {"at": datetime.now(timezone.utc).isoformat(), "pid": os.getpid(),
               "event": event, "address": address, "loopback": loopback}
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        if not loopback:
            raise PermissionError("External networking forbidden during PHASE 1C verification")

    sys.addaudithook(audit)
