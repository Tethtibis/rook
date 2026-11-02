#!/usr/bin/env bash
# ==============================================================================
# ROOK DEBIAN PACKAGE BUILDER (rook_1.0.0_amd64.deb)
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_NAME="rook"
PKG_VER="1.0.0"
ARCH="amd64"
BUILD_ROOT="/tmp/${PKG_NAME}_${PKG_VER}_${ARCH}"
OUT_DEB="${SCRIPT_DIR}/${PKG_NAME}_${PKG_VER}_${ARCH}.deb"

rm -rf "${BUILD_ROOT}"
mkdir -p "${BUILD_ROOT}/DEBIAN"
mkdir -p "${BUILD_ROOT}/opt/rook/bin"
mkdir -p "${BUILD_ROOT}/usr/bin"
mkdir -p "${BUILD_ROOT}/usr/share/applications"

# 1. Copy Rook Modules, Kernel, and Static Pascal/CUDA llama-server Binary
cp "${SCRIPT_DIR}"/rook_*.py "${BUILD_ROOT}/opt/rook/"
cp "${SCRIPT_DIR}/ROOK_KERNEL.md" "${SCRIPT_DIR}/ROOK_OPERATOR.md" "${BUILD_ROOT}/opt/rook/"
cp "${SCRIPT_DIR}/bin/llama-server" "${BUILD_ROOT}/opt/rook/bin/llama-server"
chmod 755 "${BUILD_ROOT}/opt/rook"/*.py "${BUILD_ROOT}/opt/rook/bin/llama-server"

# 2. Create Burnt-Orange Vector SVG Icon
cat << 'EOF' > "${BUILD_ROOT}/opt/rook/rook.svg"
<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 24 24" fill="#050505" stroke="#CC5500" stroke-width="1.8">
  <rect x="1" y="1" width="22" height="22" rx="4" fill="#0a0a0a" stroke="#CC5500" stroke-width="1.5"/>
  <path d="M6 4h2.5v2.5h2.5V4h2v2.5h2.5V4H18v5l-1.8 1.8v6.2H18v3H6v-3h1.8v-6.2L6 9V4z" fill="#CC5500" stroke="#FF8C00" stroke-width="0.8"/>
</svg>
EOF

# 3. Create /usr/bin/rook and /usr/bin/rykr-lite Launchers
cat << 'EOF' > "${BUILD_ROOT}/usr/bin/rook"
#!/usr/bin/env bash
set -e
if [ "${1:-}" = "--status" ] || [ "${1:-}" = "--unload" ] || [ "${1:-}" = "--load" ]; then
    exec /usr/bin/python3 /opt/rook/rook_gguf_loader.py "$@"
fi
if [ "${1:-}" = "--calc" ] || [ "${1:-}" = "--audit-csv" ] || [ "${1:-}" = "--ocr" ]; then
    exec /usr/bin/python3 /opt/rook/rook_workbench.py "$@"
fi
# Free any stale instance on port 8490 before launching fresh window
fuser -k 8490/tcp >/dev/null 2>&1 || true
exec /usr/bin/python3 /opt/rook/rook_app.py "$@"
EOF
chmod 755 "${BUILD_ROOT}/usr/bin/rook"
ln -sf /usr/bin/rook "${BUILD_ROOT}/usr/bin/rykr-lite"

# 4. Create Desktop Menu Entry
cat << 'EOF' > "${BUILD_ROOT}/usr/share/applications/rook.desktop"
[Desktop Entry]
Version=1.0
Type=Application
Name=Rook (Rykr Local AI Field Unit)
Comment=Single-Window Deterministic Local GGUF AI Appliance (Auto-VRAM Release on Close)
Exec=/usr/bin/rook
Icon=/opt/rook/rook.svg
Terminal=false
Categories=Utility;Development;System;
StartupNotify=true
EOF

# 5. Create DEBIAN/control
cat << EOF > "${BUILD_ROOT}/DEBIAN/control"
Package: ${PKG_NAME}
Version: ${PKG_VER}
Section: utils
Priority: optional
Architecture: ${ARCH}
Depends: python3, tesseract-ocr, psmisc
Maintainer: Bill (Tethtibis) & Rykr Framework v4.1 <https://github.com/Tethtibis/rykr-framework>
Description: Rook - Single-Window Deterministic Local GGUF AI Appliance
 Standalone local AI field unit (offspring of Rykr-Prime) featuring a
 single-window GIMP-style control plane, zero-Ollama direct .gguf CUDA
 engine loader with kernel PR_SET_PDEATHSIG auto-VRAM release on exit,
 deterministic base-10 Decimal math/CSV/SQLite auditing, offline Tesseract
 screenshot OCR, custom push-button forging, and Rykr-Prime audit export.
EOF

# 6. Create DEBIAN/postinst
cat << 'EOF' > "${BUILD_ROOT}/DEBIAN/postinst"
#!/usr/bin/env bash
set -e
mkdir -p /var/tmp/rook/inbox
chmod 1777 /var/tmp/rook /var/tmp/rook/inbox
echo "[+] Rook v1.0.0 installed. Run 'rook' (or click Rook in your app menu) to launch."
EOF
chmod 755 "${BUILD_ROOT}/DEBIAN/postinst"

dpkg-deb --build --root-owner-group "${BUILD_ROOT}" "${OUT_DEB}"
rm -rf "${BUILD_ROOT}"
ls -lh "${OUT_DEB}"
