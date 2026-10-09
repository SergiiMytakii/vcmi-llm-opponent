# Strategic request compatibility fixtures

`input.json` is a deterministic world/accepted-plan fixture. The six output
files preserve the complete compact wire bytes produced by the original
`NativeCampaign::prepareNextTurn` and `NativeCampaign::reviewStrategy` assembly
blocks before those blocks were replaced by `buildStrategicRequest`.

The capture compiled the original assembly blocks with the existing native
projection, campaign, intent and transport implementations. Identity, request
ID, signals and limits were supplied by the driver as the turn owner supplies
them in production. These are contract fixtures, not recorded live gameplay.

Baseline: HEAD `b97db768576893f2fac6495c572e57a09950cada` plus the existing
uncommitted strategy-review work. The original caller file SHA-256 was
`4cd89d210c52f1876e2312a0fb16b05c63e7a73b45f07c6a19d31e37bfe2d477`.
The extracted request assembly was unchanged by that pre-existing work.

Cases cover initial/local/detailed/idle review and routine/strategic background
preparation. Array order, repeated background evidence labels, absent versus
null fields, scoped targets and Unicode are deliberately preserved. The tests
also exercise truncation, required-context overflow, and unchanged source
facts through the same context builder used by both production callers. The test
driver supplies its own envelope, bounding and serialization; those now belong
to the two native callers and are intentionally outside `buildStrategicContext`.

Do not regenerate expected outputs merely because the implementation changes.
A deliberate request-contract change must explain the corresponding fixture
delta. Build `strategic-request-driver` with `tests/strategy-memory`, then run:

```sh
STRATEGIC_REQUEST_DRIVER=/absolute/build/strategic-request-driver \
PYTHONPATH=tests:controller python3 -m unittest test_strategic_request -v
```
