# Issue tracker

Repository: SergiiMytakii/vcmi-llm-opponent on GitHub.
Live issues, comments, assignees, and native relationships are authoritative.
External pull requests are not an automatic work intake surface.

Prefer the GitHub connector. If unavailable or missing an operation, use gh
against this exact repository after stating the fallback and write scope.
Use JSON input files or --body-file for multiline writes.
Read back every mutation. After an uncertain result, query before retrying.

## Wayfinder operations

The map label is wayfinder:map. Each child has exactly one type label:
wayfinder:research, wayfinder:prototype, wayfinder:grilling, or wayfinder:task.
Create missing labels before use; do not repurpose existing labels.
Record HITL or AFK in each child's body. Refer to issues by linked title.

REST paths below are relative to repos/SergiiMytakii/vcmi-llm-opponent.
Use gh api with --method and --input for writes, --paginate for lists.
N is an issue number; issue_id fields require the numeric database ID.

1. Map: POST /issues with title, body, labels; verify GET /issues/N.
2. Child: create an issue, then POST /issues/MAP/sub_issues with
   {"sub_issue_id": CHILD_ID}; verify GET /issues/CHILD/parent.
3. Blocking: POST /issues/DEPENDENT/dependencies/blocked_by with
   {"issue_id": BLOCKER_ID}; verify the same path with GET.
   Native dependencies are required; body links are not a substitute.
4. Frontier: list GET /issues/MAP/sub_issues and each child's blockers.
   Select open, unassigned children whose blockers are all closed.
   Map order is ascending child issue number. Re-query before selection.
5. Claim: re-read the unassigned open child and blockers, then POST
   /issues/N/assignees with {"assignees":["SergiiMytakii"]}.
   Verify that exact assignee before work. An existing assignment is not
   ownership proof for a new session; coordinate before continuing it.
6. Resolve: verify ownership, POST /issues/N/comments with the answer,
   PATCH /issues/N with {"state":"closed","state_reason":"completed"},
   then PATCH the map body to append one linked decision gist.
   Verify comment, closure, and map before removing this session's assignment.
7. Release: DELETE /issues/N/assignees with the exact assigned login;
   verify removal. Release only a claim acquired by this session.
8. Recalculate: re-read children, blockers, and claims after each resolution.
   Create newly precise questions and wire blockers after IDs exist.
   Close out-of-scope children with state_reason not_planned and link them
   under Out of scope, rather than Decisions so far.
9. Complete: only when all children are closed and in-scope fog is empty,
   close the map and hand its resolutions to Plan. Stop before implementation.

Charting creates the map and questions; it does not resolve them.
HITL decisions require the user's live answers. Prototype work is throwaway.
