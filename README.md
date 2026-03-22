# hands-on-satubinha-jenkins

Jenkins self-hosted na AWS provisionado como IaC — parte da série **hands-on-satubinha**.

## Contexto

Evolução do [hands-on-satubinha-iac-terragrunt](https://github.com/fabricio-f5/hands-on-satubinha-iac-terragrunt). Substitui o GitHub Actions como executor dos pipelines Terragrunt por um Jenkins self-hosted na AWS, reduzindo o tempo de execução e ganhando controlo total sobre o ambiente de CI/CD.

## Stack

| Ferramenta | Função |
|---|---|
| Terraform | Provisiona EC2, Security Group, IAM Role, Elastic IP, ECR, Secrets Manager |
| Ansible | Configura o servidor — Docker, Cosign, build/push da imagem, arranque do Jenkins |
| Docker multistage | Imagem customizada Jenkins + Terraform + Terragrunt + Checkov (Chainguard wolfi-base como builder) |
| Jenkins + JCasC | CI/CD self-hosted com configuração declarativa, sem cliques na UI |
| Trivy | Scan de vulnerabilidades da imagem antes do push para ECR e no pull da stable |
| Container Structure Tests | Validação estrutural da imagem — binários, user, env vars |
| Cosign + ECR | Assinatura e verificação de imagens — supply chain security |
| Ansible Vault | Gestão de secrets — credenciais nunca em plaintext |
| GitHub Actions | Mantido apenas como webhook trigger |

## Arquitectura

```
GitHub (push)
      │
      ▼
GitHub Actions (webhook trigger)
      │
      ▼
Jenkins EC2 (runner)
      │
      ├── terraform fmt -check
      ├── terragrunt validate
      ├── checkov scan
      ├── terragrunt plan
      └── terragrunt apply / destroy
```

## Estrutura do Repositório

```
hands-on-satubinha-jenkins/
├── terraform/                        # Infra AWS
│   ├── main.tf                       # EC2, SG, IAM Role, EIP, ECR, Secrets Manager
│   ├── variables.tf
│   ├── outputs.tf
│   ├── backend.tf                    # State no S3 com lock nativo
│   └── terraform.tfvars.example
├── ansible/                          # Configuracao do servidor
│   ├── playbook.yml
│   ├── inventory.ini.example
│   ├── cosign.pub                    # Chave publica para verificacao de imagens
│   ├── group_vars/
│   │   └── all/
│   │       ├── all.yml               # Variaveis partilhadas (inclui jenkins_image_version)
│   │       └── vault.yml             # Secrets encriptados (Ansible Vault)
│   └── roles/
│       ├── docker/                   # Instala Docker, AWS CLI, Cosign
│       ├── ecr_build_push/           # Build, Trivy scan, CST, push, cosign sign
│       └── jenkins/                  # 4 security checks, pull, run, healthcheck, stable promotion
├── jenkins/                          # Imagem Docker customizada
│   ├── Dockerfile                    # Multistage: Chainguard builder + Jenkins runtime
│   ├── plugins.txt                   # Plugins declarativos com versoes pinadas
│   ├── container-structure-test.yaml # Validacao estrutural da imagem
│   └── casc/
│       └── jenkins.yaml              # Jenkins Configuration as Code (JCasC)
├── pipelines/
│   ├── Jenkinsfile.foundation        # Pipeline layer foundation (network + security-group)
│   └── Jenkinsfile.ec2               # Pipeline layer ec2
├── deploy.py                         # Script de deploy via Ansible
├── jenkins-trigger.py                # Script de trigger de pipelines Jenkins
├── jenkins-ui.py                     # Script SSH tunnel + browser (corre na máquina local)
└── README.md
```

## Segurança

- **IAM Role via Instance Profile** — zero credenciais estáticas AWS, equivalente ao OIDC do GitHub Actions
- **Dockerfile multistage** — stage builder Chainguard wolfi-base descartado, runtime sem root
- **ECR IMMUTABLE tags** — uma tag nunca pode ser sobrescrita após push
- **Trivy scan no build** — bloqueia push se existirem CVEs CRITICAL ou HIGH na imagem
- **Container Structure Tests no build** — valida binários, user, env vars antes do push
- **Cosign key-based** — imagem assinada após push, verificada antes do `docker run`
- **4 verificações de segurança no pull da stable:**
  - `[1/4]` Cosign verify — assinatura válida pela chave correcta
  - `[2/4]` Digest check — digest local == digest registado no ECR
  - `[3/4]` Trivy scan — sem CVEs CRITICAL novas desde o build original
  - `[4/4]` Container Structure Test — binários presentes e funcionais
- **Ansible Vault** — credenciais Jenkins encriptadas no repositório
- **Porta 8080 restrita** — só aceita CIDRs do GitHub (webhooks), UI acessível via SSH tunnel

## Gestão de Imagens e Versioning

As imagens seguem o formato `vX.Y-<sha>-stable`:

- `vX.Y` — versão semântica controlada manualmente em `all.yml` (`jenkins_image_version`)
- `<sha>` — short commit hash do repo `satubinha-jenkins` que gerou a imagem
- `stable` — sufixo que indica que a imagem passou todos os gates e está em produção

Exemplo: `v1.0-28adda5-stable`

### Fluxo de deploy

```
Ansible arranca
      │
      ▼
ECR tem tag *-stable?
      │
   sim│                              não│
      ▼                                 ▼
Pull vX.Y-<sha>-stable            git clone → SHA do commit
4 security checks                 Tag: vX.Y-<sha>
Run Jenkins                       Build → Trivy → CST → Push
Healthcheck                       Cosign sign
                                        │
                                        ▼
                                  Run Jenkins
                                  Healthcheck ✅
                                        │
                                        ▼
                                  Promove vX.Y-<sha>-stable
                                  Remove stable anterior
```

### Forçar novo build

```bash
# Apagar tag stable actual
aws ecr batch-delete-image \
  --repository-name hands-on-satubinha-jenkins/jenkins \
  --image-ids imageTag=v1.0-28adda5-stable \
  --region us-east-1

python3 deploy.py
```

### Rollback

```bash
# 1. Apagar stable actual
aws ecr batch-delete-image \
  --repository-name hands-on-satubinha-jenkins/jenkins \
  --image-ids imageTag=v1.0-28adda5-stable \
  --region us-east-1

# 2. Recriar stable apontando para versao anterior
MANIFEST=$(aws ecr batch-get-image \
  --repository-name hands-on-satubinha-jenkins/jenkins \
  --image-ids imageTag=v1.0-<sha-anterior> \
  --query 'images[0].imageManifest' --output text \
  --region us-east-1)

aws ecr put-image \
  --repository-name hands-on-satubinha-jenkins/jenkins \
  --image-tag v1.0-<sha-anterior>-stable \
  --image-manifest "$MANIFEST" \
  --region us-east-1

# 3. Deploy
python3 deploy.py
```

### Nova versão semântica

Quando há uma mudança significativa na imagem (novo plugin major, mudança de JDK, etc.):

```bash
# Editar all.yml
jenkins_image_version: "v2.0"

# Apagar stable actual e deploy
aws ecr batch-delete-image ...
python3 deploy.py
# → builda v2.0-<novo-sha>, promove v2.0-<novo-sha>-stable
```

## Scripts

### `deploy.py` — deploy via Ansible

```bash
python3 deploy.py                      # deploy completo
python3 deploy.py --tags docker        # só instalar docker
python3 deploy.py --tags ecr,jenkins   # rebuild imagem + restart jenkins
python3 deploy.py --vault-pass PASS    # sem prompt de vault
python3 deploy.py --check              # dry-run
```

### `jenkins-trigger.py` — disparar pipelines Jenkins (corre na EC2)

```bash
# Requer jenkins-cli.jar em ~/
wget -q http://localhost:8080/jnlpJars/jenkins-cli.jar

python3 jenkins-trigger.py satubinha-foundation plan
python3 jenkins-trigger.py satubinha-ec2 apply
python3 jenkins-trigger.py satubinha-foundation destroy
python3 jenkins-trigger.py --list     # lista jobs e actions disponíveis
```

### `jenkins-ui.py` — SSH tunnel + browser (corre na máquina local)

```bash
python3 jenkins-ui.py                          # abre tunnel e browser automaticamente
python3 jenkins-ui.py --ip 107.23.89.54        # IP alternativo
python3 jenkins-ui.py --port 9090              # porta local alternativa
python3 jenkins-ui.py --no-browser             # só o tunnel, sem abrir browser
```

## Pré-requisitos

- AWS CLI configurado com permissões suficientes
- Terraform >= 1.10.0
- Ansible >= 2.15
- Cosign instalado localmente
- Bucket S3 `hands-on-satubinha-tfstate` existente
- Key Pair `hands-on-satubinha-key` criado via AWS CLI e `.pem` guardada em `~/.ssh/`

## Como Usar

### 1. Provisionar a infra

```bash
cd terraform/
terraform init
terraform plan -out=tfplan
terraform apply tfplan
```

### 2. Setup inicial do Cosign (apenas na primeira vez)

```bash
cosign generate-key-pair

aws secretsmanager put-secret-value \
  --secret-id hands-on-satubinha-jenkins/cosign-private-key \
  --secret-string file://cosign.key

mv cosign.pub ansible/cosign.pub
git add ansible/cosign.pub
git commit -m "feat: add cosign public key"

rm cosign.key
```

### 3. Configurar o Ansible

```bash
cd ansible/
cp inventory.ini.example inventory.ini
# editar inventory.ini com o IP real

ansible-vault create group_vars/all/vault.yml
# adicionar:
# vault_jenkins_admin_user: admin
# vault_jenkins_admin_password: SuaPasswordSegura
```

### 4. Deploy

```bash
python3 deploy.py
```

### 5. Aceder ao Jenkins

```bash
ssh -L 8080:localhost:8080 \
  -i ~/.ssh/hands-on-satubinha-key.pem \
  ubuntu@<ELASTIC_IP> -N

open http://localhost:8080
```

### 6. Disparar pipelines

```bash
# Na EC2
wget -q http://localhost:8080/jnlpJars/jenkins-cli.jar
python3 jenkins-trigger.py satubinha-foundation plan
```

## Decisões Técnicas

**Porque EC2 e não EKS para o Jenkins?**
O EKS é o próximo projecto da série (`satubinha-k8s`) onde o `satubinha-app` vai correr com Argo CD e observabilidade. Misturar Jenkins no EKS aqui adicionaria complexidade sem valor adicional para o que se pretende demonstrar.

**Porque Cosign key-based e não keyless?**
Cosign keyless requer um OIDC provider suportado pelo Fulcio (GitHub, Google, Microsoft). Um EC2 não tem OIDC nativo — key-based com chave privada no Secrets Manager é a abordagem correcta para runners self-hosted.

**Porque `use_lockfile` e não DynamoDB para o state lock?**
O Terraform 1.10+ suporta lock nativo no S3 via `use_lockfile = true`, eliminando a dependência de uma tabela DynamoDB separada.

**Porque Container Structure Tests?**
O Trivy cobre vulnerabilidades e o Cosign cobre integridade, mas nenhum valida se os binários esperados estão presentes e funcionais na imagem. O CST fecha essa lacuna — é documentação executável do contrato da imagem. No pull da stable, o CST corre novamente para garantir que a imagem não foi corrompida após o build original.

**Porque Checkov na imagem Jenkins e não só no pre-commit?**
O pre-commit corre localmente e pode ser contornado. O Checkov na imagem garante que o scan corre sempre no pipeline, independentemente do ambiente local do developer.

**Checkov neste projecto vs. projecto anterior (`satubinha-iac-terragrunt`)**

No projecto anterior, o Checkov corria via GitHub Actions com `soft_fail: true` em todos os workflows — nunca bloqueava nada. Os resultados iam para artefactos mas o pipeline continuava sempre verde independentemente das falhas. O Checkov era essencialmente decorativo.

Neste projecto, o Checkov corre dentro do container Jenkins com `--hard-fail-on` explícito. A diferença concreta: durante os testes, o Checkov detectou `CKV_AWS_18` (S3 sem access logging) e bloqueou o pipeline. O finding foi corrigido no módulo S3 — algo que o projecto anterior nunca teria tratado como problema real. Os checks de lab aceitáveis estão documentados com `--skip-check`, tornando as decisões de segurança rastreáveis no código em vez de invisíveis.

| | satubinha-iac-terragrunt | satubinha-jenkins |
|---|---|---|
| Execução | GitHub Actions | Jenkins (container) |
| Modo | `soft_fail: true` | `--hard-fail-on` por check |
| Comportamento | Nunca bloqueia | Bloqueia em findings reais |
| Resultado de falha | Artefacto de relatório | Pipeline falhado |
| Decisões documentadas | Não | `--skip-check` com justificação |

**Porque versioning `vX.Y-<sha>-stable`?**
O SHA do commit garante rastreabilidade total — dado o tag consegues fazer `git checkout <sha>` e reproduzir o build exacto. O sufixo `stable` indica que a imagem passou todos os gates de segurança e healthcheck. A versão semântica `vX.Y` é controlada manualmente, sinalizando mudanças significativas na imagem sem depender de auto-increment cego.

## Roadmap

- [x] Terraform — EC2, SG, IAM Role, Elastic IP, ECR, Secrets Manager
- [x] Dockerfile multistage — Chainguard builder + Jenkins runtime com Terraform, Terragrunt e Checkov
- [x] Trivy scan — bloqueia push com CVEs CRITICAL/HIGH
- [x] Container Structure Tests — validação estrutural da imagem
- [x] Cosign key-based — assinar e verificar imagem via Secrets Manager
- [x] JCasC — configuração declarativa do Jenkins
- [x] Ansible role: docker — Docker, AWS CLI, Cosign
- [x] Ansible role: ecr_build_push — build, Trivy, CST, sign, push para ECR
- [x] Ansible role: jenkins — 4 security checks, pull, run, healthcheck, stable promotion
- [x] Ansible Vault — credenciais encriptadas
- [x] Jenkinsfile.foundation — pipeline layer foundation (network + security-group)
- [x] Jenkinsfile.ec2 — pipeline layer ec2
- [x] Testes end-to-end dos pipelines — plan, apply e destroy testados e funcionais
- [x] Stable tag versioning — vX.Y-<sha>-stable com promoção automática
- [x] deploy.py — script de deploy via Ansible
- [x] jenkins-trigger.py — script de trigger de pipelines
- [x] jenkins-ui.py — script SSH tunnel + browser
- [ ] Webhook GitHub → Jenkins
- [ ] Ambientes staging e prod

## Série hands-on-satubinha

| Projecto | Descrição | Estado |
|---|---|---|
| [satubinha-app](https://github.com/fabricio-f5/satubinha-app) | App fullstack com Docker Compose, Chainguard, Flyway | ✅ |
| [satubinha-iac-terragrunt](https://github.com/fabricio-f5/hands-on-satubinha-iac-terragrunt) | Infra AWS com Terraform + Terragrunt | ✅ |
| **satubinha-jenkins** | Jenkins self-hosted como IaC | 🔄 em progresso |
| satubinha-k8s | EKS + Argo CD + Prometheus/Grafana | 🔲 em breve |
