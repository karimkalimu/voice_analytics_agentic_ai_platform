variable "location" {
  description = "Hetzner Cloud location for the POC server."
  type        = string
  default     = "nbg1"
}

variable "ssh_public_key_path" {
  description = "Local path to the public SSH key installed for root access."
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "ssh_source_ranges" {
  description = "Public IPv4 CIDRs permitted to reach SSH."
  type        = list(string)

  validation {
    condition     = length(var.ssh_source_ranges) > 0 && alltrue([for cidr in var.ssh_source_ranges : can(cidrhost(cidr, 0)) && !strcontains(cidr, ":") && cidr != "0.0.0.0/0"])
    error_message = "Use restricted IPv4 CIDRs; 0.0.0.0/0 is rejected."
  }
}

variable "application_source_ranges" {
  description = "Public IPv4 CIDRs permitted to reach FastAPI and tusd."
  type        = list(string)

  validation {
    condition     = length(var.application_source_ranges) > 0 && alltrue([for cidr in var.application_source_ranges : can(cidrhost(cidr, 0)) && !strcontains(cidr, ":") && cidr != "0.0.0.0/0"])
    error_message = "Use restricted IPv4 CIDRs; 0.0.0.0/0 is rejected."
  }
}

variable "repository_ref" {
  description = "Git branch, tag, or commit deployed to the server."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$", var.repository_ref)) && !strcontains(var.repository_ref, "..")
    error_message = "repository_ref must be a safe Git branch, tag, or commit name."
  }
}
