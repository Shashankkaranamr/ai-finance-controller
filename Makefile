# Real entrypoint is `python -m recon` -- this forwards to it so reviewers
# on mac/Linux get the `make demo` the README promises.
SEED ?= dev

demo:
	python -m recon demo --seed $(SEED)

test:
	pytest

.PHONY: demo test
