"""Bring newly added imagery into the repository.

    python scripts/import_seed_photos.py --from "E:/FASHION/FASHION"
    python scripts/import_seed_photos.py --from "E:/FASHION/FASHION" --dry-run

**Why a script and not a copy command.** Three things have to happen
on the way in, and none of them are `cp`:

1. **Filenames are rewritten.** The originals are scraped captions -
   `#pirsing #aesthetic.jpg`, a 150-character Portuguese product
   title, several with emoji. They break on case-insensitive
   filesystems, in URLs, and against this repository's own rule that
   asset names are kebab-case with no special characters.

2. **The original name is kept anyway.** Those captions are the only
   text attached to these pictures, and a seeder that wants to write
   a plausible caption or derive a tag has nowhere else to look. They
   go into `manifest.json` beside the files rather than being thrown
   away with the rename.

3. **Duplicates are dropped by content.** The same picture appears in
   more than one folder under different scraped names, and a feed
   with the same photograph twice makes deduplication look broken
   when it is working.

**The folder is the label, never the filename.** Verified by looking:
a file called "Take your love for #anime to the next level with our
#AnimeLiveWallpaper #App!" is a photograph of a mouth and a set of
nails. The scraped captions describe whatever ad the picture was
lifted from, so they are kept as text and trusted for nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import unicodedata
from pathlib import Path

from _assets import seed_photos

#: Source folder to the folder it lands in here.
#:
#: `PORTRAITS` becomes `beauty` on the evidence rather than the label:
#: the folder is lips, nails and makeup close-ups, not portraits of
#: people, and calling it `portraits` would have every one of them
#: tagged as somebody's outfit photograph.
FOLDERS: dict[str, str] = {
    "ACCESSORIES": "accessories",
    "FURNITURE": "furniture",
    "PORTRAITS": "beauty",
}

#: Pictures filed under the wrong folder at the source.
#:
#: These twelve arrived in `OCCATION OUTFITS` and are beds, sofas and
#: sectionals. Left where they were found they would be seeded as
#: occasion-wear and tagged `weddingguest`, which is not a
#: cosmetic problem: the whole point of adding this imagery is to give
#: the recommender honest signal to rank, and a sofa labelled as a
#: wedding guest outfit is noise aimed straight at it.
MISFILED: dict[str, str] = {
    "OCCATION OUTFITS": "furniture",
}
MISFILED_MARKERS = (
    "bedroom",
    "bed ",
    "bed.",
    "sofa",
    "sectional",
    "chaise",
    "living room",
    "platform bed",
    "headboard",
    "upholstered",
)

PICTURES = {".jpg", ".jpeg", ".png", ".webp"}

#: Long enough to stay readable, short enough for any filesystem.
MAX_STEM = 60


def slug(name: str) -> str:
    """A scraped caption as a filename this repository would accept."""
    # Strip accents rather than dropping the letters: "Révéler" should
    # become "reveler", not "rvler".
    flat = unicodedata.normalize("NFKD", name)
    flat = flat.encode("ascii", "ignore").decode("ascii")
    flat = flat.lower()
    flat = re.sub(r"[^a-z0-9]+", "-", flat).strip("-")
    flat = re.sub(r"-{2,}", "-", flat)
    if not flat:
        flat = "picture"
    return flat[:MAX_STEM].strip("-")


def looks_misfiled(name: str) -> bool:
    low = name.lower()
    return any(marker in low for marker in MISFILED_MARKERS)


def pictures_in(folder: Path) -> list[Path]:
    return sorted(
        p
        for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in PICTURES
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="source", required=True)
    parser.add_argument(
        "--into",
        default=str(seed_photos()),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source = Path(args.source)
    into = Path(args.into)
    if not source.is_dir():
        print(f"no such source folder: {source}")
        return 2

    # Content hashes of everything already here, so re-running adds
    # only what is new and a picture that arrived twice lands once.
    seen: dict[str, Path] = {}
    if into.is_dir():
        for existing in into.rglob("*"):
            if existing.is_file() and existing.suffix.lower() in PICTURES:
                seen[hashlib.sha256(existing.read_bytes()).hexdigest()] = existing
    print(f"{len(seen)} pictures already in {into}")

    manifest_path = into / "manifest.json"
    manifest: dict[str, dict[str, str]] = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    jobs: list[tuple[Path, str]] = []
    for folder_name, destination in FOLDERS.items():
        folder = source / folder_name
        if not folder.is_dir():
            print(f"  (no {folder_name} at the source, skipping)")
            continue
        for picture in pictures_in(folder):
            jobs.append((picture, destination))

    for folder_name, destination in MISFILED.items():
        folder = source / folder_name
        if not folder.is_dir():
            continue
        for picture in pictures_in(folder):
            if looks_misfiled(picture.name):
                jobs.append((picture, destination))

    added = skipped = 0
    per_folder: dict[str, int] = {}
    for picture, destination in jobs:
        digest = hashlib.sha256(picture.read_bytes()).hexdigest()
        if digest in seen:
            skipped += 1
            continue
        seen[digest] = picture

        target_dir = into / destination
        stem = slug(picture.stem)
        target = target_dir / f"{stem}{picture.suffix.lower()}"
        # Two different pictures can slug to the same name; the hash
        # is what makes the second one addressable.
        if target.exists() or str(target) in {str(v) for v in seen.values()}:
            target = target_dir / f"{stem}-{digest[:8]}{picture.suffix.lower()}"

        if not args.dry_run:
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(picture, target)
        manifest[f"{destination}/{target.name}"] = {
            # The scraped caption, kept because it is the only text
            # these pictures carry. Trusted for nothing: it describes
            # whatever advert the picture was lifted from.
            "scraped_title": picture.stem,
            "source_folder": picture.parent.name,
            "sha256": digest,
        }
        added += 1
        per_folder[destination] = per_folder.get(destination, 0) + 1

    if not args.dry_run:
        into.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    print(f"\n{'would add' if args.dry_run else 'added'} {added}, skipped {skipped} duplicates")
    for name, count in sorted(per_folder.items()):
        print(f"  {name:14s} {count:>4}")
    if not args.dry_run:
        print(f"\nmanifest: {manifest_path} ({len(manifest)} entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
