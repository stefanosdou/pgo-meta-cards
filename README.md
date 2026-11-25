# pgo-meta-cards

Product cards (1080x1080) for a Meta catalog, built from public store data, and the supplementary feed that points Meta to them.

The store, its shop pages and its main product feed are not changed. Meta only reads `feed/supplementary.csv`, which replaces the image of the products listed in it.

## How it works

1. `code/fetch.py` reads the in-stock products from the public WooCommerce Store API.
2. `code/classify.py` puts every product in one card family and extracts the facts a card may show (size, weight range, pieces, ml, capsules, ingredient). A fact is shown only when the product title or store category states it.
3. `code/build.py` renders missing cards, checks them and writes `cards/manifest.json` and `feed/supplementary.csv`.
4. `.github/workflows/feed.yml` runs the three steps every hour and commits the result. GitHub Pages serves the images and the CSV.

## Switches

| File | Effect |
|---|---|
| `supp_count.txt` | How many products of `supp_order.txt` are in the CSV. `0` = none. |
| `supp_order.txt` | Rollout order, one product id per line. |
| `switches/concepts.json` | Card design per family. |
| `switches/holdout.txt` | Ids that keep the store photo (control half of a test). |
| `PAUSE` (empty file in the repo root) | Empties the CSV: every product goes back to the store photo. |

## Safety

- A product whose photo, title or facts changed leaves the CSV until its new card exists. File names carry a hash of the inputs, so a new card always has a new URL.
- A card where the product covers too little of the image is not published.
- No secrets are stored here and none are needed.

## Font

`fonts/bold.ttf` is Noto Sans Bold, SIL Open Font License 1.1 (`fonts/OFL.txt`).
