#!/usr/bin/env bash
# Build a versioned, never-overwritten libfprint-2-2 .deb (Goodix 27c6:550c driver)
# on top of the stock Debian package layout. Needs no root.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG_NAME=libfprint-2-2
UPSTREAM=1.94.10

usage() {
  cat <<USAGE
Usage: $(basename "$0") [options]

Builds ${PKG_NAME}_${UPSTREAM}+goodix550cN_amd64.deb from the stock Debian
deb plus the locally built libfprint-2.so.2.0.0. Refuses to overwrite.

Options:
  --so PATH          built libfprint-2.so.2.0.0 (default: found under
                     build/rebuild-vi-mfp/builddir)
  --out DIR          output directory (default: ~/goodix550c-debs/patched)
  --n N              revision N (default: highest existing +goodix550cN in
                     --out, plus one; 1 if none)
  --stock-deb FILE   stock Debian deb (default:
                     ~/goodix550c-debs/stock/libfprint-2-2_1%3a1.94.9-1_amd64.deb)
  --series FILE      driver-series file to hash (default:
                     patches/goodix-550c/driver-series)
  --work DIR         staging root (default: build/pkg); DIR/libfprint-2-2 is
                     wiped on every run
  --pkg NAME         package to build: libfprint-2-2 (default) or
                     goodix550c-fingerprint (arch all, from
                     packaging/goodix550c-fingerprint/; uses --out and --work only)
  -h, --help         this help
USAGE
}

SO=""
OUT="$HOME/goodix550c-debs/patched"
N=""
STOCK="$HOME/goodix550c-debs/stock/libfprint-2-2_1%3a1.94.9-1_amd64.deb"
SERIES="$ROOT/patches/goodix-550c/driver-series"
WORK="$ROOT/build/pkg"
PKG_SEL=libfprint-2-2

die() { echo "error: $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --so) SO="${2:?--so needs a value}"; shift 2 ;;
    --out) OUT="${2:?--out needs a value}"; shift 2 ;;
    --n) N="${2:?--n needs a value}"; shift 2 ;;
    --stock-deb) STOCK="${2:?--stock-deb needs a value}"; shift 2 ;;
    --series) SERIES="${2:?--series needs a value}"; shift 2 ;;
    --work) WORK="${2:?--work needs a value}"; shift 2 ;;
    --pkg) PKG_SEL="${2:?--pkg needs a value}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "unknown option: $1" ;;
  esac
done

for tool in dpkg-deb sha256sum md5sum gzip awk sed; do
  command -v "$tool" >/dev/null || die "missing tool: $tool"
done

build_fingerprint_pkg() {
  local name=goodix550c-fingerprint src="$ROOT/packaging/goodix550c-fingerprint"
  local stage="$WORK/$name" version deb size
  [ -f "$src/DEBIAN/control" ] || die "missing $src/DEBIAN/control"
  version="$(sed -n 's/^Version: *//p' "$src/DEBIAN/control" | head -n 1)"
  [ -n "$version" ] || die "no Version in control"
  deb="$OUT/${name}_${version}_all.deb"
  mkdir -p "$OUT"
  [ ! -e "$deb" ] || die "refusing to overwrite existing $deb (bump Version in control or remove it yourself)"
  rm -rf "$stage"
  mkdir -p "$stage"
  cp -a "$src/." "$stage/"
  find "$stage" -type d -exec chmod 0755 {} +
  find "$stage" -type f -not -path "$stage/DEBIAN/*" -exec chmod 0644 {} +
  chmod 0755 "$stage/usr/sbin/goodix550c-ctl"
  size="$(du -sk --exclude=DEBIAN "$stage" | cut -f1)"
  sed -i "s/@INSTALLED_SIZE@/$size/g" "$stage/DEBIAN/control"
  ( cd "$stage" && find . -path ./DEBIAN -prune -o -type f -print | LC_ALL=C sort | sed 's|^\./||' | xargs -d '\n' md5sum ) > "$stage/DEBIAN/md5sums"
  chmod 0644 "$stage/DEBIAN/control" "$stage/DEBIAN/md5sums" "$stage/DEBIAN/conffiles"
  for s in preinst postinst prerm postrm; do chmod 0755 "$stage/DEBIAN/$s"; done
  dpkg-deb --root-owner-group --build "$stage" "$deb" >/dev/null
  ( cd "$OUT" && sha256sum -- *.deb > SHA256SUMS )
  echo "built:   $deb"
  echo "sha256:  $(sha256sum "$deb" | cut -d' ' -f1)"
}

case "$PKG_SEL" in
  goodix550c-fingerprint) build_fingerprint_pkg; exit 0 ;;
  libfprint-2-2) ;;
  *) die "unknown --pkg: $PKG_SEL" ;;
esac

if [ -z "$SO" ]; then
  SO="$(find "$ROOT/build/rebuild-vi-mfp/builddir" -name libfprint-2.so.2.0.0 -print -quit 2>/dev/null || true)"
  [ -n "$SO" ] || die "no libfprint-2.so.2.0.0 under build/rebuild-vi-mfp/builddir; pass --so"
fi
[ -f "$SO" ] && [ -s "$SO" ] || die "not a non-empty file: $SO"
[ -f "$STOCK" ] || die "stock deb not found: $STOCK"
[ -f "$SERIES" ] || die "driver-series not found: $SERIES"
mkdir -p "$OUT"

if [ -z "$N" ]; then
  max=0
  for f in "$OUT"/${PKG_NAME}_${UPSTREAM}+goodix550c*_amd64.deb; do
    [ -e "$f" ] || continue
    n="${f##*+goodix550c}"; n="${n%%_*}"
    case "$n" in ''|*[!0-9]*) continue ;; esac
    [ "$n" -gt "$max" ] && max="$n"
  done
  N=$((max + 1))
fi
case "$N" in ''|*[!0-9]*|0*) die "--n must be a positive integer without leading zeros: $N" ;; esac

DEB="$OUT/${PKG_NAME}_${UPSTREAM}+goodix550c${N}_amd64.deb"
[ ! -e "$DEB" ] || die "refusing to overwrite existing $DEB (use --n or remove it yourself)"

SERIES_SHA="$(sha256sum "$SERIES" | cut -d' ' -f1)"
SO_SHA="$(sha256sum "$SO" | cut -d' ' -f1)"
GIT_REV="unknown"; GIT_DIRTY="unknown"
if git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1; then
  GIT_REV="$(git -C "$ROOT" rev-parse HEAD)"
  if [ -n "$(git -C "$ROOT" status --porcelain 2>/dev/null)" ]; then GIT_DIRTY=yes; else GIT_DIRTY=no; fi
fi
BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
DATE_RFC="$(date -R)"

STAGE="$WORK/$PKG_NAME"
rm -rf "$STAGE"
mkdir -p "$WORK"
dpkg-deb -R "$STOCK" "$STAGE"

LIBDIR="$STAGE/usr/lib/x86_64-linux-gnu"
mkdir -p "$LIBDIR"
rm -f "$LIBDIR/libfprint-2.so.2.0.0" "$LIBDIR/libfprint-2.so.2"
install -m0644 "$SO" "$LIBDIR/libfprint-2.so.2.0.0"
ln -s libfprint-2.so.2.0.0 "$LIBDIR/libfprint-2.so.2"

# shlibs: the patched library is 1.94.10-level.
echo "libfprint-2 2 libfprint-2-2 (>= 1:${UPSTREAM})" > "$STAGE/DEBIAN/shlibs"

# hwdb: drop the 550c match line; drop a block only if that leaves it with no matches.
HWDB="$STAGE/usr/lib/udev/hwdb.d/60-autosuspend-libfprint-2.hwdb"
if [ -f "$HWDB" ]; then
  awk 'BEGIN { RS = ""; FS = "\n"; first = 1 }
    {
      n = 0; matches = 0; removed = 0
      for (i = 1; i <= NF; i++) {
        if (toupper($i) ~ /^USB:V27C6P550C/) { removed = 1; continue }
        if ($i ~ /^usb:/) matches++
        line[++n] = $i
      }
      if (removed && matches == 0) next
      if (!first) printf "\n"
      first = 0
      for (i = 1; i <= n; i++) print line[i]
    }' "$HWDB" > "$HWDB.new"
  # keep the original blank-line block separators: awk output uses one blank line, as does stock
  mv "$HWDB.new" "$HWDB"
  chmod 0644 "$HWDB"
  if grep -qi '^usb:v27C6p550C' "$HWDB"; then die "550c still listed in staged hwdb"; fi
fi

# changelog: prepend a local entry
CL="$STAGE/usr/share/doc/$PKG_NAME/changelog.Debian.gz"
if [ -f "$CL" ]; then
  {
    sed -e "s/@N@/$N/g" -e "s/@SERIES_SHA@/$SERIES_SHA/g" -e "s/@DATE_RFC@/$DATE_RFC/g" \
      "$ROOT/packaging/libfprint-2-2/changelog-entry"
    gzip -dc "$CL"
  } | gzip -9n > "$CL.new"
  mv "$CL.new" "$CL"
  chmod 0644 "$CL"
fi

# build record
DOCDIR="$STAGE/usr/share/doc/$PKG_NAME"
mkdir -p "$DOCDIR"
cat > "$DOCDIR/GOODIX550C-BUILD" <<BUILD
package: $PKG_NAME 1:${UPSTREAM}+goodix550c${N}
base: $(basename "$STOCK")
driver-series sha256: $SERIES_SHA
git rev: $GIT_REV
git dirty: $GIT_DIRTY
libfprint-2.so.2.0.0 sha256: $SO_SHA
build date: $BUILD_DATE
BUILD
chmod 0644 "$DOCDIR/GOODIX550C-BUILD"

# normalise permissions
find "$STAGE" -type d -exec chmod 0755 {} +
find "$STAGE" -type f -not -path "$STAGE/DEBIAN/*" -exec chmod 0644 {} +

# control
INSTALLED_SIZE="$(du -sk --exclude=DEBIAN "$STAGE" | cut -f1)"
sed -e "s/@N@/$N/g" -e "s/@SERIES_SHA@/$SERIES_SHA/g" -e "s/@INSTALLED_SIZE@/$INSTALLED_SIZE/g" \
  "$ROOT/packaging/libfprint-2-2/control.in" > "$STAGE/DEBIAN/control"
chmod 0644 "$STAGE/DEBIAN/control"

# md5sums (regular files only, as dpkg expects)
( cd "$STAGE" && find . -path ./DEBIAN -prune -o -type f -print | LC_ALL=C sort | sed 's|^\./||' | xargs -d '\n' md5sum ) > "$STAGE/DEBIAN/md5sums"
chmod 0644 "$STAGE/DEBIAN/md5sums"
for s in postinst postrm preinst prerm; do
  [ -f "$STAGE/DEBIAN/$s" ] && chmod 0755 "$STAGE/DEBIAN/$s"
done

dpkg-deb --root-owner-group --build "$STAGE" "$DEB" >/dev/null
( cd "$OUT" && sha256sum -- *.deb > SHA256SUMS )

echo "built:   $DEB"
echo "sha256:  $(sha256sum "$DEB" | cut -d' ' -f1)"
echo "series:  $SERIES_SHA"
echo "so:      $SO_SHA"
echo "git:     $GIT_REV (dirty: $GIT_DIRTY)"
