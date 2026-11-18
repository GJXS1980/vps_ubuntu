import importlib.util
import ipaddress
import socket
import ssl
import threading
import time
import httpx
import pytest
import uvicorn
from conftest import ROOT


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tls_identity(tmp_path, monkeypatch):
    api = load("portal_agent", ROOT / "wireguard-portal/agent/api.py")
    generator = load("generator", ROOT / "wireguard-portal/scripts/management-link.py")
    server = tmp_path / "server"
    server.mkdir()
    generator.certs(tmp_path, server, ipaddress.IPv4Address("127.0.0.1"))
    import datetime as dt
    from types import SimpleNamespace

    class Past(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return super().now(tz) - dt.timedelta(days=400)

    expired = tmp_path / "expired"
    (expired / "server").mkdir(parents=True)
    monkeypatch.setattr(
        generator,
        "dt",
        SimpleNamespace(datetime=Past, timedelta=dt.timedelta, timezone=dt.timezone),
    )
    generator.certs(expired, expired / "server", ipaddress.IPv4Address("127.0.0.1"))
    trust = server / "trust.crt"
    trust.write_bytes(
        (server / "client-ca.crt").read_bytes() + (expired / "ca.crt").read_bytes()
    )
    monkeypatch.setenv("MANAGEMENT_CLIENT", "127.0.0.1")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    cfg = uvicorn.Config(
        api.app,
        ssl_certfile=str(server / "server.crt"),
        ssl_keyfile=str(server / "server.key"),
        ssl_ca_certs=str(trust),
        ssl_cert_reqs=ssl.CERT_REQUIRED,
        log_level="critical",
        proxy_headers=False,
    )
    service = uvicorn.Server(cfg)
    thread = threading.Thread(
        target=service.run, kwargs={"sockets": [sock]}, daemon=True
    )
    thread.start()
    try:
        for _ in range(100):
            if service.started:
                break
            time.sleep(0.05)
        assert service.started
        base = f"https://127.0.0.1:{port}"
        ca = ssl.create_default_context(cafile=str(tmp_path / "ca.crt"))
        with httpx.Client(verify=ca, trust_env=False, base_url=base) as client:
            with pytest.raises(httpx.TransportError):
                client.get("/v1/health")
        bad = ssl.create_default_context(cafile=str(tmp_path / "ca.crt"))
        bad.load_cert_chain(expired / "client.crt", expired / "client.key")
        with httpx.Client(verify=bad, trust_env=False, base_url=base) as invalid:
            with pytest.raises(httpx.TransportError):
                invalid.get("/v1/health")
        ca.load_cert_chain(tmp_path / "client.crt", tmp_path / "client.key")
        with httpx.Client(verify=ca, trust_env=False, base_url=base) as client:
            assert client.get("/v1/health").json() == {"version": 1}
            assert client.get("/v2/health").status_code == 409
            assert (
                client.post(
                    "/v1/operations", json={"action": "export", "device": "invalid;id"}
                ).status_code
                == 422
            )
            monkeypatch.setenv("MANAGEMENT_CLIENT", "10.0.0.2")
            assert client.get("/v1/health").status_code == 403
        with httpx.Client(trust_env=False, base_url=base) as client:
            with pytest.raises(httpx.TransportError):
                client.get("/v1/health")
    finally:
        service.should_exit = True
        thread.join(5)
        sock.close()
