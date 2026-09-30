#!/bin/sh
# publish-repo.sh -- merge new apks into one apk repository directory, then
# index and sign it. Runs as root in an Alpine container:
#   /repo      the release's current *.apk (read-write; the result lands here)
#   /new       freshly built *.apk for this repository (read-only)
#   /keys/KEY  the private repository key, KEY named like its public half
#   /pubkeys   .github/keys (read-only; the public key to verify against)
# Env: ARCH, KEY (e.g. porthole-dev-packages-20260915.rsa), PACKAGER,
#      DESCRIPTION, UNPUBLISHED (origins that are built but never published),
#      REINDEX (non-empty: write and sign the index even if no package changed,
#      which with no packages at all gives an empty index).
# Writes /repo/.upload (files to upload) and /repo/.remove (assets to delete).
#
# Firmware stays refused until the Taimen grant gate is explicitly enabled.
# Published versions are immutable, and the index is verified before upload.
set -eu
REPO_DIR=${REPO_DIR:-/repo}
NEW_DIR=${NEW_DIR:-/new}
KEYS_DIR=${KEYS_DIR:-/keys}
PUBKEYS_DIR=${PUBKEYS_DIR:-/pubkeys}
TRUSTED_DIR=${TRUSTED_DIR:-/tmp/trusted}
apk -q add abuild >/dev/null

pkginfo() { tar -xzOf "$1" .PKGINFO 2>/dev/null | sed -n "s/^$2 = //p" | head -n1; }
unpublished() { case " ${UNPUBLISHED:-} " in *" $1 "*) return 0 ;; esac; return 1; }
taimen_firmware_approved() {
	[ "${FIRMWARE_GRANT_TAIMEN:-}" = approved ] &&
	[ "$origin" = firmware-google-taimen ] &&
	{ [ "$name" = firmware-google-taimen ] ||
	  [ "$name" = firmware-google-taimen-fingerprint ]; }
}

cd "$REPO_DIR"
: > .upload
: > .remove
for old in ./*.apk; do
	[ -e "$old" ] || continue
	if unpublished "$(pkginfo "$old" origin)"; then
		echo "drop ${old#./} (its origin is never published, see packages.conf)"
		echo "${old#./}" >> .remove
		rm -f "$old"
	fi
done
for apk in "$NEW_DIR"/*.apk; do
	[ -e "$apk" ] || continue
	# Native verification catches corrupt payloads that apk index does not read.
	apk verify --allow-untrusted "$apk"
	name=$(pkginfo "$apk" pkgname)
	origin=$(pkginfo "$apk" origin)
	file=$(basename "$apk")
	case "$name $origin" in
	firmware-*|*" firmware-"*)
		if ! taimen_firmware_approved; then
			echo "REFUSED $file: firmware grant not enabled" >&2; exit 1
		fi ;;
	esac
	if tar -tzf "$apk" 2>/dev/null | grep -qE '^(usr/)?lib/firmware/' &&
	   ! taimen_firmware_approved; then
		echo "REFUSED $file: ships files under lib/firmware" >&2; exit 1
	fi
	if unpublished "$origin"; then
		echo "skip $file (its origin is never published, see packages.conf)"
		continue
	fi
	if [ "$(pkginfo "$apk" packager)" != "$PACKAGER" ]; then
		echo "REFUSED $file: packager is not the configured PACKAGER" >&2; exit 1
	fi
	if [ -e "$file" ]; then
		if ! cmp -s "$file" "$apk"; then
			echo "REFUSED $file: published version has different bytes; bump pkgrel" >&2
			exit 1
		fi
		echo "keep $file (identical published bytes)"
		continue
	fi
	# Cached indexes and retained image snapshots still reference older APKs.
	# Keep them until an explicit retention review proves no snapshot needs them.
	cp "$apk" .
	echo "add  $file"
	echo "$file" >> .upload
done

if [ ! -s .upload ] && [ ! -s .remove ] && [ -z "${REINDEX:-}" ]; then
	echo "nothing new"
	exit 0
fi

rm -f APKINDEX.tar.gz
set -- ./*.apk
[ -e "$1" ] || set --
echo "index $# package(s) for $ARCH"
apk index -q --allow-untrusted --rewrite-arch "$ARCH" --description "$DESCRIPTION" \
	--output APKINDEX.tar.gz "$@"
abuild-sign -q -k "$KEYS_DIR/$KEY" -p "$KEY.pub" APKINDEX.tar.gz
mkdir -p "$TRUSTED_DIR"
cp "$PUBKEYS_DIR/$KEY.pub" "$TRUSTED_DIR/"
apk verify --keys-dir "$TRUSTED_DIR" APKINDEX.tar.gz
echo APKINDEX.tar.gz >> .upload
