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
# Firmware is refused, published versions are immutable, and the index is
# verified against the committed public key before it is uploaded.
set -eu
apk -q add abuild >/dev/null

pkginfo() { tar -xzOf "$1" .PKGINFO 2>/dev/null | sed -n "s/^$2 = //p" | head -n1; }
unpublished() { case " ${UNPUBLISHED:-} " in *" $1 "*) return 0 ;; esac; return 1; }

cd /repo
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
for apk in /new/*.apk; do
	[ -e "$apk" ] || continue
	name=$(pkginfo "$apk" pkgname)
	origin=$(pkginfo "$apk" origin)
	file=$(basename "$apk")
	case "$name $origin" in
	firmware-*|*" firmware-"*)
		echo "REFUSED $file: firmware is never published" >&2; exit 1 ;;
	esac
	if tar -tzf "$apk" 2>/dev/null | grep -qE '^(usr/)?lib/firmware/'; then
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
		echo "keep $file (already published; versions are immutable)"
		continue
	fi
	for old in "$name"-[0-9]*.apk; do
		[ -e "$old" ] || continue
		[ "$(pkginfo "$old" pkgname)" = "$name" ] || continue
		echo "drop $old (superseded by $file)"
		echo "$old" >> .remove
		rm -f "$old"
	done
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
abuild-sign -q -k "/keys/$KEY" -p "$KEY.pub" APKINDEX.tar.gz
mkdir -p /tmp/trusted
cp "/pubkeys/$KEY.pub" /tmp/trusted/
apk verify --keys-dir /tmp/trusted APKINDEX.tar.gz
echo APKINDEX.tar.gz >> .upload
