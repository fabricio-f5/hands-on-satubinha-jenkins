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


def trigger(job, action):
    check_prerequisites()

    user, password = get_jenkins_credentials()

    print("=" * 60)
    print(f"  Job:    {job}")
    print(f"  Action: {action} — {ACTION_DESCRIPTIONS[action]}")
    print(f"  URL:    {JENKINS_URL}")
    print("=" * 60)

    cmd = [
        "java", "-jar", CLI_JAR,
        "-s", JENKINS_URL,
        "-auth", f"{user}:{password}",
        "build", job,
        "-p", f"ACTION={action}",
        "-s", "-v"
    ]

    try:
        result = subprocess.run(cmd)
        print()
        if result.returncode == 0:
            print(f"✅ {job} ({action}) concluido com sucesso")
        else:
            print(f"❌ {job} ({action}) falhou (exit code {result.returncode})")
        sys.exit(result.returncode)

    except KeyboardInterrupt:
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
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.list:
        list_options()
        sys.exit(0)

    if not args.job or not args.action:
        print("Uso: python3 jenkins-trigger.py <job> <action>")
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

    trigger(args.job, args.action)
