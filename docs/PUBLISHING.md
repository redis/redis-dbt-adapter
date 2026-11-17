# Publishing the documentation website

The documentation is published at
[redis.github.io/redis-dbt-adapter](https://redis.github.io/redis-dbt-adapter/).
MkDocs turns the repository's Markdown into HTML pages with navigation,
site search, canonical URLs, and a sitemap. The content is present in the
HTML itself so search engines can read it without running JavaScript.

## Edit and preview

Edit the original Markdown files listed in `mkdocs.yml`. The site reads those
files directly; there are no duplicate Markdown copies to maintain. To add a
page, add its repository-relative path to `nav` in `mkdocs.yml`.

From the repository root:

```sh
python3.13 -m venv .venv-docs
source .venv-docs/bin/activate
python -m pip install -r requirements-docs.txt
python -m mkdocs serve
```

Open the local URL printed by MkDocs. Run `python -m mkdocs build --strict`
to check the build and links before publishing. Generated files go in `site/`.
Only the selected Markdown and `website/content/` assets are published;
the repository's source code, test data, and local environments are not copied.
Links to source files and directories point to GitHub.

## Automatic deployment

The [Documentation workflow](../.github/workflows/docs.yml) checks pull requests
and publishes documentation changes pushed to `main`. It can also be run
manually from GitHub Actions. Pull requests build without publishing.

In the repository's **Settings → Pages**, the publishing source must be
**GitHub Actions**. Deployment uses the built-in Actions token; no deployment
secret is needed. A configured `github-pages` environment may require a
maintainer to approve deployment according to its existing protection rules.

## Google discovery

The sitemap is available at
[sitemap.xml](https://redis.github.io/redis-dbt-adapter/sitemap.xml).
To monitor indexing, add the site's URL as a URL-prefix property in
[Google Search Console](https://search.google.com/search-console/), complete
Google's ownership verification, and submit that sitemap URL. Use the URL
inspection tool to request indexing of the home page and installation guide.
Google controls whether and when pages appear in search results.

If the site moves to a custom domain, update `site_url` in `mkdocs.yml` and
the links in this guide so canonical URLs and the sitemap use the new address.
