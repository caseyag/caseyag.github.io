#!/usr/bin/env python3
"""Checks for the rendered site. Run after `quarto render`.

Usage:
  python3 tests/check_site.py            # all checks
  python3 tests/check_site.py NAME ...   # only the named checks
  python3 tests/check_site.py --launch   # all checks plus pre-launch checks
"""
import hashlib
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from html import unescape as html_unescape
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "_site"
CHECKS = []
LAUNCH_CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


def launch(fn):
    LAUNCH_CHECKS.append(fn)
    return fn


def page(rel):
    path = SITE / rel
    assert path.exists(), f"missing page {rel}"
    return path.read_text(encoding="utf-8")


class Refs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []
        self.ids = set()
        self.classes = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.add(attrs["id"])
            self.classes[attrs["id"]] = (attrs.get("class") or "").split()
        for key in ("href", "src"):
            if attrs.get(key):
                self.hrefs.append(attrs[key])


def parse(html):
    parser = Refs()
    parser.feed(html)
    return parser


# --- checks ---------------------------------------------------------------

@check
def home_has_title():
    html = page("index.html")
    assert "<title>Casey Aguilar-Gervase" in html, "homepage <title> should start with Casey Aguilar-Gervase"


@check
def navbar_links():
    nav = re.search(r"<nav\b.*?</nav>", page("index.html"), re.S)
    assert nav, "index.html has no <nav> element"
    navbar_html = nav.group(0)
    # Quarto keeps .qmd for pages that don't exist yet; internal_links_resolve reports any .qmd href that stays unresolved.
    hrefs = [re.sub(r"\.qmd(?=#|$)", ".html", h) for h in parse(navbar_html).hrefs]
    for target in (
        "work/index.html",
        "talks/index.html",
        "resume/index.html",
        "about/index.html",
        "https://github.com/caseyag",
        "https://www.linkedin.com/in/casey-aguilar-gervase/",
    ):
        assert any(h.endswith(target) for h in hrefs), f"navbar missing link to {target}"


@check
def docs_not_published():
    assert not (SITE / "docs").exists(), "docs/ (specs and plans) must not be rendered into the site"


# Tokens must stay 6-digit hex literals; aliases or short hex make the check report the token as missing.
def hex_tokens(path):
    text = path.read_text(encoding="utf-8")
    return {m.group(1): m.group(2) for m in re.finditer(r"^\$([\w-]+):\s*(#[0-9A-Fa-f]{6})\s*;", text, re.M)}


def luminance(hex_color):
    def channel(value):
        value = value / 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# (text token, background token) pairs the design actually uses
TEXT_PAIRS = [
    ("ink", "paper"),
    ("ink", "sage"),
    ("on-accent", "magenta"),
    ("slate", "paper"),
    ("slate", "sage"),
    ("muted", "paper"),
    ("link", "paper"),
    ("link", "sage"),
    ("muted", "sage"),
]


@check
def theme_contrast():
    for name in ("theme.scss", "theme-dark.scss"):
        path = ROOT / name
        assert path.exists(), f"missing {name}"
        tokens = hex_tokens(path)
        for fg, bg in TEXT_PAIRS:
            assert fg in tokens and bg in tokens, f"{name}: missing ${fg} or ${bg}"
            ratio = contrast(tokens[fg], tokens[bg])
            assert ratio >= 4.5, f"{name}: ${fg} on ${bg} is {ratio:.2f}:1, needs 4.5:1"


def bootstrap_css_files():
    css_files = sorted((SITE / "site_libs" / "bootstrap").glob("bootstrap*.min.css"))
    assert css_files, "no compiled Bootstrap CSS in _site/site_libs/bootstrap"
    return css_files


@check
def fonts_in_css():
    for path in bootstrap_css_files():
        css = path.read_text(encoding="utf-8")
        assert re.match(r'@import\s*(url\()?["\']?https://fonts\.googleapis\.com/[^;]*Fraunces', css), \
            f"{path.name} must start with the Google Fonts @import that includes Fraunces"
        for font in ("Inter", "JetBrains"):
            assert font in css, f"{path.name} does not reference {font}"


# Rules from Bootstrap/Quarto components this site never renders (buttons, forms,
# dashboards, kbd, etc.). Their stock greys are allowed; everything else is not.
UNUSED_GREY_SELECTORS = re.compile(
    r"\.blockquote-footer|\.table-light|file-selector-button|\.form-|\.input-group-text"
    r"|\.btn-(?:secondary|light|outline-(?:secondary|light)|link)\b|\.btn\.btn-quarto|\.dropdown-menu|\.pagination|\.list-group"
    r"|\.text-(?:secondary|light)|\.bg-(?:secondary|light)|\.quarto-dashboard"
    r"|column-screen-inset-shaded|^kbd|code a:any-link"
)


@check
def compiled_css_no_bootstrap_greys():
    for path in bootstrap_css_files():
        css = re.sub(r"\s+", "", path.read_text(encoding="utf-8")).lower()
        assert "rgba(233,236,239" not in css, f"{path.name}: stock Bootstrap rgba(233,236,239,...) leaked"
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"([^{}]*)\{([^{}]*)\}", text):
            selector = m.group(1).strip()
            if UNUSED_GREY_SELECTORS.search(selector):
                continue
            for decl in m.group(2).split(";"):
                prop = decl.split(":", 1)[0].strip()
                if prop.startswith("--"):
                    continue  # palette variables, only matter if a rule uses them
                if re.search(r"#6c757d|#f8f9fa|rgba\(233,\s*236,\s*239", decl, re.I):
                    raise AssertionError(f"{path.name}: stock grey in `{selector[:80]}`: {decl.strip()}")


def blend(rgba, base_hex):
    r, g, b, a = rgba
    base = [int(base_hex[i:i + 2], 16) for i in (1, 3, 5)]
    mixed = [round(c * a + bc * (1 - a)) for c, bc in zip((r, g, b), base)]
    return "#{:02X}{:02X}{:02X}".format(*mixed)


@check
def highlighter_contrast():
    for name in ("theme.scss", "theme-dark.scss"):
        text = (ROOT / name).read_text(encoding="utf-8")
        tokens = hex_tokens(ROOT / name)
        m = re.search(r"^\$hl-band:\s*rgba\(\s*(\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\s*\)\s*;", text, re.M)
        if m:
            rgba = (int(m.group(1)), int(m.group(2)), int(m.group(3)), float(m.group(4)))
            for bg in ("paper", "sage"):
                mixed = blend(rgba, tokens[bg])
                ratio = contrast(tokens["ink"], mixed)
                assert ratio >= 4.5, f"{name}: $ink on highlighter over ${bg} is {ratio:.2f}:1, needs 4.5:1"
        else:
            assert re.search(r"^\$hl-band:\s*\$magenta\s*;", text, re.M), f"{name}: unrecognised $hl-band"
            ratio = contrast(tokens["ink"], tokens["magenta"])
            assert ratio >= 4.5, f"{name}: $ink on $magenta highlighter is {ratio:.2f}:1, needs 4.5:1"


def assert_img_alts(html, name):
    imgs = re.findall(r"<img\b[^>]*>", html)
    assert imgs, f"{name} has no images"
    for tag in imgs:
        assert re.search(r'\balt="[^"]+"', tag), f"{name}: img without alt text: {tag}"


@check
def work_listing():
    html = page("work/index.html")
    for slug in ("biomarker-explorer", "report-generator", "app-refactor", "handsome-table"):
        assert f"{slug}/index.html" in html, f"Work listing should link to {slug}"
    assert "thumbnail.png" in html, "Work listing should use the PNG thumbnail"
    assert_img_alts(html, "work/index.html")
    demo = page("work/biomarker-explorer/index.html")
    assert "https://caseya-g.shinyapps.io/biomarker-explorer/" in demo, "Biomarker Explorer should link to its live demo"
    table = page("work/handsome-table/index.html")
    assert 'src="demo/index.html"' in table, "Handsome Table should embed its live demo"
    assert "../../talks/design-of-everyday-shiny-apps/index.html" in table, "Handsome Table should link to the talk"


@check
def talks_listing():
    html = page("talks/index.html")
    assert "design-of-everyday-shiny-apps/index.html" in html, "Talks listing should link to Design of Everyday Apps"
    assert "thumbnail.png" in html, "Talks listing should use the PNG thumbnail"
    assert_img_alts(html, "talks/index.html")
    item = page("talks/design-of-everyday-shiny-apps/index.html")
    assert "https://github.com/caseyag/Posit-Conf-25" in item, "talk page should link to the talk repo"
    assert "../../work/handsome-table/index.html" in item, "talk page should link to Handsome Table"


@check
def og_images_not_svg():
    for path in SITE.rglob("*.html"):
        html = path.read_text(encoding="utf-8")
        for tag in re.findall(r"<meta\b[^>]*>", html):
            if 'property="og:image"' in tag:
                m = re.search(r'content="([^"]*)"', tag)
                assert m and not m.group(1).lower().endswith(".svg"), f"{path.relative_to(SITE)}: og:image is SVG"


@check
def home_hero():
    html = page("index.html")
    assert "Data deserves apps people" in html, "hero headline missing"
    assert '<span class="hl">actually</span>' in html, "'actually' should carry the highlighter class"
    assert "Data Scientist, R Shiny Specialist &amp; UI/UX Designer" in html, "hero label missing"


@check
def home_sections():
    refs = parse(page("index.html"))
    assert "contact" in refs.ids, "homepage missing #contact"
    assert "featured" not in refs.ids, "the Featured section was removed from the homepage"
    assert "about" not in refs.ids, "About lives on its own page (about/index.html), not the homepage"
    assert any(h.endswith("about/index.html") for h in refs.hrefs), "homepage should link to the About page"
    assert "mailto:97caguilar@gmail.com" in refs.hrefs, "homepage needs an email link"
    html = page("index.html")
    assert 'role="main"' in html or "<main" in html, "homepage needs a main landmark"


@check
def about_page():
    refs = parse(page("about/index.html"))
    for section_id in ("about", "dogs-heading", "contact"):
        assert section_id in refs.ids, f"about page missing #{section_id}"
    assert "page-section" in refs.classes.get("about", []), "#about should have class page-section"
    assert "mailto:97caguilar@gmail.com" in refs.hrefs, "about page needs an email link"
    html = page("about/index.html")
    assert 'role="main"' in html or "<main" in html, "about page needs a main landmark"
    assert "What I work on" in html, "about page should list what I work on"
    assert_img_alts(html, "about/index.html")



@check
def about_photos():
    hrefs = parse(page("about/index.html")).hrefs
    for photo in ("images/headshot.jpg", "images/dog-mason.jpg", "images/dog-tony.jpg", "images/dogs-walk.jpg"):
        assert f"../{photo}" in hrefs, f"about page should show {photo}"
        assert (SITE / photo).exists(), f"{photo} not copied into the site"


sys.path.insert(0, str(ROOT / "tools"))
import strip_metadata  # noqa: E402


def jpeg_problems(data):
    """Return reasons this JPEG still carries metadata or trailing data."""
    problems = []
    end = 0
    try:
        for marker, _, end in strip_metadata.walk_segments(data):
            if strip_metadata.is_metadata(marker):
                problems.append(f"segment FF{marker:02X}")
    except ValueError as err:
        return problems + [str(err)]
    if end != len(data):
        problems.append("bytes after the first EOI")
    return problems


def _synthetic_jpeg(extra_segments=b""):
    jfif = b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sos = b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00"
    return b"\xff\xd8" + jfif + extra_segments + sos + b"\x12\xff\x00\x34" + b"\xff\xd9"


@check
def stripper_self_test():
    clean = _synthetic_jpeg()
    assert jpeg_problems(clean) == [], "a clean synthetic JPEG should pass"
    exif = b"\xff\xe1\x00\x0cExif\x00\x00GPS!"
    cases = {
        "trailer containing FFD9": clean + b"\x00\x00ftypmp42 GPS \xff\xd9 more bytes",
        "appended JPEG with EXIF": clean + _synthetic_jpeg(exif),
        "EXIF in the primary image": _synthetic_jpeg(exif),
    }
    for name, data in cases.items():
        assert jpeg_problems(data), f"jpeg_problems should flag: {name}"
        stripped = strip_metadata.strip(data)
        assert stripped == clean, f"strip() should return just the clean primary image: {name}"
        assert b"GPS" not in stripped and stripped.count(b"\xff\xd8") == 1, f"leftover trailer: {name}"
        assert jpeg_problems(stripped) == [], f"stripped output should pass: {name}"
    assert "truncated JPEG" in jpeg_problems(clean[:-2] + b"\xff\xff"), "fill-byte ending should be truncated"


@check
def images_have_no_metadata():
    leaky = []
    for img in list(SITE.rglob("*.jpg")) + list(SITE.rglob("*.jpeg")):
        problems = jpeg_problems(img.read_bytes())
        if problems:
            leaky.append(f"{img.relative_to(SITE)} ({'; '.join(problems)})")
    assert not leaky, "run tools/strip_metadata.py on: " + ", ".join(leaky)


# Phone-free web copy approved by Casey; update deliberately when replacing the PDF
# (it must never include the phone number).
APPROVED_RESUME_SHA256 = "5e3c55feabe455e80847163602569df73cb47d870337484e302bb39bd258f8e8"


@check
def resume_page():
    html = page("resume/index.html")
    for title in (
        "Kardigan",
        "Principal Shiny Developer",
        "Senior Shiny Developer",
        "Data Visualization Engineer / Data Scientist",
        "Associate, Programming &amp; Biostatistics",
        "Specialist, Programming",
    ):
        assert title in html, f"resume missing role: {title}"
    assert "Casey-Aguilar-Gervase-Resume.pdf" in html, "resume needs a Download PDF link"
    pdf = SITE / "resume" / "Casey-Aguilar-Gervase-Resume.pdf"
    assert pdf.exists(), "resume PDF not copied into the site"
    roles = html.count('class="role"')
    assert roles == 6, f"expected 6 roles, found {roles}"
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    assert digest == APPROVED_RESUME_SHA256, "resume PDF does not match the approved phone-free copy"


SKIP_REF = re.compile(r"^(https?:|mailto:|tel:|data:|javascript:|#|//)")


@check
def internal_links_resolve():
    broken = []
    for html_file in SITE.rglob("*.html"):
        for ref in parse(html_file.read_text(encoding="utf-8")).hrefs:
            if SKIP_REF.match(ref):
                continue
            path_part, _, fragment = ref.partition("#")
            where = f"{html_file.relative_to(SITE)} -> {ref}"
            if path_part.split("?")[0].endswith(".qmd"):
                broken.append(f"{where} (unresolved Quarto link)")
                continue
            path_part = unquote(path_part.split("?")[0])
            if path_part.startswith("/"):
                target = (SITE / path_part.lstrip("/")).resolve()
            else:
                target = (html_file.parent / path_part).resolve()
            if not target.is_relative_to(SITE.resolve()):
                broken.append(f"{where} (outside site)")
                continue
            if target.is_dir():
                target = target / "index.html"
            if not target.exists():
                broken.append(where)
            elif fragment and target.suffix == ".html":
                if fragment not in parse(target.read_text(encoding="utf-8")).ids:
                    broken.append(f"{where} (no #{fragment})")
    assert not broken, "broken links:\n  " + "\n  ".join(broken)


def social_metas(html):
    metas = {}
    for tag in re.findall(r"<meta\b[^>]*>", html):
        key = re.search(r'(?:property|name)="((?:og|twitter):[^"]*)"', tag)
        content = re.search(r'content="([^"]*)"', tag)
        if key and content:
            metas[key.group(1)] = content.group(1)
    return metas


SITE_WIDE_ALT = "Casey Aguilar-Gervase, Data Scientist, R Shiny Specialist & UI/UX Designer"


@check
def open_graph():
    site_url = "https://caseyag.co/"
    for rel in ("index.html", "about/index.html", "work/index.html", "talks/index.html", "resume/index.html"):
        metas = social_metas(page(rel))
        for prop in ("og:title", "og:description", "og:image", "og:image:alt"):
            assert metas.get(prop), f"{rel} missing {prop} meta tag"
        assert not metas["og:image"].lower().endswith(".svg"), f"{rel}: og:image is SVG"
        assert metas["og:image"].startswith(site_url), f"{rel}: og:image should be an absolute site URL"
        assert (SITE / metas["og:image"][len(site_url):]).exists(), f"{rel}: og:image file not in site: {metas['og:image']}"
        assert metas.get("twitter:image") == metas["og:image"], f"{rel}: twitter:image should equal og:image"
        if rel == "index.html":
            assert metas["og:image"].endswith("images/social-card.png"), "homepage og:image should be images/social-card.png"
    for path in SITE.rglob("*.html"):
        metas = social_metas(path.read_text(encoding="utf-8"))
        if "og:image" in metas and "twitter:image" in metas:
            assert metas["twitter:image"] == metas["og:image"], f"{path.relative_to(SITE)}: twitter:image differs from og:image"
        if "og:image" in metas and not metas["og:image"].endswith("images/social-card.png"):
            for alt_key in ("og:image:alt", "twitter:image:alt"):
                if alt_key in metas:
                    assert html_unescape(metas[alt_key]) != SITE_WIDE_ALT, (
                        f"{path.relative_to(SITE)}: {alt_key} is the site-wide alt text; add "
                        "`open-graph: image-alt:` and `twitter-card: image-alt:` to this item's front matter"
                    )


@launch
def no_todo_markers():
    hits = [str(p.relative_to(SITE)) for p in SITE.rglob("*.html") if "[TODO" in p.read_text(encoding="utf-8")]
    assert not hits, "replace [TODO] markers before launch: " + ", ".join(hits)


@check
def light_only():
    # Dark mode is off for now; see the comment in _quarto.yml to re-enable it.
    assert not list((SITE / "site_libs" / "bootstrap").glob("bootstrap-dark*.css")), "dark theme CSS is being built"
    assert "quarto-color-scheme-toggle" not in page("index.html"), "navbar still has a light/dark toggle"


@check
def custom_domain():
    cname = SITE / "CNAME"
    assert cname.exists(), "CNAME missing from _site; GitHub Pages would drop the custom domain"
    assert cname.read_text().strip() == "caseyag.co", "CNAME should contain caseyag.co"


# --- runner (keep at the bottom; add new checks above this line) ----------

def main(args):
    if not SITE.is_dir():
        print("FAIL: _site/ is missing; run quarto render first")
        sys.exit(1)
    known = {f.__name__ for f in CHECKS + LAUNCH_CHECKS}
    names = [a for a in args if not a.startswith("--")]
    for a in args:
        if a.startswith("--") and a != "--launch":
            print(f"unknown option: {a}")
            sys.exit(2)
    for n in names:
        if n not in known:
            print(f"unknown check: {n} (known: {', '.join(sorted(known))})")
            sys.exit(2)
    checks = CHECKS + LAUNCH_CHECKS if "--launch" in args or names else CHECKS
    failed = 0
    for fn in checks:
        if names and fn.__name__ not in names:
            continue
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as err:
            failed += 1
            print(f"FAIL {fn.__name__}: {err}")
        except Exception as err:
            failed += 1
            print(f"ERROR {fn.__name__}: {type(err).__name__}: {err}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
