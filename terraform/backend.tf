terraform {
  backend "s3" {
    bucket       = "hands-on-satubinha-tfstate"
    key          = "jenkins/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
