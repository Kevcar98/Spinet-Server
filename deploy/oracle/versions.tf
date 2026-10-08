terraform {
  required_version = ">= 1.2"
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = ">= 5.0.0"
    }
  }
}

# Resource Manager fills in the region and credentials of whoever deploys.
provider "oci" {
  region = var.region
}
