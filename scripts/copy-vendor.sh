#!/usr/bin/env bash
# copy-vendor.sh — copies dist files from node_modules into static vendor dirs.
# Run after `npm install` when upgrading any library listed in package.json.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NM="$ROOT/node_modules"

# ── helpers ────────────────────────────────────────────────────────────────
cp_v() { echo "  $1 → $2"; cp "$1" "$2"; }

# ── 1. Tabler core  →  nuevo_fonotarot/static/vendor/tabler/ ──────────────
TABLER="$ROOT/nuevo_fonotarot/static/vendor/tabler"
mkdir -p "$TABLER/css" "$TABLER/js"
cp_v "$NM/@tabler/core/dist/css/tabler.min.css"       "$TABLER/css/tabler.min.css"
cp_v "$NM/@tabler/core/dist/css/tabler-flags.min.css" "$TABLER/css/tabler-flags.min.css"
cp_v "$NM/@tabler/core/dist/js/tabler.min.js"         "$TABLER/js/tabler.min.js"

# ── 2. Tabler icons  →  nuevo_fonotarot/static/vendor/tabler-icons/ ───────
ICONS="$ROOT/nuevo_fonotarot/static/vendor/tabler-icons"
mkdir -p "$ICONS/fonts"
cp_v "$NM/@tabler/icons-webfont/dist/tabler-icons.min.css" "$ICONS/tabler-icons.min.css"
cp_v "$NM/@tabler/icons-webfont/dist/fonts/tabler-icons.woff2" "$ICONS/fonts/tabler-icons.woff2"
cp_v "$NM/@tabler/icons-webfont/dist/fonts/tabler-icons.woff"  "$ICONS/fonts/tabler-icons.woff"
cp_v "$NM/@tabler/icons-webfont/dist/fonts/tabler-icons.ttf"   "$ICONS/fonts/tabler-icons.ttf"

# ── 3. Web fonts (fontsource, latin subset only) ───────────────────────────
FONTS="$ROOT/nuevo_fonotarot/static/vendor/fonts"
mkdir -p "$FONTS/files"

# Montserrat: weights used in base.html (400 500 600 700 800) and security (400 500 600 700)
for W in 400 500 600 700 800; do
  cat "$NM/@fontsource/montserrat/latin-${W}.css" >> "$FONTS/montserrat.css"
done

# Playfair Display: 400 normal, 700 normal, 400 italic, 700 italic
for F in latin-400 latin-700 latin-400-italic latin-700-italic; do
  cat "$NM/@fontsource/playfair-display/${F}.css" >> "$FONTS/playfair-display.css"
done

# Source Sans 3: weights 300 400 600
for W in 300 400 600; do
  cat "$NM/@fontsource/source-sans-3/latin-${W}.css" >> "$FONTS/source-sans-3.css"
done

# Copy font files referenced by the generated CSS files
copy_font_files() {
  local css_file="$1"
  local pkg="$2"
  grep -oP "(?<=url\(./files/)[^)'\"()]+" "$css_file" \
    | sort -u \
    | while read -r fname; do
        SRC="$NM/@fontsource/$pkg/files/$fname"
        [ -f "$SRC" ] && cp_v "$SRC" "$FONTS/files/$fname"
      done
}
copy_font_files "$FONTS/montserrat.css"      "montserrat"
copy_font_files "$FONTS/playfair-display.css" "playfair-display"
copy_font_files "$FONTS/source-sans-3.css"   "source-sans-3"

# ── 4. HugeRTE  →  nuevo_fonotarot/static/vendor/hugerte/ ────────────────
HUGERTE="$ROOT/nuevo_fonotarot/static/vendor/hugerte"
mkdir -p "$HUGERTE"
cp_v "$NM/hugerte/hugerte.min.js" "$HUGERTE/hugerte.min.js"
cp -r "$NM/hugerte/icons"   "$HUGERTE/icons"
cp -r "$NM/hugerte/models"  "$HUGERTE/models"
cp -r "$NM/hugerte/plugins" "$HUGERTE/plugins"
cp -r "$NM/hugerte/skins"   "$HUGERTE/skins"
cp -r "$NM/hugerte/themes"  "$HUGERTE/themes"
echo "  hugerte → $HUGERTE (+ icons/ models/ plugins/ skins/ themes/)"

# ── 5. GrapeJS  →  nuevo_fonotarot/static/vendor/grapesjs/ ───────────────
GJS="$ROOT/nuevo_fonotarot/static/vendor/grapesjs"
mkdir -p "$GJS/css" "$GJS/js"
cp_v "$NM/grapesjs/dist/css/grapes.min.css"               "$GJS/css/grapes.min.css"
cp_v "$NM/grapesjs/dist/grapes.min.js"                    "$GJS/js/grapesjs.min.js"
cp_v "$NM/grapesjs-preset-webpage/dist/index.js"          "$GJS/js/grapesjs-preset-webpage.min.js"
cp_v "$NM/grapesjs-blocks-basic/dist/index.js"            "$GJS/js/grapesjs-blocks-basic.min.js"

# ── 5. Highlight.js  →  flask_admin_tabler/static/vendor/highlightjs/ ─────
HLJS="$ROOT/flask_admin_tabler/static/vendor/highlightjs"
mkdir -p "$HLJS/styles"
cp_v "$NM/@highlightjs/cdn-assets/highlight.min.js"              "$HLJS/highlight.min.js"
cp_v "$NM/@highlightjs/cdn-assets/styles/googlecode.min.css"     "$HLJS/styles/googlecode.min.css"
cp_v "$NM/@highlightjs/cdn-assets/styles/monokai.min.css"        "$HLJS/styles/monokai.min.css"

echo ""
echo "✓ Vendor assets copied successfully."
