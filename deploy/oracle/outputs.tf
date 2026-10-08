output "server_ip" {
  description = "The server's public IP address. It stays the same across restarts."
  value       = oci_core_public_ip.spinet.ip_address
}

output "app_server_address" {
  description = "Enter this in Spinet under Settings → My Server → Host."
  value = (
    local.https ? "https://${local.hostname}" :
    "http://${oci_core_public_ip.spinet.ip_address}:8091"
  )
}

output "next_steps" {
  value = join(" ", compact([
    "The server finishes setting itself up about 5 minutes after this job ends.",
    local.mode_domain ? "Now add an A record for ${local.hostname} pointing at ${oci_core_public_ip.spinet.ip_address}; HTTPS starts working once it resolves." : "",
    "Then enter the app server address in Spinet under Settings → My Server.",
    "Keep that address private: the server has no password.",
  ]))
}

output "ssh_command" {
  description = "To connect later (only if you gave an SSH key)."
  value       = "ssh ubuntu@${oci_core_public_ip.spinet.ip_address}"
}
