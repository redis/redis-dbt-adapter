#!/usr/bin/env bash
# Download the prebuilt Redis ADBC driver from its GitHub release into
# ./driver/, after checking the release's SHA-256.
#
# The driver's repo is public. Download with gh when it is authenticated
# (gh auth login, or GH_TOKEN as in CI); otherwise use curl over HTTPS.
# DRIVER_RELEASES can point to a release mirror.
#
# Releases have builds for macOS arm64, Linux x86-64 and Linux arm64. When
# there's none for this platform or version (another OS, or DRIVER_VERSION set
# to a commit), this builds the driver from source instead
# (scripts/build_driver.sh, which needs Go 1.26+ and a C toolchain).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DRIVER_GH_REPO="${DRIVER_GH_REPO:-redis/redis-adbc-driver}"
DRIVER_RELEASES="${DRIVER_RELEASES:-}"
DRIVER_VERSION="${DRIVER_VERSION:-$(cat "${ROOT}/scripts/driver-version")}"

build_instead() {
  echo "$1; building it from source instead." >&2
  exec "${ROOT}/scripts/build_driver.sh"
}

case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) PLATFORM=darwin-arm64 EXT=dylib ;;
  Linux-x86_64 | Linux-amd64) PLATFORM=linux-amd64 EXT=so ;;
  Linux-aarch64 | Linux-arm64) PLATFORM=linux-arm64 EXT=so ;;
  *) build_instead "No prebuilt driver for $(uname -s) $(uname -m)" ;;
esac

NAME="adbc_driver_redis-${DRIVER_VERSION}-${PLATFORM}"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

# A missing release (or build for this platform) means build instead. Any
# other failure stops here.
if [ -z "${DRIVER_RELEASES}" ] && command -v gh >/dev/null && gh auth status >/dev/null 2>&1; then
  if ! gh release download "${DRIVER_VERSION}" --repo "${DRIVER_GH_REPO}" --dir "${TMP}" \
    --pattern "${NAME}.tar.gz" --pattern "${NAME}.tar.gz.sha256" 2>"${TMP}/gh.log"; then
    case "$(cat "${TMP}/gh.log")" in
      *"release not found"* | *"no assets match"*)
        build_instead "No prebuilt driver ${NAME} in ${DRIVER_GH_REPO} (is ${DRIVER_VERSION} a release?)" ;;
      *) cat "${TMP}/gh.log" >&2; exit 1 ;;
    esac
  fi
else
  URL="${DRIVER_RELEASES:-https://github.com/${DRIVER_GH_REPO}/releases/download}/${DRIVER_VERSION}/${NAME}.tar.gz"
  status="$(curl -sSL -o "${TMP}/${NAME}.tar.gz" -w '%{http_code}' "${URL}")"
  case "${status}" in
    200) ;;
    404) build_instead "No prebuilt driver ${NAME} (is ${DRIVER_VERSION} a release?)" ;;
    *) echo "Downloading ${URL} failed: HTTP ${status}" >&2; exit 1 ;;
  esac
  curl -fsSL -o "${TMP}/${NAME}.tar.gz.sha256" "${URL}.sha256"
fi

if command -v sha256sum >/dev/null; then
  (cd "${TMP}" && sha256sum --check --quiet "${NAME}.tar.gz.sha256")
else
  (cd "${TMP}" && shasum -a 256 --check --quiet "${NAME}.tar.gz.sha256")
fi

tar -xzf "${TMP}/${NAME}.tar.gz" -C "${TMP}"
mkdir -p "${ROOT}/driver"
cp "${TMP}/${NAME}/libadbc_driver_redis.${EXT}" "${ROOT}/driver/"
echo "Downloaded ${ROOT}/driver/libadbc_driver_redis.${EXT} (${DRIVER_VERSION}, ${PLATFORM})"
