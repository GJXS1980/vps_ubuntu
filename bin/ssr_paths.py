"""Select a complete known installation without creating a second config."""
from pathlib import Path

LAYOUTS = (
    (Path('/etc/ssr/config.json'), Path('/opt/ssr/shadowsocks/server.py')),
    (Path('/etc/shadowsocksr/config.json'), Path('/opt/shadowsocksr/shadowsocks/server.py')),
)


def installation():
    found = [(config, server) for config, server in LAYOUTS
             if config.is_file() and server.is_file()]
    if len(found) > 1:
        raise ValueError('检测到两套 SSR 安装，请先核对 ssr.service 的实际配置来源；拒绝自动选择')
    if found:
        return found[0]
    raise ValueError('未找到完整 SSR 安装：请检查 /etc/ssr 或 /etc/shadowsocksr 的配置及对应 /opt 源码；不要创建空配置')


def server_for(config):
    for candidate, server in LAYOUTS:
        if Path(config) == candidate:
            return server
    raise ValueError('自定义配置路径无法确定服务端源码，拒绝修改限速或设备限制')
