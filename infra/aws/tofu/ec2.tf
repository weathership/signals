# ── AMI ──────────────────────────────────────────────────────────────────────

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# ── SSH Key ──────────────────────────────────────────────────────────────────

resource "tls_private_key" "ssh" {
  algorithm = "ED25519"
}

resource "aws_key_pair" "main" {
  key_name   = "${var.project}-key"
  public_key = tls_private_key.ssh.public_key_openssh
}

resource "local_file" "ssh_private_key" {
  content         = tls_private_key.ssh.private_key_openssh
  filename        = "${path.module}/.ssh/${var.project}.pem"
  file_permission = "0600"
}

# ── Bastion Host ─────────────────────────────────────────────────────────────

resource "aws_instance" "bastion" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = "t3.small"
  key_name               = aws_key_pair.main.key_name
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.bastion.id]

  root_block_device {
    volume_size = 30
    encrypted   = true
  }

  tags = { Name = "${var.project}-bastion" }
}

# ── Control Plane ────────────────────────────────────────────────────────────

resource "aws_instance" "control_plane" {
  count                  = var.control_plane_count
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.control_plane_instance_type
  key_name               = aws_key_pair.main.key_name
  subnet_id              = aws_subnet.private.id
  vpc_security_group_ids = [aws_security_group.rke2.id]

  root_block_device {
    volume_size = var.root_volume_size
    encrypted   = true
  }

  tags = { Name = "${var.project}-cp-${count.index}" }
}

# ── Workers ──────────────────────────────────────────────────────────────────

resource "aws_instance" "worker" {
  count                  = var.worker_count
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.worker_instance_type
  key_name               = aws_key_pair.main.key_name
  subnet_id              = aws_subnet.private.id
  vpc_security_group_ids = [aws_security_group.rke2.id]

  root_block_device {
    volume_size = var.root_volume_size
    encrypted   = true
  }

  ebs_block_device {
    device_name = "/dev/sdf"
    volume_size = var.data_volume_size
    encrypted   = true
  }

  tags = { Name = "${var.project}-worker-${count.index}" }
}
