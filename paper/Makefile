PYTHON ?= python3
TECTONIC ?= tectonic

TEX_SOURCES := main.tex references.bib $(wildcard sections/*.tex) $(wildcard figures/*.tex)
FIGURE_OUTPUTS := \
	figures/benchmark-scores.pdf \
	figures/benchmark-matrix.pdf \
	figures/auditability.pdf \
	figures/aetnamem-profile.pdf \
	figures/demo-trace.pdf

.NOTPARALLEL:

.PHONY: all figures verify clean

all: figures aetnamem-control-plane.pdf

figures:
	$(PYTHON) scripts/generate_figures.py

build/aetnamem-control-plane.pdf: $(TEX_SOURCES) $(FIGURE_OUTPUTS)
	mkdir -p build
	$(TECTONIC) -X compile main.tex --outdir build
	mv build/main.pdf $@

aetnamem-control-plane.pdf: build/aetnamem-control-plane.pdf
	cp $< $@

verify:
	$(PYTHON) scripts/validate_evidence.py

clean:
	rm -rf build aetnamem-control-plane.pdf figures/*.pdf figures/*.png
