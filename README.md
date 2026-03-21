# hands-on-satubinha-jenkins

Jenkins self-hosted na AWS provisionado como IaC — parte da série **hands-on-satubinha**.

## Contexto

Evolução do [hands-on-satubinha-iac-terragrunt](https://github.com/fabricio-f5/hands-on-satubinha-iac-terragrunt). Substitui o GitHub Actions como executor dos pipelines Terragrunt por um Jenkins self-hosted na AWS, reduzindo o tempo de execução e ganhando controlo total sobre o ambiente de CI/CD.

## Stack

| Ferramenta | Função |
|---|---|
| Terraform | Provisiona EC2, Security Group, IAM Role, Elastic IP, ECR, Secrets Manager |
| Ansible | Configura o servidor — Docker, Cosign, build/push da imagem, arranque do Jenkins |
| Docker multistage | Imagem customizada Jenkins + Terraform + Terragrunt (Chainguard wolfi-base como builder) |
| Jenkins + JCasC | CI/CD self-hosted com configuração declarativa, sem cliques na UI |
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
├── terraform/                  # Infra AWS
│   ├── main.tf                 # EC2, SG, IAM Role, EIP, ECR, Secrets Manager
│   ├── variables.tf
│   ├── outputs.tf
│   ├── backend.tf              # State no S3 com lock nativo
│   └── terraform.tfvars.example
├── ansible/                    # Configuracao do servidor
│   ├── playbook.yml
│   ├── inventory.ini.example
│   ├── cosign.pub              # Chave publica para verificacao de imagens
│   ├── group_vars/
│   │   └── all/
│   │       ├── all.yml         # Variaveis partilhadas
│   │       └── vault.yml       # Secrets encriptados (Ansible Vault)
│   └── roles/
│       ├── docker/             # Instala Docker, AWS CLI, Checkov, Cosign
│       ├── ecr_build_push/     # Build, assina e push da imagem para ECR
│       └── jenkins/            # Verifica assinatura, pull, arranca container
├── jenkins/                    # Imagem Docker customizada
│   ├── Dockerfile              # Multistage: Chainguard builder + Jenkins runtime
│   ├── plugins.txt             # Plugins declarativos com versoes pinadas
│   └── casc/
│       └── jenkins.yaml        # Jenkins Configuration as Code (JCasC)
├── pipelines/                  # Em construcao
│   └── Jenkinsfile
└── README.md
```

## Segurança

- **IAM Role via Instance Profile** — zero credenciais estáticas AWS, equivalente ao OIDC do GitHub Actions
- **Dockerfile multistage** — stage builder Chainguard wolfi-base descartado, runtime sem root
- **ECR IMMUTABLE tags** — uma tag nunca pode ser sobrescrita após push
- **Cosign key-based** — imagem assinada após push, verificada antes do `docker run`
- **Ansible Vault** — credenciais Jenkins encriptadas no repositório
- **Porta 8080 restrita** — só aceita CIDRs do GitHub (webhooks), UI acessível via SSH tunnel

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
# Gerar par de chaves
cosign generate-key-pair

# Popular o secret no Secrets Manager
aws secretsmanager put-secret-value \
  --secret-id hands-on-satubinha-jenkins/cosign-private-key \
  --secret-string file://cosign.key

# Mover chave publica para o ansible e commitar
mv cosign.pub ansible/cosign.pub
git add ansible/cosign.pub
git commit -m "feat: add cosign public key"

# Apagar a chave privada local — nunca commitar
rm cosign.key
```

### 3. Configurar o Ansible

```bash
cd ansible/

# Inventory com o Elastic IP do terraform output
cp inventory.ini.example inventory.ini
# editar inventory.ini com o IP real

# Criar vault com credenciais Jenkins
mkdir -p group_vars/all
ansible-vault create group_vars/all/vault.yml
# adicionar dentro:
# vault_jenkins_admin_user: admin
# vault_jenkins_admin_password: SuaPasswordSegura
```

### 4. Correr o Ansible

```bash
# Completo
ansible-playbook -i inventory.ini playbook.yml --ask-vault-pass

# Por fases
ansible-playbook -i inventory.ini playbook.yml --tags "docker" --ask-vault-pass
ansible-playbook -i inventory.ini playbook.yml --tags "ecr" --ask-vault-pass
ansible-playbook -i inventory.ini playbook.yml --tags "jenkins" --ask-vault-pass
```

### 5. Aceder ao Jenkins

```bash
# Abrir SSH tunnel
ssh -L 8080:localhost:8080 \
  -i ~/.ssh/hands-on-satubinha-key.pem \
  ubuntu@<ELASTIC_IP> -N

# Browser
open http://localhost:8080
```

## Decisões Técnicas

**Porque EC2 e não EKS para o Jenkins?**
O EKS é o próximo projecto da série (`satubinha-k8s`) onde o `satubinha-app` vai correr com Argo CD e observabilidade. Misturar Jenkins no EKS aqui adicionaria complexidade sem valor adicional para o que se pretende demonstrar.

**Porque Cosign key-based e não keyless?**
Cosign keyless requer um OIDC provider suportado pelo Fulcio (GitHub, Google, Microsoft). Um EC2 não tem OIDC nativo — key-based com chave privada no Secrets Manager é a abordagem correcta para runners self-hosted.

**Porque `use_lockfile` e não DynamoDB para o state lock?**
O Terraform 1.10+ suporta lock nativo no S3 via `use_lockfile = true`, eliminando a dependência de uma tabela DynamoDB separada.

## Roadmap

- [x] Terraform — EC2, SG, IAM Role, Elastic IP, ECR, Secrets Manager
- [x] Dockerfile multistage — Chainguard builder + Jenkins runtime sem root
- [x] JCasC — configuração declarativa do Jenkins
- [x] Ansible role: docker — Docker, AWS CLI, Checkov, Cosign
- [x] Ansible role: ecr_build_push — build, sign, push para ECR
- [x] Ansible role: jenkins — verify, pull, run
- [x] Ansible Vault — credenciais encriptadas
- [ ] Jenkinsfile — pipeline equivalente ao GitHub Actions
- [ ] Webhook GitHub → Jenkins

## Série hands-on-satubinha

| Projecto | Descrição | Estado |
|---|---|---|
| [satubinha-app](https://github.com/fabricio-f5/satubinha-app) | App fullstack com Docker Compose, Chainguard, Flyway | ✅ |
| [satubinha-iac-terragrunt](https://github.com/fabricio-f5/hands-on-satubinha-iac-terragrunt) | Infra AWS com Terraform + Terragrunt | ✅ |
| **satubinha-jenkins** | Jenkins self-hosted como IaC | 🔄 em progresso |
| satubinha-k8s | EKS + Argo CD + Prometheus/Grafana | 🔲 em breve |
