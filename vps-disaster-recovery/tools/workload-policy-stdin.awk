# configure_workload_policy recorre contenedores DB y volumenes con
# `while read ...; do <prompts>; done < <(lista)`. Esa redireccion tambien es la
# stdin de los prompts: "Estrategia para X" leia la linea siguiente de la lista
# (otro contenedor) en vez del teclado y abortaba con "Estrategia inválida".
# Se leen las listas por los descriptores 3 y 4 para que los prompts usen la
# terminal. Solo actua dentro de configure_workload_policy; cada sustitucion
# debe ocurrir exactamente una vez (si no, sale con 57).
{
  line = $0
  if (line == "configure_workload_policy() {") { inside = 1 }
  if (inside) {
    if (line == "  while IFS=$'\\t' read -r name image; do") { line = "  while IFS=$'\\t' read -r -u 3 name image; do"; n[1]++ }
    else if (line == "  done < <(docker_db_containers)") { line = "  done 3< <(docker_db_containers)"; n[2]++ }
    else if (line == "  while IFS= read -r vol; do") { line = "  while IFS= read -r -u 4 vol; do"; n[3]++ }
    else if (line == "  done < <(docker volume ls -q 2>/dev/null)") { line = "  done 4< <(docker volume ls -q 2>/dev/null)"; n[4]++ }
    if (line == "}") { inside = 0 }
  }
  print line
}
END {
  for (i = 1; i <= 4; i++) if (n[i] != 1) { print "workload-policy-stdin rewrite " i " matched " n[i] + 0 " times" > "/dev/stderr"; exit 57 }
}
