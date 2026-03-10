# ── Bastion Security Group ────────────────────────────────────────────────────

resource "aws_security_group" "bastion" {
  name_prefix = "${var.project}-bastion-"
  vpc_id      = aws_vpc.main.id
  description = "Bastion host - SSH from allowed CIDRs"

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = var.allowed_ssh_cidrs
    description = "SSH from WARP"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-bastion-sg" }
}

# ── RKE2 Cluster Security Group ──────────────────────────────────────────────

resource "aws_security_group" "rke2" {
  name_prefix = "${var.project}-rke2-"
  vpc_id      = aws_vpc.main.id
  description = "RKE2 cluster internal communication"

  # Intra-cluster communication
  ingress {
    from_port = 0
    to_port   = 0
    protocol  = "-1"
    self      = true
    description = "All traffic within cluster"
  }

  # SSH from bastion
  ingress {
    from_port       = 22
    to_port         = 22
    protocol        = "tcp"
    security_groups = [aws_security_group.bastion.id]
    description     = "SSH from bastion"
  }

  # Kubernetes API from bastion
  ingress {
    from_port       = 6443
    to_port         = 6443
    protocol        = "tcp"
    security_groups = [aws_security_group.bastion.id]
    description     = "K8s API from bastion"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-rke2-sg" }
}
