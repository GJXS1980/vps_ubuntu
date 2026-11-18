import os
import socket
import ssl
import time
from urllib.parse import urlsplit

origin = urlsplit(os.environ["PORTAL_ORIGIN"])
ctx = ssl.create_default_context(cafile="/tls/tls.crt")
for attempt in range(20):
    try:
        with (
            socket.create_connection(("web", 443), 3) as plain,
            ctx.wrap_socket(plain, server_hostname=origin.hostname) as tls,
        ):
            tls.sendall(
                f"GET /api/health HTTP/1.1\r\nHost: {origin.netloc}\r\nConnection: close\r\n\r\n".encode()
            )
            if tls.makefile("rb").readline().split()[1] == b"200":
                print("HTTPS 与数据库健康检查通过", origin.geturl())
                break
    except OSError:
        pass
    time.sleep(1)
else:
    raise SystemExit("HTTPS 检查失败，请检查证书、入口和数据库迁移")
