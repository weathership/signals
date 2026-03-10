output "bastion_public_ip" {
  value = aws_instance.bastion.public_ip
}

output "control_plane_private_ips" {
  value = aws_instance.control_plane[*].private_ip
}

output "worker_private_ips" {
  value = aws_instance.worker[*].private_ip
}

output "ssh_key_path" {
  value = local_file.ssh_private_key.filename
}

output "s3_bucket_name" {
  value = aws_s3_bucket.data.bucket
}

output "vpc_id" {
  value = aws_vpc.main.id
}
