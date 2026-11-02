# Release dbt-redis-adbc

The `Publish to PyPI` workflow builds the wheel and source archive once from an
existing stable version tag. It checks the tag against the package and runtime
versions, verifies distribution metadata and checksums, and runs the existing
CI workflow against the exact source commit with the built wheel installed.
The project runs on both locked dependencies and the oldest supported dbt
combination; dbt's functional adapter suite runs on locked dependencies. Each
integration job provisions a dedicated Redis Enterprise database with verified
TLS and named-user authentication.

The release jobs replace the editable adapter with the wheel, verify its origin
and imported module path, and disable automatic environment synchronization so
subsequent dbt and pytest commands continue testing that installed wheel.

After every validation job passes, the workflow publishes the same distributions
to PyPI through GitHub OIDC. It checks PyPI's file hashes against the tested
artifacts, then creates or updates the GitHub release, attaches the wheel, source
archive and `SHA256SUMS`, and marks the release published and latest. Publication
to PyPI and GitHub happens only on tag pushes or an explicitly enabled manual
publication. No long-lived PyPI token is required.

## Prepare a release

1. Update `v1/adapter/pyproject.toml`, the adapter's `__version__.py`, and the
   adapter version in `v1/uv.lock`. Merge the change after CI passes.
2. Create a stable tag such as `v0.3.0` on that exact commit and push the tag.
3. Watch **Actions → Publish to PyPI**. Tag pushes automatically build, test,
   publish to PyPI, verify published hashes, and finalize the GitHub release.
4. Review the generated GitHub release notes and add user-facing details as needed.

Do not build or attach release packages manually. The GitHub release is finalized
only after PyPI publication and verification succeeds. The native dbt v2 engine
fork has a separate distribution process; this workflow releases the Python v1
adapter.

## Validate without publishing

Open **Actions → Publish to PyPI → Run workflow**, choose the workflow branch,
and enter an existing tag. Leave **Publish to PyPI and finalize GitHub release**
unselected (the default). This runs the actual build and wheel integration tests
and retains artifacts, while skipping both publishing jobs. For example, use
`v0.2.0` to validate pipeline changes without altering that existing release.

To publish an existing, unpublished tag, run the same workflow with publication
enabled. The package and runtime versions must match the tag. Tags are resolved
to an immutable commit for building and testing; finalization refuses a tag that
has moved since the build.

## Retry a failed release

Prefer **Re-run failed jobs** on the original run so it reuses the already built
artifacts. If an upload completed before a later step failed, existing PyPI files
are skipped, but finalization still requires both PyPI files' SHA-256 hashes to
match the tested artifacts exactly. A differing package cannot silently replace
an already published version. Investigate any mismatch and use a new version
when package contents need to change; never move an existing release tag.

## Trusted publisher setup

The existing PyPI project's
[publishing settings](https://pypi.org/manage/project/dbt-redis-adbc/settings/publishing/)
must contain this GitHub trusted publisher:

| Field | Value |
| --- | --- |
| Owner | `redis` |
| Repository | `redis-dbt-adapter` |
| Workflow | `publish.yml` |
| Environment | `pypi` |

Only the publishing job receives `id-token: write`; only GitHub finalization
receives `contents: write`. Build and test jobs have read access. Repository
administrators can configure reviewers and deployment restrictions on the
`pypi` environment. See [PyPI's trusted publishing documentation](https://docs.pypi.org/trusted-publishers/).
