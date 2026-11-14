SHELL := /usr/bin/env bash
.PHONY: candidate static s3 postgres mariadb ops qemu perf release

candidate:
	bash ./tools/materialize-candidate.sh
static:
	bash ./tests/static.sh
s3:
	sudo bash ./tests/s3-roundtrip.sh
postgres:
	sudo bash ./tests/postgres-roundtrip.sh
mariadb:
	sudo bash ./tests/mariadb-roundtrip.sh
ops:
	sudo bash ./tests/ops-integrations.sh
qemu:
	sudo bash ./tests/recovery-image-qemu.sh
perf:
	sudo SIZE_MIB=256 SMALL_FILES=10000 bash ./tests/performance.sh
release:
	bash ./tools/package-release.sh
