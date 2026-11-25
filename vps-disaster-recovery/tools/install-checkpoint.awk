# Inyecta los puntos de control del borrador del instalador dentro de
# configure_interactive (ver modules/install-checkpoint.sh). Solo actua entre
# "configure_interactive() {" y su "}" de cierre. Cada ancla debe aparecer
# exactamente una vez; si no, sale con 55 y el materializador falla.
function hit(i) { seen[i]++ }
{
  line = $0
  if (line == "configure_interactive() {") { inside = 1 }
  if (inside) {
    if (line == "  local detected_host default_id input") { print "  install_draft_load"; hit(1) }
    if (index(line, "printf '\\nModo de archivos:\\n'") > 0) { print "  install_checkpoint"; hit(3) }
    if (index(line, "printf '\\nPolítica de protección / costo:\\n'") > 0) { print "  install_checkpoint"; hit(4) }
    if (index(line, "printf '\\nMódulos detectados:\\n'") > 0) { print "  install_checkpoint"; hit(5) }
    if (index(line, "printf '\\nRetención Restic / frecuencia actual:\\n'") > 0) { print "  install_checkpoint"; hit(7) }
    if (line == "  if is_true \"$generated_password\"; then") {
      print "  restic_password=$(install_restic_password_to_show \"$restic_password\")"
      print "  if [[ -n \"$restic_password\" ]] && is_true \"${RESTIC_PASSWORD_UNSHOWN:-false}\"; then generated_password=\"true\"; fi"
      hit(8)
    }
  }
  print line
  if (inside) {
    if (index(line, "[[ -n \"$AWS_SECRET_ACCESS_KEY\" ]] || die \"Secret Key vacío.\"") > 0) { print "  install_checkpoint"; hit(2) }
    if (index(line, "[[ -n \"$COOLIFY_API_TOKEN\" ]] || die \"Coolify CLI DR requiere API token.\"") > 0) { print "        install_checkpoint"; hit(6) }
    if (line == "  atomic_finish \"$tmp_cred\" \"$CREDENTIALS_FILE\" 0600") { print "  install_draft_clear"; hit(9) }
    if (line == "}") { inside = 0 }
  }
}
END {
  for (i = 1; i <= 9; i++) if (seen[i] != 1) { print "install-checkpoint anchor " i " matched " seen[i] + 0 " times" > "/dev/stderr"; exit 55 }
}
