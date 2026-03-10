provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "opentofu"
      Owner       = var.developer_email
    }
  }
}

provider "cloudflare" {
  # API token set via CLOUDFLARE_API_TOKEN env var
}
