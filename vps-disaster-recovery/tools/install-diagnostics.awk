# Engancha modules/install-diagnostics.sh en el candidato:
# - elimina initialize_repository_interactive del base (lo reemplaza el modulo);
# - install y reconfigure abren/cierran el log de instalacion;
# - la contrasena Restic generada se imprime solo en la terminal original
#   (fd $INSTALL_TTY_FD), nunca en el log.
# Debe correr despues de tools/auto-install.awk. Cada reescritura debe ocurrir
# exactamente una vez (si no, sale con 60).
/^initialize_repository_interactive\(\) \{$/ { skip = 1; n[1]++; next }
skip { if ($0 == "}") skip = 0; next }
{
  line = $0
  if (line == "configure_interactive() {") inside = 1
  if (line == "    install|setup) install_parse_flags \"$@\" || exit 2; cmd_install ;;") {
    line = "    install|setup) install_parse_flags \"$@\" || exit 2; install_trace_begin install \"$@\"; cmd_install; install_trace_end ;;"; n[2]++
  }
  if (line == "    reconfigure|configure) cmd_reconfigure \"$@\" ;;") {
    line = "    reconfigure|configure) install_trace_begin reconfigure \"$@\"; cmd_reconfigure \"$@\"; install_trace_end ;;"; n[3]++
  }
  if (inside && line == "  if is_true \"$generated_password\"; then") { inpw = 1 }
  else if (inpw && line == "  fi") { inpw = 0 }
  else if (inpw && line ~ /^    printf /) { line = line " >&\"$INSTALL_TTY_FD\""; n[4]++ }
  if (inside && line == "}") inside = 0
  print line
}
END {
  if (n[4] == 4) n[4] = 1
  for (k = 1; k <= 4; k++) if (n[k] != 1) { print "install-diagnostics rewrite " k " matched " n[k] + 0 " times" > "/dev/stderr"; exit 60 }
}
