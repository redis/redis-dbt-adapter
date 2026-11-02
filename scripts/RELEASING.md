# Publish dbt-redis-adbc to PyPI

The `Publish to PyPI` workflow publishes the wheel and source archive attached
to a published GitHub release. It verifies their SHA-256 checksums and package
identity, checks package metadata with Twine, and passes only those verified
distributions to the publishing job. The job uses PyPI trusted publishing
through GitHub OIDC; no long-lived PyPI API token is required.

Configure a GitHub trusted publisher in the existing PyPI project's
[publishing settings](https://pypi.org/manage/project/dbt-redis-adbc/settings/publishing/):

| Field | Value |
| --- | --- |
| Owner | `redis` |
| Repository | `redis-dbt-adapter` |
| Workflow | `publish.yml` |
| Environment | `pypi` |

The workflow uses the GitHub environment `pypi`. Repository administrators can
add required reviewers or deployment restrictions in that environment's settings.

For a new release, attach the wheel, source archive, and `SHA256SUMS` before
publishing the GitHub release. Use stable version tags such as `v0.2.0`; package
metadata versions must match. Publication then starts automatically.

To publish an existing release, open **Actions → Publish to PyPI → Run workflow**,
select `main`, and supply its tag (for example `v0.2.0`). This also retries a
failed publication after correcting the trusted publisher configuration. PyPI
rejects replacement files for an already published version; inspect the PyPI
release before retrying a partially completed upload.

After success, verify the version and distribution checksums on PyPI. See
[PyPI's trusted publishing documentation](https://docs.pypi.org/trusted-publishers/).
