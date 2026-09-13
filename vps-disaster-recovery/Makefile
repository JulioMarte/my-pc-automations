SHELL := /usr/bin/env bash
.PHONY: candidate static s3 postgres perf
candidate:
	./tools/materialize-candidate.sh
static:
	./tests/static.sh
s3:
	sudo ./tests/s3-roundtrip.sh
postgres:
	sudo ./tests/postgres-roundtrip.sh
perf:
	sudo ./tests/performance.sh
