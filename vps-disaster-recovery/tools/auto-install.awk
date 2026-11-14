# Engancha modules/auto-install.sh en el candidato: flags de `install`, opciones
# de linea de comandos aplicadas tras cargar config/borrador, token de Coolify
# automatico y defaults del modo automatico en la politica Docker. Cada
# reescritura debe ocurrir exactamente una vez (si no, sale con 58).
{
  line = $0
  if (line == "    install|setup) cmd_install \"$@\" ;;") { line = "    install|setup) install_parse_flags \"$@\" || exit 2; cmd_install ;;"; n[1]++ }
  if (line == "      choice=$(prompt_default \"Estrategia para $name\" \"$default_choice\")") { line = "      choice=$(prompt_default \"Estrategia para $name\" \"$(auto_sql_db_default \"$default_choice\")\")"; n[2]++ }
  if (line == "      choice=$(prompt_default \"Estrategia para $name\" \"1\")") { line = "      choice=$(prompt_default \"Estrategia para $name\" \"$(auto_nonsql_db_default \"$name\")\")"; n[3]++ }
  old = "COOLIFY_API_TOKEN=$(prompt_secret \"Coolify API token dedicado a DR\")"
  i = index(line, old)
  if (i > 0) {
    new = "COOLIFY_API_TOKEN=$(prompt_secret \"Coolify API token dedicado a DR (Enter = crear uno automáticamente)\"); [[ -n \"$COOLIFY_API_TOKEN\" ]] || COOLIFY_API_TOKEN=$(coolify_provision_api_token || true)"
    line = substr(line, 1, i - 1) new substr(line, i + length(old))
    n[4]++
  }
  print line
  if (line == "  install_draft_load") { print "  install_apply_flags"; n[5]++ }
}
END {
  for (k = 1; k <= 5; k++) if (n[k] != 1) { print "auto-install rewrite " k " matched " n[k] + 0 " times" > "/dev/stderr"; exit 58 }
}
