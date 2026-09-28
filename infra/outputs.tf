output "public_ip" {
  description = "Public IPv4 address of the POC server."
  value       = hcloud_server.poc.ipv4_address
}

output "api_url" {
  description = "FastAPI URL."
  value       = "http://${hcloud_server.poc.ipv4_address}:8000"
}

output "tusd_url" {
  description = "tusd upload URL."
  value       = "http://${hcloud_server.poc.ipv4_address}:8081/files/"
}
