# Hetzner POC infrastructure

This Terraform deploys the POC to one Hetzner Cloud `cx23`: Ubuntu 24.04 x86_64, 2 shared vCPUs, 4 GB RAM, and 40 GB NVMe storage.

```mermaid
flowchart LR
    O["👤 Operator<br/>Terraform + SSH"]:::actor
    C["📱 Flutter client"]:::actor

    subgraph HC["☁️ Hetzner Cloud POC"]
        direction LR
        F["🛡️ Firewall<br/>Allowlisted IPs"]:::security

        subgraph VM["🖥️ Ubuntu 24.04 · cx23<br/>2 vCPU · 4 GB RAM"]
            direction TB
            T["📤 tusd<br/>Port 8081"]:::service
            A["⚙️ FastAPI<br/>Port 8000"]:::service
            D[("💾 SQLite<br/>Audio + transcripts")]:::data

            T -->|Private loopback hooks| A
            A --> D
        end

        F --> T
        F --> A
    end

    O -->|Terraform API and SSH 22| F
    C -->|TUS uploads| F
    C -->|API requests| F

    classDef actor fill:#eef2ff,stroke:#4f46e5,color:#111827,stroke-width:1.5px
    classDef security fill:#fff7ed,stroke:#ea580c,color:#111827,stroke-width:2px
    classDef service fill:#ecfdf5,stroke:#059669,color:#111827,stroke-width:1.5px
    classDef data fill:#fdf2f8,stroke:#db2777,color:#111827,stroke-width:1.5px
    style HC fill:#f8fafc,stroke:#64748b,stroke-width:1.5px
    style VM fill:#ffffff,stroke:#94a3b8,stroke-width:1.5px
```

Terraform creates one SSH key entry, one restricted firewall, and one server. Cloud-init clones the selected Git ref, runs `backend/ubuntu_setup.sh`, and installs disabled systemd services. Runtime credentials are copied after provisioning and never enter Terraform state.

## Deploy

Requirements: Terraform 1.6+, a Hetzner Cloud Read & Write API token, and an SSH key pair.

```sh
export HCLOUD_TOKEN='replace-with-your-token'
cd infra
cp terraform.tfvars.example terraform.tfvars
```

In `terraform.tfvars`, replace the documentation CIDR with the operator and demo client's public `/32` address. Pin `repository_ref` to the demo commit.

```sh
terraform init
terraform fmt -check
terraform validate
terraform plan -out=poc.tfplan
terraform apply poc.tfplan
```

State, saved plans, and `terraform.tfvars` are local and ignored by Git.

## Install runtime credentials

Create a filled backend environment file outside Git. Set `GOOGLE_APPLICATION_CREDENTIALS=/opt/voice-analytics/backend/firebase-service-account.json` and retain the service values from `backend/.env.example`.

```sh
SERVER_IP="$(terraform output -raw public_ip)"
ssh "root@$SERVER_IP" 'cloud-init status --wait'
scp /secure/path/backend.env "root@$SERVER_IP:/root/backend.env"
scp /secure/path/firebase-service-account.json "root@$SERVER_IP:/root/firebase-service-account.json"
ssh "root@$SERVER_IP" \
  'install -o voiceai -g voiceai -m 0600 /root/backend.env /opt/voice-analytics/backend/.env && install -o voiceai -g voiceai -m 0600 /root/firebase-service-account.json /opt/voice-analytics/backend/firebase-service-account.json && rm -f /root/backend.env /root/firebase-service-account.json && systemctl enable --now voice-analytics-api.service voice-analytics-tusd.service'
```

## Verify or destroy

```sh
curl "$(terraform output -raw api_url)/health"
ssh "root@$(terraform output -raw public_ip)" \
  'systemctl --no-pager status voice-analytics-api.service voice-analytics-tusd.service'
```

The POC uses HTTP and restricts access through `application_source_ranges`. Destroying the server also destroys its local data.

```sh
terraform destroy
```
