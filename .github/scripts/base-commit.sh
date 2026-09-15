#!/bin/sh
# base-commit.sh -- print the commit this workflow run's changes are measured
# from, or nothing when there is none (scheduled and manual runs, a new branch
# at an existing commit, a root commit).
#
#   pull_request  the base branch commit
#   merge_group   the merge group's base commit
#   push          the previous tip of the branch; after a force push or on a
#                 new branch, the parent of the first commit the push brought
#
# Needs jq, the GitHub event payload and a checkout deep enough to hold the
# base (fetch-depth: 100, like pmaports' own CI). A base that should exist but
# is not in the checkout is an error: printing nothing would silently check
# nothing.
set -eu
event=$GITHUB_EVENT_PATH

have() { git cat-file -e "$1^{commit}" 2>/dev/null; }
missing() {
	echo "::error::base-commit.sh: $1 is not in this checkout; the checkout needs more history (fetch-depth)" >&2
	exit 1
}

case "$GITHUB_EVENT_NAME" in
pull_request | merge_group)
	if [ "$GITHUB_EVENT_NAME" = pull_request ]; then
		base=$(jq -r .pull_request.base.sha "$event")
	else
		base=$(jq -r .merge_group.base_sha "$event")
	fi
	have "$base" || missing "$base"
	echo "$base"
	;;
push)
	before=$(jq -r .before "$event")
	if have "$before" && git merge-base --is-ancestor "$before" HEAD; then
		echo "$before"
		exit 0
	fi
	[ "$(jq '.commits | length' "$event")" -lt 2048 ] ||
		missing "the first commit of this push (the event lists at most 2048)"
	first=$(jq -r '.commits[0].id // empty' "$event")
	[ -n "$first" ] || exit 0 # a new branch at an existing commit
	have "$first" || missing "$first"
	# In a shallow checkout the oldest commit looks like a root commit.
	shallow=$(git rev-parse --git-path shallow)
	if [ -f "$shallow" ] && grep -qx "$(git rev-parse "$first")" "$shallow"; then
		missing "the parent of $first"
	fi
	# Prints nothing only for a root commit (the first push to a repository).
	git rev-parse -q --verify "$first^" || true
	;;
esac
