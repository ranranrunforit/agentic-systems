# project-303-extensible-agent-platform
#
# Everything runs offline with a bare CPython 3.11+ install. PyYAML is used when
# present and a bundled fallback parser is used when it is not.

PY ?= python3

.PHONY: help test test-portability demo triage injection containment governance portability \
        glue list audit yaml-check lint clean

help:
	@echo "make test            run the acceptance-criteria test suite (63 tests)"
	@echo "make demo            run all five demos end to end"
	@echo "make triage          demo 1: the happy path"
	@echo "make injection       demo 2: prompt-injection red team"
	@echo "make containment     demo 3: rogue extension containment"
	@echo "make governance      demo 4: permission diff, kill-switch, rotation"
	@echo "make portability     demo 5: the same contract on a second host"
	@echo "make glue            measure host-specific vs portable lines"
	@echo "make list            inspect loaded extensions and their permissions"
	@echo "make audit           show an audit trail"
	@echo "make yaml-check      verify the bundled fallback YAML parser matches PyYAML"

test:
	$(PY) -m unittest runtime.tests.test_platform runtime.tests.test_portability -v

test-portability:
	$(PY) -m unittest runtime.tests.test_portability -v

demo:
	$(PY) -m runtime.demos.run_all

triage:
	$(PY) -m runtime.demos.demo_triage

injection:
	$(PY) -m runtime.demos.demo_injection

containment:
	$(PY) -m runtime.demos.demo_containment

governance:
	$(PY) -m runtime.demos.demo_governance

portability:
	$(PY) -m runtime.demos.demo_portability

glue:
	$(PY) -m portability.bindings.measure_glue

list:
	$(PY) -m runtime.cli.ext list

audit:
	$(PY) -m runtime.cli.ext audit --name triage-agent --input '{"ticket_id":"T-1043"}' -n 30

yaml-check:
	$(PY) -m runtime.host.yamlio

lint:
	$(PY) -m compileall -q runtime portability >/dev/null && echo "compile ok"

clean:
	find . -name '__pycache__' -type d -prune -exec rm -rf {} + ; rm -f audit.jsonl
