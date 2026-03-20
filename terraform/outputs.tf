output "jenkins_elastic_ip" {
  description = "Elastic IP do Jenkins — usar no inventory do Ansible e no webhook do GitHub"
  value       = aws_eip.jenkins.public_ip
}

output "jenkins_instance_id" {
  description = "Instance ID do EC2 do Jenkins"
  value       = aws_instance.jenkins.id
}

output "jenkins_ami_id" {
  description = "AMI usada na instancia (Ubuntu 22.04 mais recente)"
  value       = data.aws_ami.ubuntu.id
}

output "jenkins_iam_role_arn" {
  description = "ARN da IAM Role do Jenkins"
  value       = aws_iam_role.jenkins.arn
}

output "jenkins_security_group_id" {
  description = "ID do Security Group do Jenkins"
  value       = aws_security_group.jenkins.id
}

output "ssh_tunnel_command" {
  description = "Comando para criar o SSH tunnel e aceder a UI do Jenkins"
  value       = "ssh -L 8080:localhost:8080 -i ~/.ssh/hands-on-satubinha-key.pem ubuntu@${aws_eip.jenkins.public_ip}"
}

output "ansible_inventory_hint" {
  description = "IP para usar no inventory.ini do Ansible"
  value       = "jenkins ansible_host=${aws_eip.jenkins.public_ip} ansible_user=ubuntu ansible_ssh_private_key_file=~/.ssh/hands-on-satubinha-key.pem"
}

output "ecr_repository_url" {
  description = "URL do repositorio ECR — usar no docker push e no Ansible"
  value       = aws_ecr_repository.jenkins.repository_url
}

output "ecr_registry" {
  description = "Registry ECR (sem o nome do repositorio) — usar no docker login"
  value       = "${var.aws_account_id}.dkr.ecr.${var.aws_region}.amazonaws.com"
}

output "cosign_secret_arn" {
  description = "ARN do secret Cosign no Secrets Manager"
  value       = aws_secretsmanager_secret.cosign_private_key.arn
}

output "setup_cosign_hint" {
  description = "Comando para popular o secret apos gerar o par de chaves Cosign"
  value       = "aws secretsmanager put-secret-value --secret-id ${aws_secretsmanager_secret.cosign_private_key.name} --secret-string file://cosign.key"
}
