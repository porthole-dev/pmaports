#!/bin/sh
# Assemble a configured experimental device release in the CI pmbootstrap container.
# No device writes. The caller supplies the published package mirror.
set -eu
: "${PACKAGES_URL:?published package repository required}"
: "${FIRMWARE_GRANT:?firmware grant required}"
[ "$FIRMWARE_GRANT" = approved ]
: "${IMAGE_DEVICE:?device required}"
eval "$(python3 .github/scripts/image-config.py "$IMAGE_DEVICE")"
python3 .github/scripts/test-image.py
pmb() { pmbootstrap --details-to-stdout --aports "$PWD" "$@"; }
pmb config device "$IMAGE_DEVICE"
pmb config kernel "$IMAGE_KERNEL"
pmb config ui "$IMAGE_UI"
pmb config service_manager "$IMAGE_INIT"
pmb config user user
pmb config hostname nura
pmb config mirrors.pmaports_custom "$PACKAGES_URL"
pmb config mirrors.systemd_custom "$PACKAGES_URL/systemd"
pmb config build_pkgs_on_install False
mkdir -p /work/config_apk_keys /work/image
cp .github/keys/*.pub /work/config_apk_keys/
pmb install --password "${PORTHOLE_PMOS_PASSWORD:?release password required}" --no-local-pkgs --add "$IMAGE_EXTRA"
root=/work/chroot_rootfs_$IMAGE_DEVICE
# Confirm udev works after all systemd components have been installed.
if [ "$IMAGE_INIT" = systemd ]; then
    sudo chroot "$root" /usr/bin/udevadm --version
fi
# Validate installed versions against the release recipes, not just package presence.
sudo --preserve-env=PYTHONPATH,PMB_CHANNELS_CFG python3 .github/scripts/check-image.py "$root" "$IMAGE_DEVICE"
pmb export /work/export
# Fastboot exports may use Android sparse encoding. Verify the filesystem UUIDs
# on a temporary decoded copy, while publishing the original flashable export.
uuid_image=/work/export/$IMAGE_DEVICE.img
if python3 -c 'import sys; sys.exit(open(sys.argv[1], "rb").read(4) != bytes.fromhex("3aff26ed"))' "$uuid_image"; then
    pmb chroot -- simg2img "/home/pmos/rootfs/$IMAGE_DEVICE.img" "/home/pmos/rootfs/$IMAGE_DEVICE-verify.raw"
    uuid_image=/work/chroot_native/home/pmos/rootfs/$IMAGE_DEVICE-verify.raw
fi
python3 /verification/tools/rootfs-uuid.py "$uuid_image" --bootimg /work/export/boot.img
if [ "$uuid_image" != "/work/export/$IMAGE_DEVICE.img" ]; then sudo rm -f "$uuid_image"; fi
python3 /verification/tools/bootimg-verify.py /work/export/boot.img \
    --dtb "$root/$IMAGE_BOOT_DTB" --kernel "$root/$IMAGE_BOOT_KERNEL"
cp -L /work/export/boot.img /work/image/
cp -L "/work/export/$IMAGE_DEVICE.img" "/work/image/$IMAGE_DEVICE.img"
if [ -n "$IMAGE_DTBO_SHA256" ]; then
    cp -L /work/export/dtbo.img /work/image/
    printf '%s  %s\n' "$IMAGE_DTBO_SHA256" /work/image/dtbo.img | sha256sum -c -
fi
cp "$root/lib/apk/db/installed" /work/image/installed-packages.txt
cp "$root/etc/apk/repositories" /work/image/apk-repositories.txt
# Preserve exact source revisions and the signed indexes consumed by the image.
git rev-parse HEAD > /work/image/pmaports.commit
git -C /opt/pmbootstrap rev-parse HEAD > /work/image/pmbootstrap.commit
cp /work/config_apk_keys/*.pub /work/image/
for repo in "$IMAGE_BRANCH" "systemd/$IMAGE_BRANCH"; do
    name=$(printf '%s' "$repo" | tr / -)
    wget -q -O "/work/image/$name-APKINDEX.tar.gz" "$PACKAGES_URL/$repo/$IMAGE_ARCH/APKINDEX.tar.gz"
done
gzip -n "/work/image/$IMAGE_DEVICE.img"
cp "$IMAGE_INSTALL_GUIDE" /work/image/INSTALL.md
cp /work/image-config.json /work/image/device.json
(cd /work/image && sha256sum ./* > SHA256SUMS)
python3 .github/scripts/bundle.py /work/image "$IMAGE_DEVICE"
python3 .github/scripts/bundle.py /work/image "$IMAGE_DEVICE" --native
(cd /work/image && cat BUNDLE-SHA256SUMS NATIVE-V2-BUNDLE-SHA256SUMS >> SHA256SUMS)
