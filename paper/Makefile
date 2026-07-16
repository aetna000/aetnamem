PYTHON ?= python3
TECTONIC ?= tectonic

CONTROL_PLANE_SOURCES := main.tex references.bib $(wildcard sections/*.tex) $(wildcard figures/*.tex)
GOVERNED_MEMORY_SOURCES := \
	governed-memory.tex \
	governed-memory-references.bib \
	$(wildcard sections/governed-memory/*.tex) \
	$(wildcard figures/governed-memory-*.tex)
FIGURE_OUTPUTS := \
	figures/benchmark-scores.pdf \
	figures/benchmark-matrix.pdf \
	figures/auditability.pdf \
	figures/aetnamem-profile.pdf \
	figures/demo-trace.pdf

.NOTPARALLEL:

.PHONY: all figures verify clean

all: figures aetnamem-control-plane.pdf aetnamem-governed-memory.pdf

figures:
	$(PYTHON) scripts/generate_figures.py

build/aetnamem-control-plane.pdf: $(CONTROL_PLANE_SOURCES) $(FIGURE_OUTPUTS)
	mkdir -p build
	$(TECTONIC) -X compile main.tex --outdir build
	mv build/main.pdf $@

aetnamem-control-plane.pdf: build/aetnamem-control-plane.pdf
	cp $< $@

build/aetnamem-governed-memory.pdf: $(GOVERNED_MEMORY_SOURCES)
	mkdir -p build
	$(TECTONIC) -X compile governed-memory.tex --outdir build
	mv build/governed-memory.pdf $@

aetnamem-governed-memory.pdf: build/aetnamem-governed-memory.pdf
	cp $< $@

verify:
	$(PYTHON) scripts/validate_evidence.py

clean:
	rm -rf build aetnamem-control-plane.pdf aetnamem-governed-memory.pdf figures/*.pdf figures/*.png
