#!/usr/bin/env python3
"""
jenkins-trigger.py — dispara pipelines Jenkins via CLI
Corre na EC2 ou localmente via SSH tunnel (porta 8080)

Uso:
  python3 jenkins-trigger.py <job> <action>
  python3 jenkins-trigger.py --list

Exemplos:
  python3 jenkins-trigger.py satubinha-foundation plan
  python3 jenkins-trigger.py satubinha-ec2 apply
  python3 jenkins-trigger.py satubinha-foundation plan-destroy
  python3 jenkins-trigger.py satubinha-ec2 destroy
"""

import subprocess
import sys
import os
import argparse
import threading
import time

JOBS = ["satubinha-foundation", "satubinha-ec2"]
ACTIONS = ["plan", "apply", "plan-destroy", "destroy"]
JENKINS_URL = "http://localhost:8080"
CLI_JAR = os.path.expanduser("~/jenkins-cli.jar")

ACTION_DESCRIPTIONS = {
    "plan":         "mostra o que vai ser criado/alterado (sem aplicar)",
    "apply":        "plan + apply (requer confirmacao manual no Jenkins)",
    "plan-destroy": "mostra o que vai ser destruido (sem aplicar)",
    "destroy":      "plan destroy + destroy (requer confirmacao manual no Jenkins)",
}


def check_prerequisites():
    errors = []

    result = subprocess.run(["which", "java"], capture_output=True)
    if result.returncode != 0:
        errors.append("  - 'java' nao encontrado. Instalar com: sudo apt install openjdk-21-jre-headless")

    if not os.path.isfile(CLI_JAR):
        errors.append(f"  - jenkins-cli.jar nao encontrado em {CLI_JAR}")
        errors.append(f"    Fazer download com: wget -q {JENKINS_URL}/jnlpJars/jenkins-cli.jar")

    if errors:
        print("Pre-requisitos em falta:")
        for e in errors:
            print(e)
        sys.exit(1)


def get_jenkins_credentials():
    result = subprocess.run(
        ["docker", "exec", "jenkins", "env"],
        capture_output=True, text=True
    )

    user = "admin"
    password = None

    for line in result.stdout.splitlines():
        if line.startswith("JENKINS_ADMIN_USER="):
            user = line.split("=", 1)[1].strip()
        elif line.startswith("JENKINS_ADMIN_PASSWORD="):
            password = line.split("=", 1)[1].strip()

    if not password:
        print("Erro: nao foi possivel obter JENKINS_ADMIN_PASSWORD do container Jenkins")
        print("Verifica se o container esta a correr: docker ps | grep jenkins")
        sys.exit(1)

    return user, password


def get_pending_input_id(job, build_number, user, password):
    """Obtém o ID do input pendente num build."""
    cmd = [
        "java", "-jar", CLI_JAR,
        "-s", JENKINS_URL,
        "-auth", f"{user}:{password}",
        "console", job, str(build_number)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    # O input ID é gerado pelo Jenkins — usa o default que é o primeiro disponível
    return "_"


def confirm_input(job, build_number, user, password, input_id="_"):
    """Confirma um input pendente via REST API."""
    import urllib.request
    import urllib.parse

    url = f"{JENKINS_URL}/job/{job}/{build_number}/input/{input_id}/proceedEmpty"
    auth = f"{user}:{password}"
    import base64
    token = base64.b64encode(auth.encode()).decode()

    req = urllib.request.Request(url, method="POST")
    req.add_header("Authorization", f"Basic {token}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        urllib.request.urlopen(req, data=b"")
        return True
    except Exception:
        return False


def auto_confirm_worker(job, user, password, stop_event, delay=5):
    """Thread que monitoriza e confirma inputs pendentes automaticamente."""
    import urllib.request
    import urllib.error
    import base64
    import json

    auth = base64.b64encode(f"{user}:{password}".encode()).decode()

    # Aguarda o build arrancar
    time.sleep(delay)

    while not stop_event.is_set():
        try:
            # Obter o último build number
            url = f"{JENKINS_URL}/job/{job}/lastBuild/api/json"
            req = urllib.request.Request(url)
            req.add_header("Authorization", f"Basic {auth}")
            response = urllib.request.urlopen(req, timeout=5)
            build_data = json.loads(response.read())
            build_number = build_data.get("number")

            # Verificar se há inputs pendentes
            url = f"{JENKINS_URL}/job/{job}/{build_number}/wfapi/pendingInputActions"
            req = urllib.request.Request(url)
            req.add_header("Authorization", f"Basic {auth}")
            response = urllib.request.urlopen(req, timeout=5)
            inputs = json.loads(response.read())

            if inputs:
                for inp in inputs:
                    input_id = inp.get("id", "_")
                    proceed_url = f"{JENKINS_URL}/job/{job}/{build_number}/input/{input_id}/proceedEmpty"
                    req = urllib.request.Request(proceed_url, method="POST")
                    req.add_header("Authorization", f"Basic {auth}")
                    req.add_header("Content-Type", "application/x-www-form-urlencoded")
                    try:
                        urllib.request.urlopen(req, data=b"", timeout=5)
                        print(f"\n  [AUTO-CONFIRM] Input '{inp.get('message', '')}' confirmado automaticamente")
                    except Exception:
                        pass

        except Exception:
            pass

        time.sleep(3)


def trigger(job, action, auto_confirm=False):
    check_prerequisites()

    user, password = get_jenkins_credentials()

    print("=" * 60)
    print(f"  Job:    {job}")
    print(f"  Action: {action} — {ACTION_DESCRIPTIONS[action]}")
    print(f"  URL:    {JENKINS_URL}")
    if auto_confirm:
        print(f"  Modo:   auto-confirm ACTIVO")
    print("=" * 60)

    base_cmd = [
        "java", "-jar", CLI_JAR,
        "-s", JENKINS_URL,
        "-auth", f"{user}:{password}",
        "build", job,
        "-s", "-v"
    ]
    cmd_with_param = base_cmd + ["-p", f"ACTION={action}"]

    try:
        # Verificar se job esta parametrizado antes de disparar
        check_cmd = [
            "java", "-jar", CLI_JAR,
            "-s", JENKINS_URL,
            "-auth", f"{user}:{password}",
            "get-job", job
        ]
        check = subprocess.run(check_cmd, capture_output=True, text=True)
        is_parameterized = "<parameterDefinitions>" in check.stdout

        if not is_parameterized:
            print("  [INFO] Primeiro build — inicializando parametros do job...")
            init_result = subprocess.run(base_cmd)
            if init_result.returncode != 0:
                print(f"\n❌ Inicializacao do job falhou (exit code {init_result.returncode})")
                sys.exit(init_result.returncode)
            print("\n  [INFO] Job inicializado — a disparar com ACTION...")

        # Arrancar thread de auto-confirm se solicitado
        stop_event = threading.Event()
        if auto_confirm:
            confirm_thread = threading.Thread(
                target=auto_confirm_worker,
                args=(job, user, password, stop_event),
                daemon=True
            )
            confirm_thread.start()

        # Disparar com parametro — output em tempo real
        result = subprocess.run(cmd_with_param)

        # Parar thread de auto-confirm
        stop_event.set()

        print()
        if result.returncode == 0:
            print(f"✅ {job} ({action}) concluido com sucesso")
        else:
            print(f"❌ {job} ({action}) falhou (exit code {result.returncode})")
        sys.exit(result.returncode)

    except KeyboardInterrupt:
        stop_event.set()
        print("\nInterrompido pelo utilizador")
        sys.exit(1)


def list_options():
    print("Jobs disponíveis:")
    for job in JOBS:
        print(f"  {job}")
    print()
    print("Actions disponíveis:")
    for action, desc in ACTION_DESCRIPTIONS.items():
        print(f"  {action:<15} {desc}")
    print()
    print("Exemplos:")
    print("  python3 jenkins-trigger.py satubinha-foundation plan")
    print("  python3 jenkins-trigger.py satubinha-ec2 apply")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Dispara pipelines Jenkins via CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("job", nargs="?", help="Job a disparar")
    parser.add_argument("action", nargs="?", help="Action a executar")
    parser.add_argument("--list", action="store_true", help="Lista jobs e actions disponíveis")
    parser.add_argument(
        "--auto-confirm",
        action="store_true",
        help="Confirma automaticamente o stage de confirmacao (apply/destroy)"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.list:
        list_options()
        sys.exit(0)

    if not args.job or not args.action:
        print("Uso: python3 jenkins-trigger.py <job> <action> [--auto-confirm]")
        print("     python3 jenkins-trigger.py --list")
        sys.exit(1)

    if args.job not in JOBS:
        print(f"Erro: job '{args.job}' invalido.")
        print(f"Jobs validos: {', '.join(JOBS)}")
        sys.exit(1)

    if args.action not in ACTIONS:
        print(f"Erro: action '{args.action}' invalida.")
        print(f"Actions validas: {', '.join(ACTIONS)}")
        sys.exit(1)

    trigger(args.job, args.action, auto_confirm=args.auto_confirm)
