import ipaddress
import json
import os
import subprocess
from typing import Literal
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

app = FastAPI(docs_url=None, redoc_url=None)


class Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal[
        "create", "adopt", "enable", "disable", "rotate", "delete", "export"
    ]
    device: str = Field(pattern=r"^[0-9a-f]{32}$")
    key: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    peer: str | None = Field(default=None, pattern=r"^user[0-9]{2,16}$")
    fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    mode: Literal["global", "proxy"] | None = None
    label: str | None = Field(default=None, min_length=1, max_length=40)


@app.middleware("http")
async def network(request: Request, call_next):
    from fastapi.responses import JSONResponse

    if request.client.host != os.environ["MANAGEMENT_CLIENT"]:
        return JSONResponse({"detail": "管理地址无权访问"}, status_code=403)
    if not request.url.path.startswith("/v1/"):
        return JSONResponse({"detail": "Agent 仅支持 API v1"}, status_code=409)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


def invoke(q):
    try:
        result = subprocess.run(
            ["/usr/bin/sudo", "-n", "/usr/local/sbin/wg-portal-bridge"],
            input=json.dumps(q),
            text=True,
            capture_output=True,
            timeout=25,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise HTTPException(503, "管理器不可用")
    if result.returncode == 3:
        raise HTTPException(409, json.loads(result.stdout)["error"])
    if result.returncode:
        raise HTTPException(503, "管理器未确认结果")
    return json.loads(result.stdout)


@app.get("/v1/health")
def health():
    return {"version": 1}


@app.get("/v1/peers")
def inventory():
    return invoke({"action": "inventory"})


@app.get("/v1/audit")
def audit():
    return invoke({"action": "audit"})


@app.get("/v1/results/{key}")
def result(key: str):
    return invoke({"action": "result", "key": key})


@app.post("/v1/operations")
def operation(op: Operation):
    return invoke(op.model_dump(exclude_none=True))


@app.get("/v1/capacity")
def capacity():
    snap = inventory()
    return {key: snap[key] for key in ("version", "live", "capacity", "free")}


@app.get("/v1/peers/{peer}")
def peer_status(peer: str):
    import re

    if not re.fullmatch(r"user[0-9]{2,16}", peer):
        raise HTTPException(422, "Peer ID 无效")
    for row in inventory()["rows"]:
        if row["name"] == peer:
            return row
    raise HTTPException(404, "Peer 不存在")


if __name__ == "__main__":
    import ssl
    import uvicorn

    address = ipaddress.IPv4Address(os.environ["MANAGEMENT_SERVER"])
    if not any(
        address in ipaddress.IPv4Network(net)
        for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    ):
        raise SystemExit("管理地址无效")
    uvicorn.run(
        app,
        host=str(address),
        port=9443,
        proxy_headers=False,
        access_log=False,
        ssl_certfile="/etc/wg-portal/server.crt",
        ssl_keyfile="/etc/wg-portal/server.key",
        ssl_ca_certs="/etc/wg-portal/client-ca.crt",
        ssl_cert_reqs=ssl.CERT_REQUIRED,
    )
