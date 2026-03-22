#!/usr/bin/env python3
"""
jenkins-trigger.py — dispara pipelines Jenkins via CLI
Uso: python3 jenkins-trigger.py <job> <action>
Exemplo: python3 jenkins-trigger.py satubinha-foundation plan
"""

import subprocess
import sys
import os

JOBS = ["satubinha-foundation", "satubinha-ec2"]
ACTIONS = ["plan", "apply", "plan-destroy", "destroy"]
JENKINS_URL = "http://localhost:8080"
CLI_JAR = os.path.expanduser("~/jenkins-cli.jar")


def get_jenkins_password():
    result = subprocess.run(
        ["docker", "exec", "jenkins", "env"],
        capture_output=True, text=True
    )
    for line in result.stdout.splitlines():
        if line.startswith("JENKINS_ADMIN_PASSWORD="):
            return line.split("=", 1)[1]
    print("Erro: JENKINS_ADMIN_PASSWORD nao encontrado no container Jenkins")
    sys.exit(1)


def get_jenkins_user():
    result = subprocess.run(
        ["docker", "exec", "jenkins", "env"],
        capture_output=True, text=True
    )
    for line in result.stdout.splitlines():
        if line.startswith("JENKINS_ADMIN_USER="):
            return line.split("=", 1)[1]
    return "admin"


def trigger(job, action):
    user = get_jenkins_user()
    password = get_jenkins_password()

    cmd = [
        "java", "-jar", CLI_JAR,
        "-s", JENKINS_URL,
        "-auth", f"{user}:{password}",
        "build", job,
        "-p", f"ACTION={action}",
        "-s", "-v"
    ]

    print(f"==> Disparando {job} com ACTION={action}")
    print(f"==> URL: {JENKINS_URL}")
    print("-" * 60)

    result = subprocess.run(cmd)
    sys.exit(result.returncode)


def usage():
    print(f"Uso: python3 {sys.argv[0]} <job> <action>")
    print(f"  Jobs:    {', '.join(JOBS)}")
    print(f"  Actions: {', '.join(ACTIONS)}")
    print()
    print("Exemplos:")
    print(f"  python3 {sys.argv[0]} satubinha-foundation plan")
    print(f"  python3 {sys.argv[0]} satubinha-ec2 apply")
    sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        usage()

    job = sys.argv[1]
    action = sys.argv[2]

    if job not in JOBS:
        print(f"Erro: job '{job}' invalido. Opcoes: {', '.join(JOBS)}")
        usage()

    if action not in ACTIONS:
        print(f"Erro: action '{action}' invalida. Opcoes: {', '.join(ACTIONS)}")
        usage()

    trigger(job, action)
