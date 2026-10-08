# Filled in by Resource Manager from where the stack is created.
variable "tenancy_ocid" {}
variable "region" {}
variable "compartment_ocid" {}

variable "setup_mode" {
  description = "How the apps reach the server."
  type        = string
  default     = "HTTPS with a free DuckDNS name"
  validation {
    condition = contains([
      "HTTPS with a free DuckDNS name",
      "HTTPS with my own domain",
      "Plain HTTP with the IP address only",
    ], var.setup_mode)
    error_message = "Pick one of the listed setups."
  }
}

variable "duckdns_subdomain" {
  description = "The DuckDNS name you created, without .duckdns.org (e.g. spinet-kev)."
  type        = string
  default     = ""
}

variable "duckdns_token" {
  description = "Your DuckDNS token, shown at the top of duckdns.org once signed in."
  type        = string
  default     = ""
  sensitive   = true
}

variable "domain" {
  description = "The full hostname of your own domain (e.g. library.example.com)."
  type        = string
  default     = ""
}

variable "availability_domain" {
  description = "Where the server runs. Leave empty for the first one."
  type        = string
  default     = ""
}

variable "shape" {
  description = "The Always Free server type."
  type        = string
  default     = "VM.Standard.A1.Flex"
}

variable "ocpus" {
  description = "Processors for the Ampere shape. Always Free covers up to 4 in total."
  type        = number
  default     = 1
}

variable "memory_in_gbs" {
  description = "Memory for the Ampere shape. Always Free covers up to 24 GB in total."
  type        = number
  default     = 6
}

variable "ssh_public_key" {
  description = "Optional: a public SSH key, to connect later and update the server."
  type        = string
  default     = ""
}

variable "repo_url" {
  description = "Where the server's code is fetched from."
  type        = string
  default     = "https://github.com/Kevcar98/Spinet-Server.git"
}
