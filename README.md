# hands-on-satubinha-jenkins

Plataforma de execução de infraestrutura self-hosted na AWS — parte da série **hands-on-satubinha**.

## Contexto

Projecto paralelo ao [hands-on-satubinha-iac-terragrunt](https://github.com/fabricio-f5/hands-on-satubinha-iac-terragrunt). Enquanto o `satubinha-iac-terragrunt` define **o que** provisionar, o `satubinha-jenkins` define **quem** executa o provisionamento — são dois planos independentes com responsabilidades distintas:

```
satubinha-iac-terragrunt   ←──── satubinha-jenkins
(infra repo)                      (pipeline repo — consome o infra repo)
```

O Jenkins não substitui o GitHub Actions — coexiste com ele. O mesmo repositório de infra pode ser executado por qualquer executor (GitHub Actions, Jenkins, CLI local) sem alterações. O `satubinha-jenkins` demonstra como construir um executor de CI/CD self-hosted agnóstico ao repositório de infra, introduzindo o conceito de plataforma de execução genérica: o mesmo `Jenkinsfile.infra` serve qualquer repositório que siga a estrutura `environments/<env>/<layer>/terragrunt.hcl`.

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

## Arquitectura

```
GitHub (push)
      │
      ▼
Jenkins EC2 (runner)
      │
      ▼
Jenkinsfile.infra (parametrizado)
      │
      ├── REPO_URL      → qualquer repositório de infra
      ├── ENVIRONMENT   → dev | staging | prod
      ├── PIPELINE_TYPE → foundation | ec2
      └── ACTION        → plan | apply | plan-destroy | destroy
            │
            ├── terraform fmt -check
            ├── terragrunt validate
            ├── checkov scan
            ├── terragrunt plan
            └── terragrunt apply / destroy (com confirmação manual)
```

## Jenkins como plano de controlo genérico

O Jenkins neste projecto não está acoplado a nenhum repositório de infraestrutura específico — funciona como plataforma de execução genérica. O `Jenkinsfile.infra` aceita qualquer repositório que siga a estrutura `environments/<env>/<layer>/terragrunt.hcl`.

Esta separação segue o padrão de mercado de *pipeline repo* vs *infra repo*:

| Repo | Responsabilidade |
|---|---|
| `satubinha-jenkins` | Provisiona e mantém o Jenkins EC2 — pipeline repo |
| `satubinha-iac-terragrunt` | Define a infraestrutura — infra repo |

O executor de CI/CD é independente do código que executa. O Jenkins pode ser substituído por qualquer outro CI sem tocar no Terraform, e o mesmo repositório de infra pode ser consumido por múltiplos executores em paralelo.

### Confirmação por ambiente

Apply e destroy em staging e prod exigem confirmação tipada — prevenindo operações acidentais em ambientes críticos:

| Ambiente | Apply | Destroy |
|---|---|---|
| dev | Confirmação simples (click) | `dev-destroy` |
| staging | `staging-apply` | `staging-destroy` |
| prod | `prod-apply` | `prod-destroy` |

### Ordem de operações recomendada

**Criar infra do zero:**
```
foundation → plan → apply
ec2        → plan → apply
```

**Destruir infra:**
```
ec2        → plan-destroy → destroy
foundation → plan-destroy → destroy
```

> A layer `ec2` depende dos outputs da `foundation` (subnet_id, sg_id). Destruir a foundation com o ec2 activo causa erros — destruir sempre pela ordem inversa.

---

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
│   └── Jenkinsfile.infra             # Pipeline genérico parametrizado
├── deploy.py                         # Script de deploy via Ansible
├── jenkins-trigger.py                # Script de trigger de pipelines Jenkins
├── jenkins-ui.py                     # Script SSH tunnel + browser (corre na máquina local)
└── README.md
```

---

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
- **Porta 8080 restrita** — só aceita CIDRs oficiais do GitHub, UI acessível via SSH tunnel
- **Confirmação tipada em staging/prod** — apply e destroy exigem texto exacto, prevenindo operações acidentais

---

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

python3 deploy.py
```

---

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
wget -q http://localhost:8080/jnlpJars/jenkins-cli.jar

python3 jenkins-trigger.py satubinha-infra plan   --env dev     --type foundation
python3 jenkins-trigger.py satubinha-infra apply  --env staging --type ec2
python3 jenkins-trigger.py satubinha-infra destroy --env prod   --type foundation
python3 jenkins-trigger.py --list
```

### `jenkins-ui.py` — SSH tunnel + browser (corre na máquina local)

```bash
python3 jenkins-ui.py                    # abre tunnel e browser automaticamente
python3 jenkins-ui.py --ip 107.23.89.54  # IP alternativo
python3 jenkins-ui.py --port 9090        # porta local alternativa
python3 jenkins-ui.py --no-browser       # só o tunnel, sem abrir browser
```

---

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
# editar inventory.ini com o IP da EC2

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
python3 jenkins-ui.py
# abre SSH tunnel e browser automaticamente em http://localhost:8080
```

### 6. Criar o job satubinha-infra no Jenkins UI

```
Dashboard → New Item
  Nome:  satubinha-infra
  Tipo:  Pipeline → OK

General:
  ✅ GitHub project
  Project url: https://github.com/fabricio-f5/hands-on-satubinha-iac-terragrunt/

Build Triggers:
  ✅ GitHub hook trigger for GITScm polling

Pipeline:
  Definition:     Pipeline script from SCM
  SCM:            Git
  Repository URL: https://github.com/fabricio-f5/hands-on-satubinha-jenkins.git
  Branch:         */master
  Script Path:    pipelines/Jenkinsfile.infra
  → Save
```

> Na primeira execução clica `Build Now` para o Jenkins registar os parâmetros.
> A partir do segundo build usa `Build with Parameters`.

### 7. Executar um pipeline

```
Build with Parameters:
  REPO_URL      → https://github.com/fabricio-f5/hands-on-satubinha-iac-terragrunt.git
  REPO_BRANCH   → main
  ENVIRONMENT   → dev
  PIPELINE_TYPE → foundation
  ACTION        → plan
```

---

## Pré-requisitos

- AWS CLI configurado com permissões suficientes
- Terraform >= 1.10.0
- Ansible >= 2.15
- Cosign instalado localmente
- Bucket S3 `hands-on-satubinha-tfstate` existente
- Key Pair `hands-on-satubinha-key` criado via AWS CLI e `.pem` guardada em `~/.ssh/`

---

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

**Porque um único `Jenkinsfile.infra` em vez de um ficheiro por ambiente?**
A alternativa seria ter `Jenkinsfile.foundation`, `Jenkinsfile.ec2`, `Jenkinsfile.staging-ec2`, `Jenkinsfile.prod-foundation`, etc. — ficheiros quase idênticos que divergem gradualmente e criam inconsistências silenciosas. Um pipeline parametrizado elimina a duplicação e torna o Jenkins agnóstico ao repositório de infra: o mesmo `Jenkinsfile.infra` serve o `satubinha-iac-terragrunt` hoje e qualquer outro repositório amanhã, desde que siga a estrutura `environments/<env>/<layer>/terragrunt.hcl`. Esta é a diferença entre um *pipeline repo* acoplado e uma plataforma de execução genérica.

**Porque Terraform provider cache partilhado (`TF_PLUGIN_CACHE_DIR`)?**
O Terragrunt cria um `.terragrunt-cache` isolado por layer, o que faz com que o provider `hashicorp/aws` (~400MB) seja baixado separadamente para cada layer em cada run. Com `TF_PLUGIN_CACHE_DIR` configurado no `root.hcl`, todos os layers partilham a mesma cópia do provider — o download acontece uma vez e os runs seguintes reutilizam o cache. O directório é criado automaticamente pelo Ansible no provisionamento da EC2.

**Checkov neste projecto vs. projecto anterior (`satubinha-iac-terragrunt`)**

No projecto anterior, o Checkov corria via GitHub Actions com `soft_fail: true` — nunca bloqueava nada. Neste projecto corre dentro do container Jenkins com `--hard-fail-on` explícito. Durante os testes, o Checkov detectou `CKV_AWS_18` (S3 sem access logging) e bloqueou o pipeline — o finding foi corrigido no módulo S3. Os checks de lab aceitáveis estão documentados com `--skip-check`, tornando as decisões de segurança rastreáveis no código.

| | satubinha-iac-terragrunt | satubinha-jenkins |
|---|---|---|
| Execução | GitHub Actions | Jenkins (container) |
| Modo | `soft_fail: true` | `--hard-fail-on` por check |
| Comportamento | Nunca bloqueia | Bloqueia em findings reais |
| Resultado de falha | Artefacto de relatório | Pipeline falhado |
| Decisões documentadas | Não | `--skip-check` com justificação |

**Porque versioning `vX.Y-<sha>-stable`?**
O SHA do commit garante rastreabilidade total — dado o tag consegues fazer `git checkout <sha>` e reproduzir o build exacto. O sufixo `stable` indica que a imagem passou todos os gates de segurança e healthcheck. A versão semântica `vX.Y` é controlada manualmente, sinalizando mudanças significativas na imagem sem depender de auto-increment cego.

---

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
- [x] Jenkinsfile.infra — pipeline genérico parametrizado (substitui Jenkinsfile.foundation + Jenkinsfile.ec2)
- [x] Terraform provider cache partilhado — TF_PLUGIN_CACHE_DIR via root.hcl + Ansible
- [x] Testes end-to-end — plan, apply e destroy validados em dev, staging e prod
- [x] Stable tag versioning — vX.Y-<sha>-stable com promoção automática
- [x] deploy.py — script de deploy via Ansible
- [x] jenkins-trigger.py — script de trigger de pipelines
- [x] jenkins-ui.py — script SSH tunnel + browser

---

## Série hands-on-satubinha

| Projecto | Descrição | Relação | Estado |
|---|---|---|---|
| [satubinha-app](https://github.com/fabricio-f5/satubinha-app) | App fullstack com Docker Compose, Chainguard, Flyway | — | ✅ |
| [satubinha-iac-terragrunt](https://github.com/fabricio-f5/hands-on-satubinha-iac-terragrunt) | Infra AWS multi-ambiente com Terraform + Terragrunt | infra repo | ✅ |
| **satubinha-jenkins** | Plataforma de execução de infra self-hosted | pipeline repo — consome o satubinha-iac-terragrunt | ✅ |
| satubinha-k8s | EKS + Argo CD + Prometheus/Grafana | — | 🔲 em breve |
