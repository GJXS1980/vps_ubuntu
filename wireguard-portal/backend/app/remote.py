import ipaddress
import os
import ssl
from pathlib import Path
import httpx


def remote(server, path, payload=None):
    addr = ipaddress.IPv4Address(server["address"])
    folder = Path(os.environ.get("AGENT_CERTS", "./certs")) / str(addr)
    context = ssl.create_default_context(cafile=str(folder / "ca.crt"))
    context.load_cert_chain(folder / "client.crt", folder / "client.key")
    with httpx.Client(
        base_url=f"https://{addr}:9443/v1/", verify=context, timeout=12, trust_env=False
    ) as client:
        response = (
            client.get(path) if payload is None else client.post(path, json=payload)
        )
        response.raise_for_status()
        return response.json()
