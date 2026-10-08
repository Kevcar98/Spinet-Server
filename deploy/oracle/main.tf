locals {
  mode_duckdns = var.setup_mode == "HTTPS with a free DuckDNS name"
  mode_domain  = var.setup_mode == "HTTPS with my own domain"
  https        = local.mode_duckdns || local.mode_domain

  hostname = (
    local.mode_duckdns ? "${trimspace(lower(var.duckdns_subdomain))}.duckdns.org" :
    local.mode_domain ? trimspace(lower(var.domain)) :
    ""
  )

  flex = length(regexall("Flex$", var.shape)) > 0

  # Ports the outside world may reach: SSH always, then the web ports for
  # HTTPS (80 is how the certificate is issued) or the library port for HTTP.
  open_ports = local.https ? [22, 80, 443] : [22, 8091]

  availability_domain = (
    var.availability_domain != "" ? var.availability_domain :
    data.oci_identity_availability_domains.all.availability_domains[0].name
  )
}

data "oci_identity_availability_domains" "all" {
  compartment_id = var.tenancy_ocid
}

# The newest Ubuntu 22.04 image that runs on the chosen shape (ARM or x86).
data "oci_core_images" "ubuntu" {
  compartment_id           = var.compartment_ocid
  operating_system         = "Canonical Ubuntu"
  operating_system_version = "22.04"
  shape                    = var.shape
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"
}

# ---- Network ----------------------------------------------------------------

resource "oci_core_vcn" "spinet" {
  compartment_id = var.compartment_ocid
  cidr_blocks    = ["10.0.0.0/16"]
  display_name   = "spinet-vcn"
  dns_label      = "spinet"
}

resource "oci_core_internet_gateway" "spinet" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.spinet.id
  display_name   = "spinet-internet"
  enabled        = true
}

resource "oci_core_route_table" "spinet" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.spinet.id
  display_name   = "spinet-routes"

  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.spinet.id
  }
}

resource "oci_core_security_list" "spinet" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.spinet.id
  display_name   = "spinet-firewall"

  egress_security_rules {
    destination = "0.0.0.0/0"
    protocol    = "all"
  }

  dynamic "ingress_security_rules" {
    for_each = local.open_ports
    content {
      source   = "0.0.0.0/0"
      protocol = "6" # TCP
      tcp_options {
        min = ingress_security_rules.value
        max = ingress_security_rules.value
      }
    }
  }

  # Path MTU discovery: without it some large responses stall.
  ingress_security_rules {
    source   = "0.0.0.0/0"
    protocol = "1" # ICMP
    icmp_options {
      type = 3
      code = 4
    }
  }
}

resource "oci_core_subnet" "spinet" {
  compartment_id             = var.compartment_ocid
  vcn_id                     = oci_core_vcn.spinet.id
  cidr_block                 = "10.0.0.0/24"
  display_name               = "spinet-subnet"
  dns_label                  = "server"
  route_table_id             = oci_core_route_table.spinet.id
  security_list_ids          = [oci_core_security_list.spinet.id]
  prohibit_public_ip_on_vnic = false
}

# ---- Server -----------------------------------------------------------------

resource "oci_core_instance" "spinet" {
  compartment_id      = var.compartment_ocid
  availability_domain = local.availability_domain
  display_name        = "spinet-server"
  shape               = var.shape

  dynamic "shape_config" {
    for_each = local.flex ? [1] : []
    content {
      ocpus         = var.ocpus
      memory_in_gbs = var.memory_in_gbs
    }
  }

  source_details {
    source_type             = "image"
    source_id               = data.oci_core_images.ubuntu.images[0].id
    boot_volume_size_in_gbs = 50
  }

  # The public address is a reserved one, attached below, so it survives
  # restarts; the instance gets none of its own.
  create_vnic_details {
    subnet_id        = oci_core_subnet.spinet.id
    assign_public_ip = false
    hostname_label   = "spinet"
  }

  metadata = merge(
    {
      user_data = base64encode(templatefile("${path.module}/setup.sh.tftpl", {
        repo_url          = var.repo_url
        https             = local.https
        hostname          = local.hostname
        duckdns_subdomain = local.mode_duckdns ? trimspace(lower(var.duckdns_subdomain)) : ""
        duckdns_token     = local.mode_duckdns ? trimspace(var.duckdns_token) : ""
      }))
    },
    trimspace(var.ssh_public_key) != "" ? { ssh_authorized_keys = trimspace(var.ssh_public_key) } : {}
  )

  lifecycle {
    precondition {
      condition     = !local.mode_duckdns || (trimspace(var.duckdns_subdomain) != "" && trimspace(var.duckdns_token) != "")
      error_message = "DuckDNS needs both your DuckDNS name and your token."
    }
    precondition {
      condition     = !local.mode_domain || length(regexall("^[a-z0-9.-]+\\.[a-z]{2,}$", local.hostname)) > 0
      error_message = "Enter your domain's full hostname, e.g. library.example.com."
    }
    # A new image or setup script later must not rebuild a running server.
    ignore_changes = [source_details[0].source_id, metadata]
  }
}

# ---- Reserved public IP -----------------------------------------------------

data "oci_core_vnic_attachments" "spinet" {
  compartment_id = var.compartment_ocid
  instance_id    = oci_core_instance.spinet.id
}

data "oci_core_private_ips" "spinet" {
  vnic_id = data.oci_core_vnic_attachments.spinet.vnic_attachments[0].vnic_id
}

resource "oci_core_public_ip" "spinet" {
  compartment_id = var.compartment_ocid
  lifetime       = "RESERVED"
  display_name   = "spinet-ip"
  private_ip_id  = data.oci_core_private_ips.spinet.private_ips[0].id
}
