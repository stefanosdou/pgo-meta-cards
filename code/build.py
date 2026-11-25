"""
Hourly build: render missing cards, check them, write the supplementary feed.

  cards/<id>-<hash>.jpg     one card per product. The hash covers photo, title, shown facts, concept and
                            design version, so any change reaches Meta as a new image URL.
  cards/manifest.json       what each card was built from, and its QC result
  feed/supplementary.csv    id,image_link (+ optional catalog fields). This is what Meta reads.

Safety rules:
  - match check: a product whose photo, title or facts changed leaves the CSV until its new card exists
  - QC: a card where the product covers too little of the tile is never published
  - rollout: only the first supp_count.txt ids of supp_order.txt are in the CSV
  - test: ids in switches/holdout.txt keep the site photo (control half)
  - a file named PAUSE in the repo root empties the CSV: every product goes back to the site photo

Automatic rollout: when supp_target.txt holds a number above supp_count.txt, every run raises
supp_count.txt by rollout.ids_per_hour until it reaches the target. Go-live is one number in one file.

Cards are rendered ahead of the rollout for the whole order, photos are downloaded in parallel and the
manifest is saved every 25 cards, so a partial run can be committed and loses nothing if it stops.

Usage:
  python -I code/build.py                 normal run (limits from client.config.json)
  python -I code/build.py --max-cards 20  render at most 20 new cards
  python -I code/build.py --no-step       do not advance the automatic rollout in this run
  python -I code/build.py --dry           no files written, only the summary
"""
import argparse, csv, json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cards

ROOT, CFG = cards.ROOT, cards.CFG
QC_MIN_SHARE = 0.10   # product must cover at least 10% of the photo area of the card
SAVE_EVERY = 25
DOWNLOAD_THREADS = 4  # polite to the store: a few at a time, each photo once (disk cache)
STEP_GAP = 50 * 60    # seconds between two rollout steps


def read_lines(path):
    p = os.path.join(ROOT, path)
    return [l.strip() for l in open(p, encoding="utf-8")] if os.path.exists(p) else []


def first_int(path, default=0):
    l = [x for x in read_lines(path) if x]
    return int(l[0]) if l and l[0].isdigit() else default


def hosting_ok(base, files, sample=12, tries=3):
    """True when a random sample of cards that are already live answers 200 from the public host."""
    import random, urllib.request
    if not files:
        return True
    picks = random.sample(files, min(sample, len(files)))
    for attempt in range(tries):
        bad = 0
        for f in picks:
            try:
                req = urllib.request.Request(f"{base}/{f}", method="HEAD", headers={"User-Agent": "dpa-cards-check"})
                if urllib.request.urlopen(req, timeout=20).status != 200:
                    bad += 1
            except Exception:
                bad += 1
        if bad <= len(picks) // 4:
            return True
        time.sleep(20 * (attempt + 1))
    return False


def write_text(path, text):
    with open(os.path.join(ROOT, path), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-cards", type=int, default=CFG["rollout"]["cards_per_run"])
    ap.add_argument("--no-step", action="store_true")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    prods = json.load(open(os.path.join(ROOT, "data", "classified.json"), encoding="utf-8"))["products"]
    sw_path = os.path.join(ROOT, "switches", "concepts.json")
    switches = json.load(open(sw_path, encoding="utf-8")) if os.path.exists(sw_path) else {}
    concept_for = lambda fam: switches.get(fam) or switches.get("default")
    holdout = set(read_lines("switches/holdout.txt"))
    order = [x for x in read_lines("supp_order.txt") if x]
    count, target = first_int("supp_count.txt"), first_int("supp_target.txt", -1)
    paused = os.path.exists(os.path.join(ROOT, "PAUSE"))
    man_path = os.path.join(ROOT, "cards", "manifest.json")
    manifest = json.load(open(man_path, encoding="utf-8")) if os.path.exists(man_path) else {}
    base = (CFG.get("pages_base_url") or "").rstrip("/")

    def save_manifest():
        write_text("cards/manifest.json", json.dumps(manifest, ensure_ascii=False, indent=0))

    # automatic rollout step, at most one per STEP_GAP: two runs in the same hour (cron plus the
    # self-restarting chain, or a manual run) must not double the pace
    last_step = first_int("supp_last_step.txt")
    if target >= 0 and count != target and not a.no_step and not a.dry and not paused:
        if count > target:
            count = target
            write_text("supp_count.txt", f"{count}\n")
        elif time.time() - last_step >= STEP_GAP:
            count = min(target, count + CFG["rollout"]["ids_per_hour"])
            write_text("supp_count.txt", f"{count}\n")
            write_text("supp_last_step.txt", f"{int(time.time())}\n")

    eligible = {str(p["id"]): p for p in prods if not p["skip"] and p["family"] not in CFG["exclude_families"]}
    if not order:
        order = list(eligible)
    live_ids = [i for i in order[:count] if i in eligible and i not in holdout]
    render_ids = [i for i in order if i in eligible and i not in holdout]
    seen = set(render_ids)
    render_ids += [i for i in eligible if i not in seen and i not in holdout]

    # what needs a new card
    todo, stale = [], 0
    for pid in render_ids:
        p = eligible[pid]
        concept = concept_for(p["family"])
        if not concept:
            continue
        h = cards.input_hash(p, concept)
        m = manifest.get(pid)
        if m and m["hash"] == h:
            continue
        if m:
            stale += 1          # match check failed: the old card must not be served any more
            if not a.dry:
                manifest.pop(pid)
        todo.append((pid, concept, h))
    waiting = len(todo)
    todo = [] if a.dry else todo[:max(a.max_cards, 0)]

    os.makedirs(os.path.join(ROOT, "cards"), exist_ok=True)
    rendered = failed = 0
    if todo:
        def grab(t):
            try:
                cards.fetch_image(eligible[t[0]]["image"])
            except Exception:
                pass                # the render step reports the failure
        with ThreadPoolExecutor(DOWNLOAD_THREADS) as ex:
            list(ex.map(grab, todo))
        for pid, concept, h in todo:
            p = eligible[pid]
            try:
                im = cards.render(p, concept)
                share = cards.product_share(im.crop((0, 32, 1080, 770)))
                fn = f"cards/{pid}-{h}.jpg"
                im.save(os.path.join(ROOT, fn), quality=88, optimize=True)
                manifest[pid] = {"hash": h, "file": fn, "concept": concept, "family": p["family"], "share": round(share, 3),
                                 "qc": share >= QC_MIN_SHARE, "built": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                 "from": {"image": p["image"], "name": p["name"], "price": p["price"]}}
                rendered += 1
                if rendered % SAVE_EVERY == 0:
                    save_manifest()
            except Exception as e:  # a broken photo must not stop the run
                failed += 1
                print("render failed", pid, e)

    # Meta accepts only "update" uploads for a supplementary feed: a row that disappears from the CSV keeps
    # its last image (checked on the live catalog, 2026-11-25). So every product that ever got a card stays
    # in the CSV, and when it must go back to the store photo its row carries the store photo URL.
    pub_path = os.path.join(ROOT, "feed", "published.json")
    published = json.load(open(pub_path, encoding="utf-8")) if os.path.exists(pub_path) else {}
    # Unattended safety: if the public host stops serving cards that are already live, Meta would fail to
    # fetch them. Then this run sends every product back to its store photo, and the next healthy run restores.
    if base and not paused and not a.dry and not hosting_ok(base, [manifest[i]["file"] for i in published if i in manifest]):
        print("SAFETY: card host not reachable, sending all products back to the store photo for this run")
        paused = True
    rows, with_card = [], set()
    if not paused:
        for pid in live_ids:
            p, m = eligible[pid], manifest.get(pid)
            concept = concept_for(p["family"])
            if not (m and concept and m["qc"] and m["hash"] == cards.input_hash(p, concept)):
                continue
            row = {"id": pid, "image_link": f"{base}/{m['file']}"}
            if CFG.get("enrich_catalog_fields"):
                row.update({"product_type": p["family_label"], "custom_label_0": p["family"], "brand": p["facts"].get("brand", "")})
            rows.append(row)
            with_card.add(pid)
            published[pid] = p["image"]
    all_prods = {str(p["id"]): p for p in prods}
    reverted = 0
    for pid, store_photo in published.items():
        if pid in with_card:
            continue
        current = all_prods.get(pid, {}).get("image") or store_photo   # the store's photo as it is now
        published[pid] = current
        rows.append({"id": pid, "image_link": current})
        reverted += 1

    print(f"eligible {len(eligible)} | cards ready {len(manifest)} | waiting for a card {waiting - rendered} | rendered now {rendered} | "
          f"changed on site {stale} | failed {failed} | rollout {count}" + (f" of target {target}" if target >= 0 else "") +
          f" | in CSV {len(rows)} (cards {len(with_card)}, back to store photo {reverted}) | holdout {len(holdout)} | paused {paused}")
    if a.dry:
        return
    if not base and rows:
        print("NOTE: pages_base_url is empty in client.config.json, so image_link is not a public URL yet.")
    save_manifest()
    os.makedirs(os.path.join(ROOT, "feed"), exist_ok=True)
    fields = ["id", "image_link"] + (["product_type", "custom_label_0", "brand"] if CFG.get("enrich_catalog_fields") else [])
    with open(os.path.join(ROOT, "feed", "supplementary.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    write_text("feed/published.json", json.dumps(published, ensure_ascii=False, indent=0, sort_keys=True))
    # remove card files that no manifest entry points to
    keep = {os.path.basename(m["file"]) for m in manifest.values()}
    for f in os.listdir(os.path.join(ROOT, "cards")):
        if f.endswith(".jpg") and f not in keep:
            os.remove(os.path.join(ROOT, "cards", f))


if __name__ == "__main__":
    main()
