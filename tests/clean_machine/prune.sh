#!/usr/bin/env bash
# Which of OCRmyPDF's dependencies the plugin can do without, on a clean machine, offline.
# Usage: prune.sh WHEEL OCRMYPDF_WHEELS_DIR REQUIREMENTS CHECK_PY
set -euo pipefail
WHEEL="$1" WHEELS="$2" REQUIREMENTS="$3" CHECK="$4"
mismatches=0

# variant EXPECT NAME [DROP...]: EXPECT is works or fails, as docs/PACKAGING.md records.
variant() {
    local expect="$1" name="$2"; shift 2
    local venv="/tmp/prune-$name"
    python3 -m venv "$venv"
    "$venv/bin/pip" install -q --no-index "$WHEEL"
    # Pinned versions only, minus the packages this variant leaves out.
    grep -E '^[a-z0-9-]+==' "$REQUIREMENTS" | awk '{print $1}' | while read -r pin; do
        skip=0
        for drop in "$@"; do [ "${pin%%==*}" = "$drop" ] && skip=1; done
        [ "$skip" = 1 ] || echo "$pin"
    done > "/tmp/prune-$name.txt"
    "$venv/bin/pip" install -q --no-index --no-deps --find-links "$WHEELS" -r "/tmp/prune-$name.txt"
    local got=fails
    if (cd /tmp && "$venv/bin/python" -I "$CHECK" > "/tmp/prune-$name.log" 2>&1); then got=works; fi
    echo "$name: $got without [$*]"
    if [ "$got" != "$expect" ]; then
        echo "  expected it to $expect; last lines:" && tail -n 5 "/tmp/prune-$name.log"
        mismatches=$((mismatches + 1))
    fi
}

variant works all
variant works no-pypdfium2 pypdfium2
variant works no-fpdf2 pypdfium2 fpdf2 uharfbuzz
variant fails no-img2pdf pypdfium2 img2pdf
exit "$mismatches"
