# Работа от вкъщи

A daily search for remote jobs that someone living in Bulgaria can do without specialist skills
(customer support, AI rating and annotation, data entry, simple dispatch and monitoring).
Bulgarian and conversational English only; no night shifts.

Page: https://haygrouve.github.io/rabota-ot-vkashti/

## How it works

- `job_watch.py` checks zaplata.bg (ads sitemap) and the public APIs/feeds of Himalayas, Jobicy, Remote OK,
  Working Nomads, We Work Remotely and Remotive, filters the jobs, scores how easy each one is, and writes:
  - `reports/<date>.json` / `.md`: jobs not seen before,
  - `jobs.json`: every matching job still listed on its site,
  - `seen.json`: jobs already checked.
- `build_page.py` turns those into one static page (`site/index.html`).
- `.github/workflows/daily.yml` runs the search every morning, saves the results to the `data` branch
  and publishes the page to GitHub Pages. A push to `main` only rebuilds the page.

The job sites' terms ask for credit and a link to the original ad; every listing links to it and names its source.

## Running locally

```sh
python3 -I job_watch.py          # data in this folder, page in site/
python3 -I job_watch.py --all    # re-report everything, ignoring jobs already seen
JOBWATCH_DATA=../data python3 -I build_page.py   # rebuild the page from another data folder
python3 -I tools/dump_matches.py /tmp/matches.json /tmp/zaplata_cache.json   # all current matches with full text
```

Python 3.9+ standard library only.
