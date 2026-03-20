variable "aws_region" {
  description = "Regiao AWS onde os recursos serao provisionados"
  type        = string
  default     = "us-east-1"
}

variable "aws_account_id" {
  description = "ID da conta AWS (usado nas policies IAM)"
  type        = string
  default     = "488914007569"
}

variable "project_name" {
  description = "Nome base do projecto — usado em todos os recursos e tags"
  type        = string
  default     = "hands-on-satubinha-jenkins"
}

variable "instance_type" {
  description = "Tipo de instancia EC2 para o Jenkins"
  type        = string
  default     = "t3.medium"
}

variable "ebs_size_gb" {
  description = "Tamanho do volume EBS root em GB"
  type        = number
  default     = 20
}

variable "key_pair_name" {
  description = "Nome do Key Pair existente na AWS para acesso SSH"
  type        = string
  default     = "hands-on-satubinha-key"
}

variable "tfstate_bucket" {
  description = "Bucket S3 para o state do Terragrunt (reutilizado)"
  type        = string
  default     = "hands-on-satubinha-tfstate"
}

variable "tfstate_lock_table" {
  description = "Tabela DynamoDB para lock do state Terragrunt"
  type        = string
  default     = "hands-on-satubinha-tfstate-lock"
}

variable "github_webhook_cidrs" {
  description = "CIDRs oficiais do GitHub para webhooks (porta 8080)"
  type        = list(string)
  # Fonte: https://api.github.com/meta (campo hooks)
  default = [
    "192.30.252.0/22",
    "185.199.108.0/22",
    "140.82.112.0/20",
    "143.55.64.0/20"
  ]
}

variable "common_tags" {
  description = "Tags aplicadas a todos os recursos"
  type        = map(string)
  default = {
    Project     = "hands-on-satubinha-jenkins"
    Environment = "lab"
    ManagedBy   = "terraform"
  }
}
