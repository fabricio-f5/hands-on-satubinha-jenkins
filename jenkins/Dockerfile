# =============================================================================
# Stage 1 — builder
# cgr.dev/chainguard/wolfi-base: shell + apk, zero CVEs conhecidos
# Instala Terraform e Terragrunt (binarios estaticos Go — copiavel sem deps)
# AWS CLI e Checkov NAO entram na imagem — geridos pelo Ansible no host
# =============================================================================
FROM cgr.dev/chainguard/wolfi-base AS builder

ARG TERRAFORM_VERSION=1.14.7
ARG TERRAGRUNT_VERSION=0.99.0

RUN apk update && apk add --no-cache \
    curl \
    unzip

# --- Terraform ---
RUN curl -fsSL \
    "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" \
    -o /tmp/terraform.zip \
    && unzip /tmp/terraform.zip -d /tmp/terraform-bin \
    && chmod +x /tmp/terraform-bin/terraform

# --- Terragrunt ---
RUN curl -fsSL \
    "https://github.com/gruntwork-io/terragrunt/releases/download/v${TERRAGRUNT_VERSION}/terragrunt_linux_amd64" \
    -o /tmp/terragrunt \
    && chmod +x /tmp/terragrunt

# =============================================================================
# Stage 2 — runtime
# jenkins/jenkins LTS oficial — USER jenkins, sem root, sem ferramentas extra
# Recebe apenas os binarios estaticos do builder via COPY --from
# =============================================================================
FROM jenkins/jenkins:2.492.3-lts-jdk21

# Copiar binarios estaticos do builder — zero dependencias transitivas
COPY --from=builder --chown=root:root /tmp/terraform-bin/terraform /usr/local/bin/terraform
COPY --from=builder --chown=root:root /tmp/terragrunt /usr/local/bin/terragrunt

# Verificar binarios no contexto da imagem final
RUN terraform version && terragrunt --version

# -----------------------------------------------------------------------------
# Jenkins — configuracao declarativa
# Tudo via JCasC — zero cliques na UI, zero estado manual
# -----------------------------------------------------------------------------

# Desactivar wizard de setup inicial
ENV JAVA_OPTS="-Djenkins.install.runSetupWizard=false"

# Caminho do ficheiro JCasC montado pelo Ansible em runtime
ENV CASC_JENKINS_CONFIG=/var/jenkins_home/casc/jenkins.yaml

# Instalar plugins declarativamente — reproduzivel
COPY --chown=jenkins:jenkins plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN jenkins-plugin-cli --plugin-file /usr/share/jenkins/ref/plugins.txt

# USER jenkins e o default da imagem base — explicito para clareza
USER jenkins
