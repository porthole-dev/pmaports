#!/bin/sh
# run-pmbootstrap.sh [--no-init] COMMAND -- run COMMAND as the unprivileged
# "pmos" user in a ready pmbootstrap environment.
#
# Runs as root in an Alpine container whose working directory is the pmaports
# checkout, the way pmaports' own CI prepares one (ci-common's
# install_pmbootstrap.sh). Two differences, both on purpose:
#   - pmbootstrap is pinned to a commit instead of the tip of a branch;
#   - channels.cfg comes from this checkout instead of upstream's main
#     branch, so a run does not change when upstream edits that file.
#
# Assumes nothing about the machine: no pmbootstrap config, work directory or
# keys. The work directory is /work; bind-mount a host directory there to
# keep caches or results. --no-init skips `pmbootstrap init` for steps that
# only parse APKBUILDs.
#
# Environment:
#   PMB_REPO, PMB_COMMIT  pmbootstrap source (defaults below)
#   HOST_UID              on exit, give /work/cache_*, /work/packages and the
#                         checkout back to this uid (the runner's), so later
#                         steps and actions/cache can read and save them
set -eu

# pmbootstrap: upstream at the base of the porthole-dev fork branch, plus the
# fork's commits as patches in .github/pmbootstrap-patches/. Once the fork is
# published as porthole-dev/pmbootstrap this becomes
#   PMB_REPO=https://github.com/porthole-dev/pmbootstrap.git
#   PMB_COMMIT=<the fork commit the patch series was taken from>
# and the patch directory is deleted.
PMB_REPO=${PMB_REPO:-https://gitlab.postmarketos.org/postmarketOS/pmbootstrap.git}
PMB_COMMIT=${PMB_COMMIT:-e8a36b0a65dbd98e2f9f866d80888ba3dd69d6bd}

init=1
[ "${1:-}" = --no-init ] && { init=; shift; }
[ $# -eq 1 ] || { echo "usage: run-pmbootstrap.sh [--no-init] COMMAND" >&2; exit 64; }
pmaports=$(pwd -P)
patches=$pmaports/.github/pmbootstrap-patches

apk -q add coreutils git losetup multipath-tools openssl procps python3 sudo

id pmos >/dev/null 2>&1 || adduser -D pmos
echo 'pmos ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/pmos
git config --system --add safe.directory '*'

mkdir -p /opt/pmbootstrap
git -C /opt/pmbootstrap init -q
git -C /opt/pmbootstrap fetch -q --depth 1 "$PMB_REPO" "$PMB_COMMIT"
git -C /opt/pmbootstrap -c advice.detachedHead=false checkout -q FETCH_HEAD
count=0
for patch in "$patches"/*.patch; do
	[ -e "$patch" ] || continue
	git -C /opt/pmbootstrap apply "$patch"
	count=$((count + 1))
done
ln -sf /opt/pmbootstrap/pmbootstrap.py /usr/local/bin/pmbootstrap
echo "pmbootstrap $(git -C /opt/pmbootstrap rev-parse --short HEAD) with $count patch(es)"

# The default work path, pointed at /work.
mkdir -p /work /home/pmos/.local/var /home/pmos/.config
ln -sfn /work /home/pmos/.local/var/pmbootstrap
chown pmos:pmos /work /home/pmos/.local /home/pmos/.local/var /home/pmos/.config
# Chroot builds run as uid 12345; restored caches belong to the runner.
for d in /work/cache_ccache_* /work/cache_distfiles; do
	if [ -d "$d" ]; then chown -R 12345:12345 "$d"; fi
done
if [ -n "${HOST_UID:-}" ]; then
	trap 'chown -R "$HOST_UID" /work/cache_* /work/packages "$pmaports" 2>/dev/null || true' EXIT
fi
chown -R pmos:pmos "$pmaports"

# busybox su without -l keeps this environment, and the working directory.
export PMB_CHANNELS_CFG="$pmaports/channels.cfg"
export PYTHONPATH="/opt/pmbootstrap:$pmaports/.ci/lib"
export PYTHONUNBUFFERED=1
if [ -n "$init" ]; then
	# Stay on the checked-out branch instead of switching to the channel's.
	printf '[pmbootstrap]\nis_default_channel = False\n' > /home/pmos/.config/pmbootstrap_v3.cfg
	chown pmos:pmos /home/pmos/.config/pmbootstrap_v3.cfg
	# The documented non-interactive init: accept every default.
	if ! su pmos -c "yes '' | pmbootstrap --aports '$pmaports' init >/tmp/pmbootstrap-init.log 2>&1"; then
		cat /tmp/pmbootstrap-init.log
		exit 1
	fi
fi
su pmos -c "$1"
