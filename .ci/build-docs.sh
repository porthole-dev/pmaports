#!/bin/sh -e
# Copyright 2025 Pablo Correa Gomez
# SPDX-License-Identifier: GPL-3.0-or-later
# Description: create documentation with sphinx
# Options: with-dot-git
# Artifacts: build/site
# https://postmarketos.org/pmb-ci


# Install dependencies
if [ "$(id -u)" = 0 ]; then
	set -x
	apk -q add git nodejs npm
	exec su "${TESTUSER:-build}" -c "sh -e $0"
fi

npm install antora
npx antora -v

# FIXME: https://gitlab.com/antora/antora/-/issues/1183
git clone --depth 1 https://gitlab.postmarketos.org/postmarketOS/handbook
npx antora --clean antora-test.yml
