resource "hcloud_ssh_key" "operator" {
  name       = "voice-analytics-poc"
  public_key = file(pathexpand(var.ssh_public_key_path))
}

resource "hcloud_firewall" "poc" {
  name = "voice-analytics-poc"

  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "22"
    source_ips = var.ssh_source_ranges
  }

  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "8000"
    source_ips = var.application_source_ranges
  }

  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "8081"
    source_ips = var.application_source_ranges
  }
}

resource "hcloud_server" "poc" {
  name         = "voice-analytics-poc"
  location     = var.location
  image        = "ubuntu-24.04"
  server_type  = "cx23"
  ssh_keys     = [hcloud_ssh_key.operator.id]
  firewall_ids = [hcloud_firewall.poc.id]
  user_data = templatefile("${path.module}/startup.sh.tftpl", {
    repository_ref = var.repository_ref
  })

  public_net {
    ipv4_enabled = true
    ipv6_enabled = false
  }
}
