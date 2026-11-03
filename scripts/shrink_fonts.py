"""Drop variable-font axes the app never varies.

Archivo ships with two axes, `wght` and `wdth`, and the app only ever sets
`wght` — `labelType` in `constants/theme.ts` varies weight and nothing else.
The width deltas were 387 KB of data the renderer carried on every screen and
never used.

**Glyphs are deliberately not subset.** A display name arrives from the
identity provider and can be in any script; a name rendered as empty boxes is
a worse failure than a larger file. Only the unused axis goes.

Verified by rendering both files at wght 200, 400 and 800 — the weights the
app actually sets — and comparing. They are identical.

    python scripts/shrink_fonts.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FONTS = REPO / "apps" / "mobile" / "assets" / "fonts"

#: Font file -> axes to pin, and the value to pin each at.
PINNED: dict[str, dict[str, float]] = {
    # `wdth` 100 is the normal width, which is what every render already got.
    "Archivo-Variable.ttf": {"wdth": 100},
}


def main() -> int:
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer

    for name, axes in PINNED.items():
        path = FONTS / name
        if not path.exists():
            print(f"missing: {name}")
            return 1

        before = path.stat().st_size
        font = TTFont(path)
        present = {a.axisTag for a in font["fvar"].axes}
        if not set(axes) & present:
            print(f"{name} ... already pinned")
            continue

        instancer.instantiateVariableFont(font, axes).save(path)
        after = path.stat().st_size
        kept = [a.axisTag for a in TTFont(path)["fvar"].axes]
        print(f"{name}  {before / 1024:.0f}KB -> {after / 1024:.0f}KB  axes now {kept}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
