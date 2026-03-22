#!/usr/bin/env python3
"""
jenkins-ui.py — abre SSH tunnel e browser para o Jenkins UI

Uso:
  python3 jenkins-ui.py
  python3 jenkins-ui.py --ip 107.23.89.54
  python3 jenkins-ui.py --port 9090        # porta local alternativa
  python3 jenkins-ui.py --no-browser       # so o tunnel, sem abrir browser
"""

import subprocess
import sys
import os
import time
import argparse
import signal
import webbrowser

KEY_PATH   = os.path.expanduser("~/.ssh/hands-on-satubinha-key.pem")
DEFAULT_IP = "107.23.89.54"
LOCAL_PORT = 8080
REMOTE_PORT = 8080
SSH_USER   = "ubuntu"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Abre SSH tunnel e browser para o Jenkins UI"
    )
    parser.add_argument("--ip", default=DEFAULT_IP, help=f"IP da EC2 (default: {DEFAULT_IP})")
    parser.add_argument("--port", type=int, default=LOCAL_PORT, help=f"Porta local (default: {LOCAL_PORT})")
    parser.add_argument("--no-browser", action="store_true", help="Nao abre o browser automaticamente")
    parser.add_argument("--key", default=KEY_PATH, help=f"Caminho da chave SSH (default: {KEY_PATH})")
    return parser.parse_args()


def check_prerequisites(key_path):
    errors = []
    if not os.path.isfile(key_path):
        errors.append(f"  - Chave SSH nao encontrada: {key_path}")
        errors.append(f"    Passa o caminho correcto com --key <path>")
    result = subprocess.run(["which", "ssh"], capture_output=True)
    if result.returncode != 0:
        errors.append("  - 'ssh' nao encontrado no PATH")
    if errors:
        print("Pre-requisitos em falta:")
        for e in errors:
            print(e)
        sys.exit(1)


def is_port_in_use(port):
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0


def wait_for_tunnel(port, timeout=10):
    start = time.time()
    while time.time() - start < timeout:
        if is_port_in_use(port):
            return True
        time.sleep(0.5)
    return False


def main():
    args = parse_args()
    check_prerequisites(args.key)

    url = f"http://localhost:{args.port}"

    if is_port_in_use(args.port):
        print(f"Porta {args.port} ja esta em uso — tunnel ja activo ou outra aplicacao.")
        print(f"Jenkins UI: {url}")
        if not args.no_browser:
            webbrowser.open(url)
        sys.exit(0)

    print("=" * 60)
    print(f"  Jenkins UI")
    print(f"  EC2:        {args.ip}")
    print(f"  Tunnel:     localhost:{args.port} → {args.ip}:{REMOTE_PORT}")
    print(f"  URL:        {url}")
    print("=" * 60)
    print("A abrir tunnel SSH... (Ctrl+C para fechar)")

    cmd = [
        "ssh",
        "-L", f"{args.port}:localhost:{REMOTE_PORT}",
        "-i", args.key,
        f"{SSH_USER}@{args.ip}",
        "-N",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ExitOnForwardFailure=yes",
    ]

    try:
        tunnel = subprocess.Popen(cmd)

        if wait_for_tunnel(args.port):
            print(f"Tunnel activo — Jenkins UI disponivel em {url}")
            if not args.no_browser:
                time.sleep(0.5)
                webbrowser.open(url)
                print("Browser aberto.")
        else:
            print("Timeout a aguardar o tunnel. Verifica o IP e a chave SSH.")
            tunnel.terminate()
            sys.exit(1)

        # Manter o tunnel aberto
        def handle_sigint(sig, frame):
            print("\nA fechar tunnel SSH...")
            tunnel.terminate()
            sys.exit(0)

        signal.signal(signal.SIGINT, handle_sigint)
        tunnel.wait()

    except FileNotFoundError:
        print("Erro: 'ssh' nao encontrado.")
        sys.exit(1)


if __name__ == "__main__":
    main()
