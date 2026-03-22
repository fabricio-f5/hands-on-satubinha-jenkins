#!/usr/bin/env python3
"""
deploy.py — deploy do Jenkins EC2 via Ansible
Uso: python3 deploy.py [--tags TAGS] [--vault-pass PASS] [--check]

Exemplos:
  python3 deploy.py                          # deploy completo
  python3 deploy.py --tags docker            # so instalar docker
  python3 deploy.py --tags ecr,jenkins       # rebuild imagem + restart jenkins
  python3 deploy.py --vault-pass minhapass   # sem prompt de vault
  python3 deploy.py --check                  # dry-run
"""

import argparse
import subprocess
import sys
import os
import getpass

ANSIBLE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ansible")
PLAYBOOK    = os.path.join(ANSIBLE_DIR, "playbook.yml")
INVENTORY   = os.path.join(ANSIBLE_DIR, "inventory.ini")

VALID_TAGS = ["docker", "ecr", "build", "push", "jenkins"]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Deploy Jenkins EC2 via Ansible",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Tags disponíveis:
  docker   — instala Docker, AWS CLI, Cosign
  ecr      — build da imagem, Trivy scan, CST, push para ECR, cosign sign
  jenkins  — 4 security checks, pull, arranque do container, healthcheck,
             promoção da tag stable

Exemplos:
  python3 deploy.py
  python3 deploy.py --tags docker
  python3 deploy.py --tags ecr,jenkins
  python3 deploy.py --vault-pass minhapass
        """
    )
    parser.add_argument(
        "--tags",
        help="Tags Ansible a executar (ex: docker,ecr,jenkins)",
        default=None
    )
    parser.add_argument(
        "--vault-pass",
        help="Password do Ansible Vault (evita o prompt interactivo)",
        default=None
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Dry-run — mostra o que seria executado sem aplicar alteracoes"
    )
    return parser.parse_args()


def validate_tags(tags_str):
    tags = [t.strip() for t in tags_str.split(",")]
    invalid = [t for t in tags if t not in VALID_TAGS]
    if invalid:
        print(f"Erro: tags invalidas: {', '.join(invalid)}")
        print(f"Tags validas: {', '.join(VALID_TAGS)}")
        sys.exit(1)
    return tags


def check_prerequisites():
    errors = []
    for binary in ["ansible-playbook"]:
        result = subprocess.run(["which", binary], capture_output=True)
        if result.returncode != 0:
            errors.append(f"  - '{binary}' nao encontrado no PATH")

    if not os.path.isfile(PLAYBOOK):
        errors.append(f"  - playbook nao encontrado: {PLAYBOOK}")

    if not os.path.isfile(INVENTORY):
        errors.append(f"  - inventory nao encontrado: {INVENTORY}")

    if errors:
        print("Pre-requisitos em falta:")
        for e in errors:
            print(e)
        sys.exit(1)


def build_command(args, vault_pass):
    cmd = [
        "ansible-playbook",
        "-i", INVENTORY,
        PLAYBOOK,
    ]

    if args.tags:
        cmd += ["--tags", args.tags]

    if args.check:
        cmd += ["--check"]

    if vault_pass:
        cmd += ["--vault-password-file", "/dev/stdin"]

    return cmd


def run(args):
    check_prerequisites()

    vault_pass = args.vault_pass
    if not vault_pass:
        vault_pass = getpass.getpass("Vault password: ")

    tags_label = args.tags if args.tags else "all"
    mode_label = " [DRY-RUN]" if args.check else ""

    if args.tags:
        validate_tags(args.tags)

    print("=" * 60)
    print(f"  Deploy Jenkins EC2{mode_label}")
    print(f"  Tags:      {tags_label}")
    print(f"  Inventory: {INVENTORY}")
    print(f"  Playbook:  {PLAYBOOK}")
    print("=" * 60)

    cmd = build_command(args, vault_pass)

    try:
        result = subprocess.run(
            cmd,
            input=vault_pass if vault_pass else None,
            text=True,
            cwd=ANSIBLE_DIR
        )
        print()
        if result.returncode == 0:
            print("✅ Deploy concluido com sucesso")
        else:
            print(f"❌ Deploy falhou (exit code {result.returncode})")
        sys.exit(result.returncode)

    except KeyboardInterrupt:
        print("\nInterrompido pelo utilizador")
        sys.exit(1)


if __name__ == "__main__":
    args = parse_args()
    run(args)
