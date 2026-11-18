# caseyag.github.io

Casey Aguilar-Gervase's portfolio site, built with [Quarto](https://quarto.org) and published to https://caseyag.co (custom domain; https://caseyag.github.io redirects there). The `CNAME` file keeps the domain set on every publish, so don't delete it.

## Preview locally

Requires Quarto 1.10.x. The PATH line below is for the Quarto bundled with Positron on macOS.

    export PATH="/Applications/Positron.app/Contents/Resources/app/quarto/bin:$PATH"
    quarto preview

## Publish

Push to `main`. The GitHub Action renders the site and deploys it to the `gh-pages` branch.

Before pushing, run the checks:

    quarto render && python3 tests/check_site.py

`quarto preview` does not run the checks. `python3 tests/check_site.py NAME` runs one check. The `work_listing` and `talks_listing` checks name the example items, so update them if those items are renamed or removed.

Before launch, also run `python3 tests/check_site.py --launch no_todo_markers`. It fails while any `[TODO]` marker remains.

## Add an app or a talk

1. Copy an existing item folder, for example `work/biomarker-explorer/` to `work/my-new-app/`.
2. Edit the front matter at the top of `index.qmd`: `title`, `description`, `categories`, `order` (its position in the Work grid; talks use `date` instead), `image: thumbnail.png` and `image-alt:`. Also repeat the alt text under `open-graph: image-alt:` and `twitter-card: image-alt:`, or link previews show the site-wide alt text.
3. Replace the thumbnail with a 1600x900 PNG. A cropped screenshot works well. To make a title card instead, draw it as `thumbnail.svg`, then convert it:

       qlmanage -t -s 1600 -o "$TMPDIR" thumbnail.svg
       sips -c 900 1600 "$TMPDIR/thumbnail.svg.png" --out thumbnail.png

4. Write the page and push.

## Add a section (packages, case studies, writing)

1. Create a folder such as `packages/` with an `index.qmd` listing page. Copy `work/index.qmd` and change the title and subtitle. Keep `image-height: auto` in the listing.
2. Add a navbar entry in `_quarto.yml` under `website.navbar.right`.
3. Add a tile to the `<nav class="tiles">` block in `index.qmd`.

For writing, use `type: default` in the listing and add `feed: true` to get an RSS feed.

## Photos

Never commit a photo straight from a phone. It contains GPS location. For an iPhone HEIC, convert first:

    sips -s format jpeg --resampleHeightWidthMax 1200 IN.HEIC --out "$TMPDIR/IN.jpg"

Rotate the photo before stripping, because stripping removes the orientation metadata. Then strip the metadata, check the result, and keep photos in `images/`:

    python3 tools/strip_metadata.py IN.jpg images/OUT.jpg

The `images_have_no_metadata` check fails if any metadata remains.

## Social card

`images/social-card.png` is the site-wide link preview. Edit `images/social-card.svg`, then regenerate it:

    qlmanage -t -s 1200 -o "$TMPDIR" images/social-card.svg
    sips -c 630 1200 "$TMPDIR/social-card.svg.png" --out images/social-card.png

Item pages keep their own `thumbnail.png`.

## Resume PDF

`resume/Casey-Aguilar-Gervase-Resume.pdf` must be the web copy without the phone number. When you replace it, confirm that, then update `APPROVED_RESUME_SHA256` in `tests/check_site.py` with the output of:

    shasum -a 256 resume/Casey-Aguilar-Gervase-Resume.pdf

## Theme

Colors and fonts live in `theme.scss`. The site is light-only for now. `theme-dark.scss` holds dark tokens for later; it is not used, but the contrast checks still cover it, and `_quarto.yml` has a comment showing how to turn dark mode back on. Layout and components live in `theme-rules.scss` and use only those tokens. `tests/check_site.py` fails if a text color drops below WCAG AA contrast. Pandoc drops a CSS class named `section`, so the spacing class is `.page-section`.
