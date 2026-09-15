#!/bin/sh
# publish.sh PACKAGES -- publish built packages to the apk repositories that are
# releases of $PACKAGES_REPO, then verify what was published.
#
# PACKAGES holds pmbootstrap's local repositories, PACKAGES/<local>/aarch64/*.apk
# (edge -> tag <branch>/aarch64, systemd-edge -> systemd/<branch>/aarch64). It
# may be empty: every run still checks both trees.
#
# Each tree also gets an empty, signed x86_64 index: pmbootstrap on an x86_64
# host reads the mirror's index for the host architecture too, and aborts on a
# 404. aarch64 hosts are covered by the aarch64 index.
#
# Env: PACKAGES_REPO BRANCH ALPINE PACKAGER SIGNING_KEY SIGNING_KEY_NAME
#      UNPUBLISHED (origins built but never published, from packages.conf)
# Appends "sha256  <tag>/<file>" for every file uploaded to
# $RUNNER_TEMP/uploaded.sha256 (the subjects to attest).
set -eu
packages=$1
here=$(cd "$(dirname "$0")/.." && pwd)
work=$RUNNER_TEMP/publish
rm -rf "$work" "$RUNNER_TEMP/uploaded.sha256"
mkdir -p "$work"
keys=$work/keys
(umask 077; mkdir -p "$keys"; printf '%s\n' "$SIGNING_KEY" > "$keys/$SIGNING_KEY_NAME")
trap 'rm -rf "$keys"' EXIT

in_list() { case " $2 " in *" $1 "*) return 0 ;; esac; return 1; }

# index_origins FILE: the origin of every package an APKINDEX.tar.gz names
index_origins() { tar -xzOf "$1" APKINDEX 2>/dev/null | sed -n 's/^o://p' | sort -u; }

# publish TAG ARCH NEW: merge NEW/*.apk into release TAG and upload the result.
publish() {
	tag=$1 arch=$2 new=$3
	echo "::group::release $tag"
	repo=$work/repo/$tag check=$work/check/$tag
	mkdir -p "$repo" "$check"
	if ! gh release view "$tag" -R "$PACKAGES_REPO" >/dev/null 2>&1; then
		gh release create "$tag" -R "$PACKAGES_REPO" --title "$tag" --latest=false \
			--notes "apk repository for pmaports branch $BRANCH, $arch"
	fi
	gh release view "$tag" -R "$PACKAGES_REPO" --json assets --jq '.assets[].name' | sort > "$check/before"

	reindex=
	if ! grep -qx APKINDEX.tar.gz "$check/before"; then
		reindex=1
	else
		gh release download "$tag" -R "$PACKAGES_REPO" -p APKINDEX.tar.gz -D "$check" --clobber
		if ! docker run --rm -v "$check:/check:ro" -v "$here/keys:/pubkeys:ro" "$ALPINE" \
			apk verify --keys-dir /pubkeys /check/APKINDEX.tar.gz >/dev/null 2>&1; then
			echo "the published index does not verify against .github/keys: re-signing it"
			reindex=1
		fi
		for origin in $(index_origins "$check/APKINDEX.tar.gz"); do
			if in_list "$origin" "${UNPUBLISHED:-}"; then reindex=1; fi
		done
	fi
	if [ -z "$reindex" ] && ! ls "$new"/*.apk >/dev/null 2>&1; then
		echo "nothing new"
		echo "::endgroup::"
		return 0
	fi

	# The whole current repository: a failed or partial download must never
	# produce an index that silently drops published packages.
	want=$(grep -c '\.apk$' "$check/before" || true)
	if [ "$want" -gt 0 ]; then
		gh release download "$tag" -R "$PACKAGES_REPO" -p '*.apk' -D "$repo"
	fi
	have=$(find "$repo" -maxdepth 1 -name '*.apk' | wc -l)
	if [ "$have" -ne "$want" ]; then
		echo "::error::$tag: downloaded $have of $want published packages"
		exit 1
	fi

	# -i: the script arrives on stdin; without it the container reads an empty
	# script and exits 0 having published nothing.
	docker run -i --rm -v "$repo:/repo" -v "$new:/new:ro" \
		-v "$keys:/keys:ro" -v "$here/keys:/pubkeys:ro" \
		-e ARCH="$arch" -e KEY="$SIGNING_KEY_NAME" -e PACKAGER -e UNPUBLISHED \
		-e REINDEX="$reindex" -e DESCRIPTION="$PACKAGES_REPO $tag" \
		"$ALPINE" sh -s < "$here/scripts/publish-repo.sh"
	# publish-repo.sh always writes .upload (empty when nothing changed).
	if [ ! -f "$repo/.upload" ]; then
		echo "::error::publish-repo.sh did not run for $tag"
		exit 1
	fi
	if [ ! -s "$repo/.upload" ]; then
		echo "::endgroup::"
		return 0
	fi

	# New packages, then the index, then remove superseded packages: the
	# published index never names a missing file.
	(cd "$repo" && grep -vx APKINDEX.tar.gz .upload | xargs -r gh release upload "$tag" -R "$PACKAGES_REPO" --clobber)
	gh release upload "$tag" -R "$PACKAGES_REPO" --clobber "$repo/APKINDEX.tar.gz"
	xargs -r -n1 gh release delete-asset "$tag" -R "$PACKAGES_REPO" -y < "$repo/.remove"
	(cd "$repo" && xargs sha256sum < .upload) | sed "s|  |  $tag/|" >> "$RUNNER_TEMP/uploaded.sha256"

	# Verify what was published, not what was built.
	rm -f "$check/APKINDEX.tar.gz"
	gh release download "$tag" -R "$PACKAGES_REPO" -p APKINDEX.tar.gz -D "$check"
	cmp "$check/APKINDEX.tar.gz" "$repo/APKINDEX.tar.gz"
	docker run --rm -v "$check:/check:ro" -v "$here/keys:/pubkeys:ro" "$ALPINE" \
		apk verify --keys-dir /pubkeys /check/APKINDEX.tar.gz
	gh release view "$tag" -R "$PACKAGES_REPO" --json assets --jq '.assets[].name' | sort > "$check/assets"
	tar -xzOf "$check/APKINDEX.tar.gz" APKINDEX 2>/dev/null |
		awk -F: '/^P:/ { p = $2 } /^V:/ { print p "-" $2 ".apk" }' | sort > "$check/indexed"
	if comm -23 "$check/indexed" "$check/assets" | grep .; then
		echo "::error::$tag: the index names packages that are not release assets"
		exit 1
	fi
	for origin in $(index_origins "$check/APKINDEX.tar.gz"); do
		if in_list "$origin" "${UNPUBLISHED:-}"; then
			echo "::error::$tag: the index still names $origin, which is never published"
			exit 1
		fi
	done
	echo "::endgroup::"
}

for tree in main systemd; do
	# Only pmbootstrap's local repository directories that exist contribute.
	new=$work/new/$tree
	mkdir -p "$new"
	for dir in "$packages"/*/aarch64; do
		[ -d "$dir" ] || continue
		local_repo=$(basename "$(dirname "$dir")")
		case "$local_repo" in systemd-*) t=systemd ;; *) t=main ;; esac
		[ "$t" = "$tree" ] || continue
		for apk in "$dir"/*.apk; do
			if [ -e "$apk" ]; then cp "$apk" "$new/"; fi
		done
	done
	prefix=
	if [ "$tree" = systemd ]; then prefix=systemd/; fi
	publish "$prefix$BRANCH/aarch64" aarch64 "$new"
	mkdir -p "$work/new/empty"
	publish "$prefix$BRANCH/x86_64" x86_64 "$work/new/empty"
done
