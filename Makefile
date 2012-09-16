WD := $(shell pwd)
VENV := $(WD)/venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

# Build
.PHONY: build_all
build_all: clean_dist clean_build build_sdist build_bdist

.PHONY: clean_dist
clean_dist:
	rm -rf $(WD)/dist

.PHONY: clean_build
clean_build:
	rm -rf $(WD)/*.egg-info
	rm -rf $(WD)/build

.PHONY: build_sdist
build_sdist:
	$(PY) setup.py sdist

.PHONY: build_bdist
build_bdist:
	$(PY) setup.py bdist
	rm -rf $(WD)/*.egg-info
