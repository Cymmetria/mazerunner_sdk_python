SHELL := /bin/bash

.PHONY: dev-env
dev-env:
	sudo apt-get install -y texlive-latex-extra texlive-fonts-recommended python-sphinx; \
	virtualenv .sdk; \
	source .sdk/bin/activate; \
	pip install -r requirements.txt; \
	pip install -r testing_requirements.txt;

.PHONY: docs
docs: export PYTHONPATH = $(shell pwd):$(shell pwd)/mazerunner:$(shell pwd)/mazerunner/samples
docs:
	source .sdk/bin/activate; \
	make -f sphinx_makefile html latexpdf
	cp build/latex/MazeRunnerSDK.pdf build/html/sdk.pdf
