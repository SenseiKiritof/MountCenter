VERSION := 0.1.0
PREFIX ?= /usr/local
DESTDIR ?=

.PHONY: all install test check-version dist rpm

all:
	@echo "Targets: install [DESTDIR=…] [PREFIX=…], test, check-version, dist, rpm"

install:
	PREFIX="$(PREFIX)" DESTDIR="$(DESTDIR)" ./install.sh

test:
	python3 -m unittest discover -s tests -v

check-version:
	@v=$$(sed -n 's/^__version__ = "\(.*\)"/\1/p' mountcenter/__init__.py); \
	test "$$v" = "$(VERSION)" || { echo "VERSION $(VERSION) ≠ __version__ $$v"; exit 1; }
	@grep -q "^Version: *$(VERSION)$$" packaging/mountcenter.spec

# Tarball from the current commit (HEAD): packages are built from what is versioned.
dist: check-version
	mkdir -p dist
	git archive --format=tar.gz --prefix=mountcenter-$(VERSION)/ \
		-o dist/mountcenter-$(VERSION).tar.gz HEAD

rpm: dist
	rpmdev-setuptree
	cp dist/mountcenter-$(VERSION).tar.gz "$$HOME/rpmbuild/SOURCES/"
	rpmbuild -bb packaging/mountcenter.spec
	cp "$$HOME"/rpmbuild/RPMS/noarch/mountcenter-$(VERSION)-*.rpm dist/
	ls -1 dist/
