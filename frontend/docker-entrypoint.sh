#!/bin/sh

CERT_DIR=/etc/nginx/certs
CERT_FILE="$CERT_DIR/server.crt"
KEY_FILE="$CERT_DIR/server.key"

if [ ! -f "$CERT_FILE" ] || [ ! -f "$KEY_FILE" ]; then
    echo "Generating self-signed SSL certificate..."
    mkdir -p "$CERT_DIR"
    openssl req -x509 -nodes -newkey rsa:2048 -days 3650 \
        -keyout "$KEY_FILE" \
        -out "$CERT_FILE" \
        -subj "/CN=localhost" \
        -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
    echo "Self-signed SSL certificate generated."
else
    echo "SSL certificate already exists, skipping generation."
fi

exec nginx -g "daemon off;"
