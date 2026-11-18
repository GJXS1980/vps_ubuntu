"""Generate independent WireGuard and mTLS identities in a NEW private directory."""

import argparse
import base64
import datetime as dt
import ipaddress
import os
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, x25519
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def write(folder, name, value):
    with os.fdopen(
        os.open(folder / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb"
    ) as f:
        f.write(value.encode() if isinstance(value, str) else value)


def certs(root, server, address):
    ca = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    now = dt.datetime.now(dt.timezone.utc)
    name = x509.Name(
        [
            x509.NameAttribute(
                NameOID.COMMON_NAME, "WireGuard portal CA " + os.urandom(6).hex()
            )
        ]
    )

    def builder(subject, key, days):
        return (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5))
            .not_valid_after(now + dt.timedelta(days=days))
        )

    ca_cert = (
        builder(name, ca, 3650)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca.public_key()), False
        )
        .add_extension(
            x509.KeyUsage(False, False, False, False, False, True, True, False, False),
            True,
        )
        .sign(ca, hashes.SHA256())
    )
    for folder, role, usage in [
        (server, "server", ExtendedKeyUsageOID.SERVER_AUTH),
        (root, "client", ExtendedKeyUsageOID.CLIENT_AUTH),
    ]:
        key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        b = builder(
            x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, role)]), key, 365
        )
        b = (
            b.add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
            .add_extension(x509.ExtendedKeyUsage([usage]), False)
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(ca.public_key()),
                False,
            )
        )
        if role == "server":
            b = b.add_extension(
                x509.SubjectAlternativeName([x509.IPAddress(address)]), False
            )
        write(
            folder,
            role + ".crt",
            b.sign(ca, hashes.SHA256()).public_bytes(serialization.Encoding.PEM),
        )
        write(
            folder,
            role + ".key",
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
        )
        write(
            folder,
            "client-ca.crt" if role == "server" else "ca.crt",
            ca_cert.public_bytes(serialization.Encoding.PEM),
        )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("endpoint", type=ipaddress.IPv4Address)
    p.add_argument("folder", type=Path)
    p.add_argument("--network", default="10.203.91.0/30")
    p.add_argument("--port", type=int, default=51821)
    args = p.parse_args()
    net = ipaddress.IPv4Network(args.network)
    if (
        net.prefixlen != 30
        or not any(
            net.subnet_of(ipaddress.IPv4Network(parent))
            for parent in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
        )
        or net.overlaps(ipaddress.IPv4Network("10.66.77.0/24"))
        or not 1 <= args.port <= 65535
        or args.port == 51820
    ):
        p.error("需要独立私有 /30 网段及独立 UDP 端口")
    server_ip, client_ip = net.hosts()
    args.folder.mkdir(mode=0o700, parents=False)
    server = args.folder / "vps"
    server.mkdir(mode=0o700)
    certs(args.folder, server, server_ip)
    sk, ck = x25519.X25519PrivateKey.generate(), x25519.X25519PrivateKey.generate()

    def enc(b):
        return base64.b64encode(b).decode()

    for folder, address, peer, private, public, extra, peer_extra in [
        (server, server_ip, client_ip, sk, ck, f"ListenPort = {args.port}", ""),
        (
            args.folder,
            client_ip,
            server_ip,
            ck,
            sk,
            "",
            f"Endpoint = {args.endpoint}:{args.port}\nPersistentKeepalive = 25",
        ),
    ]:
        write(
            folder,
            "wgportal.conf",
            f"[Interface]\nAddress = {address}/30\nPrivateKey = {enc(private.private_bytes_raw())}\n{extra}\n\n[Peer]\nPublicKey = {enc(public.public_key().public_bytes_raw())}\nAllowedIPs = {peer}/32\n{peer_extra}\n",
        )
    write(
        server,
        "network",
        f"MANAGEMENT_SERVER={server_ip}\nMANAGEMENT_CLIENT={client_ip}\n",
    )
    print(f"管理服务 {server_ip}:9443，客户端 {client_ip}，密钥仅写入指定目录。")


if __name__ == "__main__":
    main()
