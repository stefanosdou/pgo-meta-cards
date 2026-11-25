"""
Hourly build: render missing cards, check them, write the supplementary feed.

  cards/<id>-<hash>.jpg     one card per product. The hash covers photo, title, shown facts, concept and
                            design version, so any change reaches Meta as a new image URL.
  cards/manifest.json       what each card was built from, and its QC result
  feed/supplementary.csv    id,image_link (+ optional catalog fields). This is what Meta reads.

Safety rules (same as the reference build):
  - match check: a product whose photo, title or facts changed leaves the CSV until its new card exists
  - QC: a card where the product covers too little of the tile is never published
  - rollout: only the first supp_count.txt ids of supp_order.txt are in the CSV
  - test: ids in switches/holdout.txt keep the site photo (control half)
  - a file named PAUSE in the repo root empties the CSV: every product goes back to the site photo

Usage:
  python -I code/build.py                 normal run (limits from client.config.json)
  python -I code/build.py --max-cards 20  render at most 20 new cards
  python -I code/build.py --dry           no files written, only the summary
"""
import argparse, csv, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cards

ROOT, CFG = cards.ROOT, cards.CFG
QC_MIN_SHARE = 0.10   # product must cover at least 10% of the photo area of the card


def read_lines(path):
    p = os.path.join(ROOT, path)
    return [l.strip() for l in open(p, encoding="utf-8")] if os.path.exists(p) else []


def concept_for(fam, switches):
    return switches.get(fam) or switches.get("default")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-cards", type=int, default=CFG["rollout"]["cards_per_run"])
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    prods = json.load(open(os.path.join(ROOT, "data", "classified.json"), encoding="utf-8"))["products"]
    sw_path = os.path.join(ROOT, "switches", "concepts.json")
    switches = json.load(open(sw_path, encoding="utf-8")) if os.path.exists(sw_path) else {}
    holdout = set(read_lines("switches/holdout.txt"))
    order = [x for x in read_lines("supp_order.txt") if x]
    count = int((read_lines("supp_count.txt") or ["0"])[0] or 0)
    paused = os.path.exists(os.path.join(ROOT, "PAUSE"))
    man_path = os.path.join(ROOT, "cards", "manifest.json")
    manifest = json.load(open(man_path, encoding="utf-8")) if os.path.exists(man_path) else {}
    base = (CFG.get("pages_base_url") or "").rstrip("/")

    eligible = {str(p["id"]): p for p in prods if not p["skip"] and p["family"] not in CFG["exclude_families"]}
    if not order:  # no rollout order yet: catalog order, so a first local run still works
        order = list(eligible)
    live_ids = [i for i in order[:count] if i in eligible and i not in holdout]
    # Cards are rendered for the whole order, ahead of the rollout, so raising supp_count.txt
    # puts products live at once. Only live_ids ever reach the CSV.
    render_ids = [i for i in order if i in eligible and i not in holdout]
    render_ids += [i for i in eligible if i not in set(render_ids) and i not in holdout]

    rendered = stale = failed = 0
    os.makedirs(os.path.join(ROOT, "cards"), exist_ok=True)
    for pid in render_ids:
        p = eligible[pid]
        concept = concept_for(p["family"], switches)
        if not concept:
            continue
        h = cards.input_hash(p, concept)
        m = manifest.get(pid)
        if m and m["hash"] == h:
            continue
        if m:
            stale += 1          # match check failed: old card must not be served any more
        if rendered >= a.max_cards or a.dry:
            if m and not a.dry:
                manifest.pop(pid)
            continue
        try:
            im = cards.render(p, concept)
            share = cards.product_share(im.crop((0, 76, 1080, 900)))
            fn = f"cards/{pid}-{h}.jpg"
            im.save(os.path.join(ROOT, fn), quality=88, optimize=True)
            manifest[pid] = {"hash": h, "file": fn, "concept": concept, "family": p["family"], "share": round(share, 3),
                             "qc": share >= QC_MIN_SHARE, "built": time.strftime("%Y-%m-%dT%H:%M:%S"),
                             "from": {"image": p["image"], "name": p["name"], "price": p["price"]}}
            rendered += 1
        except Exception as e:  # a broken photo must not stop the run
            failed += 1
            manifest.pop(pid, None)
            print("render failed", pid, e)

    rows = []
    if not paused:
        for pid in live_ids:
            p, m = eligible[pid], manifest.get(pid)
            concept = concept_for(p["family"], switches)
            if not (m and concept and m["qc"] and m["hash"] == cards.input_hash(p, concept)):
                continue
            row = {"id": pid, "image_link": f"{base}/{m['file']}"}
            if CFG.get("enrich_catalog_fields"):
                row.update({"product_type": p["family_label"], "custom_label_0": p["family"], "brand": p["facts"].get("brand", "")})
            rows.append(row)

    print(f"eligible {len(eligible)} | cards ready {len(manifest)} | in rollout {len(live_ids)} | rendered now {rendered} | changed on site {stale} | failed {failed} | "
          f"in CSV {len(rows)} | holdout {len(holdout)} | paused {paused}")
    if a.dry:
        return
    if not base and rows:
        print("NOTE: pages_base_url is empty in client.config.json, so image_link is not a public URL yet.")
    json.dump(manifest, open(man_path, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    os.makedirs(os.path.join(ROOT, "feed"), exist_ok=True)
    fields = ["id", "image_link"] + (["product_type", "custom_label_0", "brand"] if CFG.get("enrich_catalog_fields") else [])
    with open(os.path.join(ROOT, "feed", "supplementary.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    # remove card files that no manifest entry points to
    keep = {os.path.basename(m["file"]) for m in manifest.values()}
    for f in os.listdir(os.path.join(ROOT, "cards")):
        if f.endswith(".jpg") and f not in keep:
            os.remove(os.path.join(ROOT, "cards", f))


if __name__ == "__main__":
    main()
