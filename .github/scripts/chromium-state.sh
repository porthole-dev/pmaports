#!/bin/bash
# chromium-state.sh -- the stored state of the staged chromium build
# (.github/workflows/chromium.yml, design in .github/CHROMIUM.md).
#
#   chromium-state.sh tag RUNNER          name of the state for this checkout
#   chromium-state.sh manifest TAG        print its manifest ({} when none)
#   chromium-state.sh restore TAG WORK    rebuild the work directory from it
#   chromium-state.sh save TAG WORK       store what WORK/chromium/result.json
#                                         describes, then commit the manifest
#   chromium-state.sh delete TAG
#   chromium-state.sh prune TAG DAYS      delete other states idle for DAYS
#   chromium-state.sh ccache-restore ARCH WORK   unpack the compiler cache
#   chromium-state.sh ccache-save ARCH WORK      store it again
#
# A state is a draft release of this repository (drafts are only visible to
# people with write access). Its assets:
#   prep.tar.zst.NNN    the pmbootstrap work directory after prep: chroots,
#                       prepared source tree, gn gen output. Written once.
#   out-S.tar.zst.NNN   out/bld after stage S. Only the newest is kept.
#   state.json          the manifest: every part with its sha256, the ninja
#                       log record count, the stage history. Uploaded last,
#                       so a stage that dies while uploading leaves the
#                       previous state intact.
# Parts are 1900 MiB (PART_SIZE, for tests), under the 2 GiB asset limit.
#
# The compiler cache is a state of its own, tagged chromium-ccache-<arch>:
# deliberately not keyed by pkgver, because a security bump changes few
# translation units and reusing the cache across versions is the whole point.
# It is restored before every stage and stored again after every build stage.
#
# Runs on the runner as a user with sudo (tar keeps the chroots' owners).
# Env: GH_TOKEN, GITHUB_REPOSITORY, GITHUB_SERVER_URL, GITHUB_RUN_ID.
set -euo pipefail

# Bump when the layout changes, or when something outside the key changes what
# a stored state means: every stored state becomes unusable.
#   2  USE_CCACHE=1 (packages.py): before it, prep baked cc_wrapper="" into
#      args.gn, so a state from then would keep building without ccache.
FORMAT=2
R=$GITHUB_REPOSITORY
TMP=${RUNNER_TEMP:-/tmp}/chromium-state
mkdir -p "$TMP"

retry() {
	local i
	for i in 1 2 3 4; do
		"$@" && return 0
		[ "$i" = 4 ] && return 1
		echo "retrying in $((i * 15)) s: $*" >&2
		sleep $((i * 15))
	done
}

manifest() {
	if ! gh release view "$1" -R "$R" --json tagName >/dev/null 2>&1; then
		echo '{}'
		return
	fi
	gh release download "$1" -R "$R" -p state.json -O - 2>/dev/null || echo '{}'
}

# the decompressed layer $2 (prep, out or ccache) of state $1, checked part by part
fetch_layer() {
	local part name sha
	jq -c ".$2.parts[]" "${3:-$TMP/manifest.json}" | while read -r part; do
		name=$(jq -r .name <<<"$part")
		sha=$(jq -r .sha256 <<<"$part")
		retry gh release download "$1" -R "$R" -p "$name" -O "$TMP/part" --clobber
		if ! echo "$sha  $TMP/part" | sha256sum -c --quiet >&2; then
			echo "::error::$name does not match the sha256 in the manifest" >&2
			exit 1
		fi
		cat "$TMP/part"
		rm -f "$TMP/part"
	done | zstd -dc
}

upload_part() {
	local sha
	sha=$(sha256sum "$1" | cut -d' ' -f1)
	retry gh release upload "$TAG" "$1" -R "$R" --clobber >&2
	jq -cn --arg name "${1##*/}" --arg sha "$sha" --argjson bytes "$(stat -c %s "$1")" \
		'{name: $name, sha256: $sha, bytes: $bytes}' >> "$PARTS"
	rm -f "$1"
}

# tar ARGS... | compress | upload as NAME.tar.zst.NNN; prints the parts JSON
store_layer() {
	local name=$1
	shift
	PARTS=$TMP/$name.parts
	: > "$PARTS"
	export TAG PARTS R
	export -f upload_part retry
	# shellcheck disable=SC2016 # $FILE is expanded by split's filter shell
	sudo tar --format=posix --numeric-owner -cpf - "$@" |
		zstd -T0 -3 -q |
		SHELL=/bin/bash split -b "${PART_SIZE:-1900M}" -d -a 3 --filter='cat > "$FILE" && upload_part "$FILE"' - "$TMP/$name.tar.zst."
	jq -s '{parts: ., bytes: (map(.bytes) | add)}' "$PARTS"
}

ninja_records() {
	{ sudo cat "$1/.ninja_log" 2>/dev/null || true; } | awk -F'\t' 'NF == 5 { print $4 }' | sort -u | wc -l
}

cmd=${1:-}
case "$cmd" in
tag)
	runner=$2
	ver=$(sed -n 's/^pkgver=//p' temp/chromium/APKBUILD)-r$(sed -n 's/^pkgrel=//p' temp/chromium/APKBUILD)
	arch=$(case "$runner" in *-arm) echo aarch64 ;; *) echo x86_64 ;; esac)
	key=$(printf '%s\n' "$FORMAT" "$runner" \
		"$(git rev-parse HEAD:temp/chromium)" \
		"$(git rev-parse HEAD:.github/pmbootstrap-patches)" \
		"$(git rev-parse HEAD:.github/scripts/run-pmbootstrap.sh)" | sha256sum | cut -c1-12)
	echo "chromium-state-$ver-on-$arch-$key"
	;;
manifest)
	manifest "$2"
	;;
restore)
	TAG=$2 WORK=$3
	manifest "$TAG" > "$TMP/manifest.json"
	jq -e .prep "$TMP/manifest.json" >/dev/null || { echo "::error::$TAG has no prepared sources"; exit 1; }
	sudo mkdir -p "$WORK"
	fetch_layer "$TAG" prep | sudo tar -C "$WORK" --numeric-owner -xpf -
	out=$WORK/$(jq -r .out_dir "$TMP/manifest.json")
	if jq -e .out "$TMP/manifest.json" >/dev/null; then
		sudo rm -rf "$out"
		fetch_layer "$TAG" out | sudo tar -C "${out%/*}" --numeric-owner -xpf -
	fi
	want=$(jq .records "$TMP/manifest.json")
	have=$(ninja_records "$out")
	if [ "$have" != "$want" ]; then
		echo "::error::the restored ninja log has $have records, the manifest says $want"
		exit 1
	fi
	# The next result is this job's own.
	sudo rm -f "$WORK/chromium/result.json"
	echo "restored $TAG: stage $(jq .stage "$TMP/manifest.json"), $have ninja log records"
	;;
save)
	TAG=$2 WORK=$3
	result=$WORK/chromium/result.json
	manifest "$TAG" > "$TMP/manifest.json"
	gh release view "$TAG" -R "$R" --json tagName >/dev/null 2>&1 ||
		gh release create "$TAG" -R "$R" --draft --title "$TAG" \
			--notes "Stored state of the staged chromium build. Deleted once the package is published." >&2
	mode=$(jq -r .mode "$result")
	out_dir=$(jq -r .out_dir "$result")
	entry=$(jq -c --arg run "$GITHUB_SERVER_URL/$R/actions/runs/$GITHUB_RUN_ID" \
		'del(.ok, .out_dir) + {run: $run, at: (now | todate)}' "$result")
	if [ "$mode" = prep ]; then
		# Cache contents are rebuilt on demand; their directories keep their owners.
		layer=$(store_layer prep -C "$WORK" --exclude='./cache_*/*' --exclude=./log.txt .)
		jq --argjson layer "$layer" --arg out_dir "$out_dir" --argjson entry "$entry" \
			--argjson format "$FORMAT" --arg tag "$TAG" \
			'{format: $format, tag: $tag, prep: $layer, out_dir: $out_dir, stage: 0,
			  records: $entry.records_after, done: false, history: [$entry + {stage: 0}]}' \
			"$TMP/manifest.json" > "$TMP/new.json"
	else
		stage=$(($(jq .stage "$TMP/manifest.json") + 1))
		out=$WORK/$out_dir
		layer=$(store_layer "out-$stage" -C "${out%/*}" "${out##*/}")
		jq --argjson layer "$layer" --argjson entry "$entry" --argjson stage "$stage" \
			'.out = $layer | .stage = $stage | .records = $entry.records_after
			 | .done = $entry.done | .history += [$entry + {stage: $stage}]' \
			"$TMP/manifest.json" > "$TMP/new.json"
	fi
	cp "$TMP/new.json" "$TMP/state.json"
	retry gh release upload "$TAG" "$TMP/state.json" -R "$R" --clobber
	# The new manifest is committed: parts that only the old one named can go.
	jq -r '[.out.parts[]?.name] | .[]' "$TMP/manifest.json" | sort > "$TMP/old"
	jq -r '[.out.parts[]?.name, .prep.parts[]?.name] | .[]' "$TMP/new.json" | sort > "$TMP/new"
	comm -23 "$TMP/old" "$TMP/new" | while read -r name; do
		retry gh release delete-asset "$TAG" "$name" -R "$R" -y
	done
	jq '{stage, records, done, prep_bytes: .prep.bytes, out_bytes: .out.bytes, last: .history[-1]}' "$TMP/new.json"
	;;
ccache-restore)
	arch=$2 WORK=$3
	TAG=chromium-ccache-$arch
	dir=$WORK/cache_ccache_$arch
	sudo mkdir -p "$dir"
	manifest "$TAG" > "$TMP/ccache.json"
	if jq -e .ccache "$TMP/ccache.json" >/dev/null; then
		fetch_layer "$TAG" ccache "$TMP/ccache.json" | sudo tar -C "$dir" --numeric-owner -xpf -
		echo "restored $TAG: $(jq .ccache.bytes "$TMP/ccache.json") compressed bytes"
	else
		echo "no $TAG yet: the compiler cache starts empty"
	fi
	# ccache's own limit. pmbootstrap's default is 5G and it writes
	# ccache.conf only while it creates a chroot, which a restored stage
	# never does -- and this cache is the whole reason the next version's
	# build is cheap, so it is sized here and not left to chance.
	printf 'max_size = %s\n' "${CCACHE_MAX_SIZE:-6G}" | sudo tee "$dir/ccache.conf" >/dev/null
	;;
ccache-save)
	arch=$2 WORK=$3
	TAG=chromium-ccache-$arch
	dir=$WORK/cache_ccache_$arch
	[ -d "$dir" ] || { echo "::warning::no $dir to store"; exit 0; }
	gh release view "$TAG" -R "$R" --json tagName >/dev/null 2>&1 ||
		gh release create "$TAG" -R "$R" --draft --title "$TAG" \
			--notes "Compiler cache for the staged chromium build, shared across versions." >&2
	mkdir -p "$TMP/cc"
	manifest "$TAG" > "$TMP/old-ccache.json"
	layer=$(store_layer ccache -C "$dir" .)
	jq -n --argjson layer "$layer" --arg tag "$TAG" --argjson format "$FORMAT" \
		--arg run "$GITHUB_SERVER_URL/$R/actions/runs/$GITHUB_RUN_ID" \
		'{format: $format, tag: $tag, ccache: $layer, run: $run, at: (now | todate)}' \
		> "$TMP/cc/state.json"
	retry gh release upload "$TAG" "$TMP/cc/state.json" -R "$R" --clobber
	# The new manifest is committed: parts only the old one named can go.
	jq -r '[.ccache.parts[]?.name] | .[]' "$TMP/old-ccache.json" | sort > "$TMP/old"
	jq -r '[.ccache.parts[]?.name] | .[]' "$TMP/cc/state.json" | sort > "$TMP/new"
	comm -23 "$TMP/old" "$TMP/new" | while read -r name; do
		retry gh release delete-asset "$TAG" "$name" -R "$R" -y
	done
	jq '{ccache_bytes: .ccache.bytes}' "$TMP/cc/state.json"
	;;
delete)
	gh release delete "$2" -R "$R" -y
	;;
prune)
	keep=$2 days=$3
	gh api "repos/$R/releases" --paginate --jq '.[] | select(.draft and (.tag_name | startswith("chromium-state-")))
		| [.id, .tag_name, ((.assets | map(select(.name == "state.json")) | .[0].updated_at) // .created_at)] | @tsv' |
	while IFS=$'\t' read -r id tag updated; do
		[ "$tag" != "$keep" ] || continue
		if [ "$(date -d "$updated" +%s)" -lt "$(($(date +%s) - days * 86400))" ]; then
			echo "deleting $tag, idle since $updated"
			gh api -X DELETE "repos/$R/releases/$id"
		fi
	done
	;;
*)
	sed -n '2,/^set -euo/p' "$0" | sed '$d'
	exit 64
	;;
esac
