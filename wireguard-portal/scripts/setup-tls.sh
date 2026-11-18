#!/bin/sh
set -eu
umask 077
cd /tls
if [ -s tls.key ] && [ -s tls.crt ]; then exit 0; fi
test ! -e tls.key && test ! -e tls.crt || exit 1
openssl req -x509 -newkey rsa:3072 -nodes -days 365 -subj /CN=localhost -addext 'subjectAltName=DNS:localhost,IP:127.0.0.1' -keyout tls.key -out tls.crt
