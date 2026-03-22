terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# -----------------------------------------------------------------------------
# Data Sources
# -----------------------------------------------------------------------------

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

data "aws_vpc" "default" {
  default = true
}

# -----------------------------------------------------------------------------
# Security Group
# -----------------------------------------------------------------------------

resource "aws_security_group" "jenkins" {
  name        = "${var.project_name}-jenkins-sg"
  description = "Security Group para o Jenkins EC2"
  vpc_id      = data.aws_vpc.default.id

  # SSH — aberto para qualquer IP (ambiente de laboratorio)
  # NOTA: em producao restringir a var.allowed_ssh_cidrs ou usar SSM Session Manager
  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Webhooks do GitHub — apenas CIDRs oficiais do GitHub
  # https://api.github.com/meta (campo "hooks")
  ingress {
    description = "GitHub Webhooks"
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = var.github_webhook_cidrs
  }

  # Saida livre — para pull de imagens, pacotes, AWS APIs
  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.common_tags, {
    Name = "${var.project_name}-jenkins-sg"
  })
}

# -----------------------------------------------------------------------------
# IAM Role + Instance Profile (sem credenciais estaticas)
# -----------------------------------------------------------------------------

resource "aws_iam_role" "jenkins" {
  name        = "${var.project_name}-jenkins-role"
  description = "IAM Role para o Jenkins EC2 - acesso via Instance Profile"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "ec2.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = merge(var.common_tags, {
    Name = "${var.project_name}-jenkins-role"
  })
}

resource "aws_iam_role_policy" "jenkins" {
  name = "${var.project_name}-jenkins-policy"
  role = aws_iam_role.jenkins.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # S3 — leitura e escrita no bucket de state do Terragrunt
      {
        Sid    = "TerragruntState"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket",
          "s3:GetBucketVersioning",
          "s3:GetBucketLocation"
        ]
        Resource = [
          "arn:aws:s3:::${var.tfstate_bucket}",
          "arn:aws:s3:::${var.tfstate_bucket}/*"
        ]
      },

      # ECR — GetAuthorizationToken e obrigatorio a nivel de conta, nao de repositorio
      {
        Sid      = "ECRAuthToken"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },

      # ECR — operacoes de push/pull restritas ao repositorio Jenkins
      {
        Sid    = "ECRJenkinsRepo"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:PutImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:DescribeImages",
          "ecr:ListImages"
        ]
        Resource = "arn:aws:ecr:${var.aws_region}:${var.aws_account_id}:repository/${var.project_name}/jenkins"
      },

      # Secrets Manager — leitura da chave privada Cosign
      {
        Sid    = "CosignPrivateKey"
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret"
        ]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:${var.project_name}/cosign-private-key*"
      },

      # Terragrunt — permissoes para plan/apply na layer foundation e ec2
      {
        Sid    = "TerragruntInfra"
        Effect = "Allow"
        Action = [
          # VPC / Network
          "ec2:DescribeVpcs",
          "ec2:DescribeSubnets",
          "ec2:DescribeInternetGateways",
          "ec2:DescribeRouteTables",
          "ec2:DescribeSecurityGroups",
          "ec2:DescribeSecurityGroupRules",
          "ec2:DescribeInstances",
          "ec2:DescribeInstanceTypes",
          "ec2:DescribeImages",
          "ec2:DescribeKeyPairs",
          "ec2:DescribeAddresses",
          "ec2:DescribeAvailabilityZones",
          "ec2:DescribeAccountAttributes",
          "ec2:DescribeInstanceAttribute",
          "ec2:DescribeVolumes",
          "ec2:DescribeNetworkInterfaces",
          "ec2:DescribeVpcAttribute",
          # IAM — para o instance profile do EC2
          "iam:GetRole",
          "iam:GetInstanceProfile",
          "iam:GetRolePolicy",
          "iam:ListRolePolicies",
          "iam:ListAttachedRolePolicies",
          "iam:ListInstanceProfilesForRole",
          # Secrets Manager — listagem para o plan do EC2
          "secretsmanager:ListSecrets",
          # STS — decodificacao de mensagens de erro IAM
          "sts:DecodeAuthorizationMessage"
        ]
        Resource = "*"
      }
    ]
  })
}

# AmazonEC2FullAccess — necessario para o Terragrunt executar plan/apply
# nas layers foundation (VPC, SG) e ec2 (EC2, EIP, IAM Instance Profile)
# TODO: substituir por policy de least privilege apos mapeamento completo
resource "aws_iam_role_policy_attachment" "jenkins_ec2_full" {
  role       = aws_iam_role.jenkins.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2FullAccess"
}

resource "aws_iam_instance_profile" "jenkins" {
  name = "${var.project_name}-jenkins-profile"
  role = aws_iam_role.jenkins.name

  tags = merge(var.common_tags, {
    Name = "${var.project_name}-jenkins-profile"
  })
}

# -----------------------------------------------------------------------------
# EC2
# -----------------------------------------------------------------------------

resource "aws_instance" "jenkins" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  key_name               = var.key_pair_name
  vpc_security_group_ids = [aws_security_group.jenkins.id]
  iam_instance_profile   = aws_iam_instance_profile.jenkins.name

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.ebs_size_gb
    delete_on_termination = true
    encrypted             = true

    tags = merge(var.common_tags, {
      Name = "${var.project_name}-jenkins-ebs"
    })
  }

  # User data — pre-requisitos para o Ansible
  user_data = <<-EOF
    #!/bin/bash
    set -e
    apt-get update -y
    apt-get install -y python3 python3-pip
  EOF

  tags = merge(var.common_tags, {
    Name = "${var.project_name}-jenkins-ec2"
  })
}

# -----------------------------------------------------------------------------
# Elastic IP
# -----------------------------------------------------------------------------

resource "aws_eip" "jenkins" {
  instance = aws_instance.jenkins.id
  domain   = "vpc"

  tags = merge(var.common_tags, {
    Name = "${var.project_name}-jenkins-eip"
  })

  depends_on = [aws_instance.jenkins]
}

# -----------------------------------------------------------------------------
# ECR Repository — imagem Jenkins assinada com Cosign
# -----------------------------------------------------------------------------

resource "aws_ecr_repository" "jenkins" {
  name                 = "${var.project_name}/jenkins"
  image_tag_mutability = "IMMUTABLE"

  # Scan automatico em cada push — detecta CVEs nas layers
  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = merge(var.common_tags, {
    Name = "${var.project_name}-ecr-jenkins"
  })
}

resource "aws_ecr_lifecycle_policy" "jenkins" {
  repository = aws_ecr_repository.jenkins.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Manter apenas as ultimas 5 imagens tagged"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["v"]
          countType     = "imageCountMoreThan"
          countNumber   = 5
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Remover imagens untagged apos 7 dias"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }
        action = { type = "expire" }
      }
    ]
  })
}

# -----------------------------------------------------------------------------
# Secrets Manager — chave privada Cosign para assinatura da imagem
# -----------------------------------------------------------------------------

resource "aws_secretsmanager_secret" "cosign_private_key" {
  name        = "${var.project_name}/cosign-private-key"
  description = "Chave privada Cosign para assinar imagens Docker no ECR"

  tags = merge(var.common_tags, {
    Name = "${var.project_name}-cosign-private-key"
  })
}
