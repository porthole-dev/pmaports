#!/bin/sh
# Assemble an experimental Taimen release in the CI pmbootstrap container.
# No device writes. The caller supplies the published package mirror.
set -eu
: "${PACKAGES_URL:?published package repository required}"
: "${FIRMWARE_GRANT_TAIMEN:?firmware grant required}"
[ "$FIRMWARE_GRANT_TAIMEN" = approved ]
pmb() { pmbootstrap --aports "$PWD" "$@"; }
pmb config device google-taimen
pmb config kernel mainline
pmb config ui phosh
pmb config service_manager systemd
pmb config user user
pmb config hostname nura
pmb config mirrors.pmaports_custom "$PACKAGES_URL"
pmb config mirrors.systemd_custom "$PACKAGES_URL/systemd"
pmb config build_pkgs_on_install False
mkdir -p /work/config_apk_keys /work/image
cp .github/keys/*.pub /work/config_apk_keys/
pmb install --password "${PORTHOLE_PMOS_PASSWORD:?release password required}" --no-local-pkgs --add firmware-google-taimen-fingerprint,fprintd,tap,obscura
root=/work/chroot_rootfs_google-taimen
# Public images must never carry a build-host login key.
if find "$root/home" "$root/root" -name authorized_keys -type f -size +0c | grep -q .; then
    echo 'Refusing an image containing authorized SSH keys' >&2
    exit 1
fi
# Validate installed versions against the release recipes, not just package presence.
python3 .github/scripts/check-image.py "$root"
pmb export /work/export
cp -L /work/export/boot.img /work/export/dtbo.img /work/image/
cp -L /work/export/google-taimen.img /work/image/google-taimen.img
printf '%s  %s\n' fd9752b381403312bcdeda8bb8555f0ad964f3464e7bc4ed307e3cef018362da /work/image/dtbo.img | sha256sum -c -
cp "$root/lib/apk/db/installed" /work/image/installed-packages.txt
cp "$root/etc/apk/repositories" /work/image/apk-repositories.txt
# Preserve exact source revisions and the signed indexes consumed by the image.
git rev-parse HEAD > /work/image/pmaports.commit
git -C /opt/pmbootstrap rev-parse HEAD > /work/image/pmbootstrap.commit
cp /work/config_apk_keys/*.pub /work/image/
for repo in main systemd/main; do
    name=$(printf '%s' "$repo" | tr / -)
    wget -q -O "/work/image/$name-APKINDEX.tar.gz" "$PACKAGES_URL/$repo/aarch64/APKINDEX.tar.gz"
done
gzip -n /work/image/google-taimen.img
cp .github/IMAGE-INSTALL.md /work/image/INSTALL.md
(cd /work/image && sha256sum ./* > SHA256SUMS)
