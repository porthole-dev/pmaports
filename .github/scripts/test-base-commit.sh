#!/bin/sh
# test-base-commit.sh -- run base-commit.sh against throwaway repositories.
set -eu
script=$(cd "$(dirname "$0")" && pwd)/base-commit.sh
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
export GIT_CONFIG_GLOBAL=/dev/null GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.org \
	GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.org
git init -q "$tmp/origin"
for i in 1 2 3 4 5; do git -C "$tmp/origin" commit -q --allow-empty -m "c$i"; done
c() { git -C "$tmp/origin" rev-parse "HEAD~$1"; }

# expect RESULT DEPTH EVENT JSON: RESULT is a commit, "none" or "error"
expect() {
	rm -rf "$tmp/clone"
	git clone -q --no-local --depth "$2" "file://$tmp/origin" "$tmp/clone"
	printf '%s\n' "$4" > "$tmp/event.json"
	if got=$(cd "$tmp/clone" && GITHUB_EVENT_NAME=$3 GITHUB_EVENT_PATH=$tmp/event.json sh "$script" 2>/dev/null); then
		got=${got:-none}
	else
		got=error
	fi
	if [ "$got" != "$1" ]; then
		echo "FAIL: expected $1, got $got for $3 at depth $2: $4" >&2
		exit 1
	fi
}

expect "$(c 1)" 5 pull_request "{\"pull_request\": {\"base\": {\"sha\": \"$(c 1)\"}}}"
expect error 2 pull_request "{\"pull_request\": {\"base\": {\"sha\": \"$(c 4)\"}}}"
expect "$(c 2)" 5 merge_group "{\"merge_group\": {\"base_sha\": \"$(c 2)\"}}"
expect "$(c 1)" 5 push "{\"before\": \"$(c 1)\", \"commits\": [{\"id\": \"$(c 0)\"}]}"
# a force push: before is gone, the push brought the last two commits
expect "$(c 2)" 5 push "{\"before\": \"0123456789012345678901234567890123456789\", \"commits\": [{\"id\": \"$(c 1)\"}, {\"id\": \"$(c 0)\"}]}"
# the same push, but the parent of its first commit is beyond the checkout
expect error 2 push "{\"before\": \"0123456789012345678901234567890123456789\", \"commits\": [{\"id\": \"$(c 1)\"}, {\"id\": \"$(c 0)\"}]}"
# a root commit, and a branch created at an existing commit
expect none 100 push "{\"before\": \"0000000000000000000000000000000000000000\", \"commits\": [{\"id\": \"$(c 4)\"}]}"
expect none 5 push "{\"before\": \"0000000000000000000000000000000000000000\", \"commits\": []}"
expect none 5 schedule "{}"
echo "base-commit: all cases pass"
