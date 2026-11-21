"""
Give photographers portfolio images so visual search has something to match.

    python manage.py seed_portfolio                     # generated sample images
    python manage.py seed_portfolio --from D:/photos    # your own photos
    python manage.py seed_portfolio --per-photographer 6

WHY THIS EXISTS
---------------
"Find Similar Style" compares a buyer's reference photo against portfolio
images. `seed_data` creates no portfolio images, so on a fresh database every
visual search answers "No style matches found".

WHERE THE IMAGES COME FROM
--------------------------
* `--from DIR` — real JPEG / PNG / WebP photos, shared round-robin across
  photographers. The file name becomes the caption ("mehndi-night.jpg" →
  "Mehndi night"), which also feeds the style classifier. Use this for a demo.
* Otherwise — generated sample images in seven looks (warm desi wedding,
  moody, bright & airy, cinematic, studio, candid). They differ in exactly
  what the embedding measures — colour, brightness, contrast, texture,
  framing — so matching behaves realistically, but they are placeholders.

Every image goes through `portfolio.services.upload_image`, the same path as an
upload from the app: metadata stripped, three renditions, aesthetic analysis
and embedding stored, portfolio score refreshed.

Safe to re-run: a photographer who already has `--per-photographer` images is
skipped.
"""

import io
import mimetypes
import random
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}

# (look, caption, base colours top → bottom, landscape?)
LOOKS = [
    ("desi", "Mehndi night — warm desi wedding colours",
     [(150, 30, 25), (215, 150, 40)], True),
    ("desi", "Baraat stage portrait in red and gold",
     [(120, 20, 30), (230, 170, 60)], False),
    ("moody", "Moody evening portrait in deep shadow",
     [(10, 12, 20), (60, 55, 70)], False),
    ("bright", "Bright airy daylight shoot",
     [(250, 245, 235), (215, 225, 240)], True),
    ("cinematic", "Cinematic wide shot of the venue",
     [(20, 45, 60), (200, 120, 60)], True),
    ("studio", "Studio headshot on a clean backdrop",
     [(200, 200, 205), (170, 170, 175)], False),
    ("candid", "Candid family moment, natural light",
     [(110, 130, 90), (200, 185, 150)], True),
]

# Looks that suit each category, so a wedding photographer's grid reads as one.
CATEGORY_LOOKS = {
    "wedding": ["desi", "desi", "cinematic", "candid", "moody"],
    "mehndi": ["desi", "desi", "bright", "candid"],
    "portrait": ["studio", "moody", "bright", "candid"],
    "fashion": ["studio", "moody", "cinematic", "bright"],
    "event": ["cinematic", "candid", "bright", "desi"],
}


class Command(BaseCommand):
    help = "Add portfolio images to photographers so visual search can match them."

    def add_arguments(self, parser):
        parser.add_argument(
            "--from", dest="source", default=None,
            help="Folder of JPEG/PNG/WebP photos to import instead of generated samples.",
        )
        parser.add_argument(
            "--per-photographer", type=int, default=4,
            help="Images per photographer (default 4, max 20).",
        )
        parser.add_argument("--seed", type=int, default=42, help="Random seed.")

    def handle(self, *args, **options):
        from apps.portfolio.models import PortfolioImage
        from apps.portfolio.services import upload_image
        from apps.profiles import selectors

        per = max(1, min(options["per_photographer"], 20))
        rng = random.Random(options["seed"])
        photos = self._photos(options["source"])

        photographers = list(
            selectors.visible_photographers().prefetch_related("categories").order_by("id")
        )
        added = skipped = failed = 0
        cursor = 0
        for photographer in photographers:
            have = PortfolioImage.objects.filter(
                photographer=photographer, is_deleted=False
            ).count()
            if have >= per:
                skipped += 1
                continue

            category = next(iter(photographer.categories.all()), None)
            for index in range(have, per):
                if photos:
                    upload, caption = self._from_file(photos[cursor % len(photos)])
                    cursor += 1
                else:
                    upload, caption = self._generated(category, rng, index)
                try:
                    upload_image(
                        photographer,
                        image=upload,
                        caption=caption,
                        category=category,
                        is_featured=(index == 0),
                    )
                    added += 1
                except Exception as exc:  # noqa: BLE001 — report and keep going
                    failed += 1
                    self.stderr.write(f"  photographer {photographer.pk}: {exc}")

        self.stdout.write(self.style.SUCCESS(
            f"Portfolio images added: {added} · photographers already filled: "
            f"{skipped} · failed: {failed}"
        ))

    # ─── Sources ────────────────────────────────────────────────────────────
    def _photos(self, source):
        if not source:
            return []
        folder = Path(source)
        if not folder.is_dir():
            raise CommandError(f"Not a folder: {folder}")
        photos = sorted(
            p for p in folder.rglob("*") if p.suffix.lower() in IMAGE_SUFFIXES
        )
        if not photos:
            raise CommandError(f"No JPEG/PNG/WebP photos found in {folder}")
        self.stdout.write(f"Importing from {len(photos)} photos in {folder}")
        return photos

    def _from_file(self, path: Path):
        content_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        upload = SimpleUploadedFile(path.name, path.read_bytes(), content_type=content_type)
        caption = path.stem.replace("-", " ").replace("_", " ").strip().capitalize()
        return upload, caption[:200]

    def _generated(self, category, rng: random.Random, index: int):
        from PIL import Image, ImageDraw, ImageFilter

        slug = (getattr(category, "slug", "") or "").lower()
        preferred = next(
            (looks for key, looks in CATEGORY_LOOKS.items() if key in slug), None
        )
        if preferred:
            wanted = preferred[index % len(preferred)]
            choices = [look for look in LOOKS if look[0] == wanted]
        else:
            choices = LOOKS
        _, caption, (top, bottom), landscape = rng.choice(choices)

        size = (1200, 800) if landscape else (800, 1000)
        image = Image.new("RGB", size)
        draw = ImageDraw.Draw(image)
        jitter = [rng.randint(-18, 18) for _ in range(3)]
        for y in range(size[1]):
            t = y / (size[1] - 1)
            draw.line(
                [(0, y), (size[0], y)],
                fill=tuple(
                    max(0, min(255, int(a + (b - a) * t) + j))
                    for a, b, j in zip(top, bottom, jitter)
                ),
            )
        # Soft subjects and highlights, so images differ in texture and contrast.
        for _ in range(rng.randint(3, 7)):
            w, h = rng.randint(80, 380), rng.randint(80, 380)
            x, y = rng.randint(0, size[0] - w), rng.randint(0, size[1] - h)
            base = top if rng.random() < 0.5 else bottom
            shade = tuple(max(0, min(255, c + rng.randint(-70, 70))) for c in base)
            draw.ellipse([x, y, x + w, y + h], fill=shade)
        image = image.filter(ImageFilter.GaussianBlur(rng.uniform(2, 9)))

        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=88)
        name = f"sample-{rng.randrange(10**8):08d}.jpg"
        return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg"), caption
