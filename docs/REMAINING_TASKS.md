# Remaining live-evidence and submission tasks

This is the single operator checklist for the work that remains after the
software implementation in `docs/challenge_12_hour_implementation_plan.md`.
The implementation has passed independent review. The remaining work is live
human authorization, provider-backed scientific execution, evidence capture,
rehearsal, and submission packaging.

Commands in `bash` blocks are written so the whole block can be copied into a
terminal and run. Commands that require run-specific information prompt for it;
they do not contain fake digests, identities, or placeholder paths. Omnigent
interactions are described as operator actions rather than shell commands.

Every multi-command block runs in a subshell, delimited by the opening `(` and
closing `)`. Copy both delimiters. Strict error handling is enabled only inside
that subshell, so a failed check stops the block and returns a nonzero status but
does **not** enable `errexit`, `nounset`, or `pipefail` in the interactive shell
and does not close the terminal.

## Current release identity

- Repository: `https://github.com/buh07/Ai-Researcher.git`
- Verified implementation commit:
  `8a814084041a3a3051bcb751552474c8242f623b`
- Verified lock digest:
  `ce4253d3d470c83448322aa35a830e06bb7dc008882cf9a3586e565d6cbb7c88`
- Primary endpoint: `trials_to_threshold`
- Quality guard: `accuracy`
- Pinned live target: OpenML task 59, dataset 61, version 1
- External evidence directory:
  `/jumbo/lisp/f004ndc/projects/Ai-Researcher-submission-evidence`

The recorded evidence below is historical evidence for the verified
implementation commit. The current branch may contain later documentation-only
commits. Do not expect the current `HEAD` to equal the historical evidence
commit. After the repository has its eventual submission commit, use Task 1's
fresh-capture block so `environment.txt` names that exact commit.

## Required challenge-submission work

### [ ] Task 1 — Capture and verify release-check evidence for the submission commit

**Status:** historical evidence is complete and revalidated for commit
`8a814084041a3a3051bcb751552474c8242f623b`. A fresh capture is still required
after the eventual submission commit is created.

Evidence is stored in:

`/jumbo/lisp/f004ndc/projects/Ai-Researcher-submission-evidence/checks/`

Verified results:

| Check | Result | Duration or identity |
|---|---|---|
| Environment | PASS | Python 3.12.3; uv 0.12.0 |
| Repository identity | PASS | `main`, synchronized with `origin/main` |
| `uv sync --frozen` | PASS | 99 packages checked; 0.42 seconds |
| Omnigent bundle validation | PASS | 1.77 seconds |
| Project tests | PASS | 102 passed; 9.92 test seconds, 11.38 wall seconds |
| Complete Harness suite | PASS | 514 passed, 42 skipped; 49.221 seconds |
| Compileall | PASS | No compile failures |
| `git diff --check` | PASS | No whitespace errors |
| Working tree at capture | PASS | Clean and synchronized |
| Evidence checksums | PASS | Every captured check log revalidated |

The 42 Harness skips are disclosed in the verbose log. They comprise 5 absent
optional fake-store fixtures, 6 Windows replacement-semantics tests, 2 macOS
product demonstrations, 1 unavailable setuptools/wheel environment test, 1
Windows creation-flags test, 2 Windows venv-redirector tests, 3 Windows Job
Object tests, 2 unavailable Qwen 0.21.10 tests, 5 Windows junction tests, and 15
absent optional live-matrix fixture tests.

The Harness suite must use node-local temporary storage on this host. The
inherited Lustre temporary directory can leave transient `.nfs*` handles during
test cleanup even though the product assertions pass.
The `operator_launch: ... invalid choice: 'detached.json'` text emitted during
the full suite is expected output from a negative CLI parser test; the unittest
summary, not that deliberately generated stderr, determines suite success.

Revalidate the historical evidence at any time with the following block. It
validates the recorded commit directly and deliberately does not require the
current checkout to be at that older commit:

```bash
(
set -euo pipefail

REPO=/jumbo/lisp/f004ndc/projects/Ai-Researcher
CHECKS=/jumbo/lisp/f004ndc/projects/Ai-Researcher-submission-evidence/checks
EVIDENCE_COMMIT=8a814084041a3a3051bcb751552474c8242f623b
LOCK_DIGEST=ce4253d3d470c83448322aa35a830e06bb7dc008882cf9a3586e565d6cbb7c88

cd "$REPO"
git cat-file -e "${EVIDENCE_COMMIT}^{commit}"
test "$(git show "${EVIDENCE_COMMIT}:uv.lock" | sha256sum | awk '{print $1}')" = \
  "$LOCK_DIGEST"

cd "$CHECKS"
sha256sum -c SHA256SUMS
grep -Fx "$EVIDENCE_COMMIT" environment.txt
grep -F "$LOCK_DIGEST  uv.lock" environment.txt
grep -F "102 passed" project-tests.txt
grep -F "Ran 514 tests" harness-tests.txt
grep -F "OK (skipped=42)" harness-tests.txt
grep -F "clean-working-tree: PASS" compile-diff-status.txt
printf '%s\n' "Historical evidence validation: PASS ($EVIDENCE_COMMIT)"
)
```

After creating the eventual submission commit, capture a fresh complete check
set with the next block. Run it only from a clean branch synchronized with its
upstream. Unlike the historical validation above, this block records whichever
commit is checked out when it runs:

```bash
(
set -euo pipefail

REPO=/jumbo/lisp/f004ndc/projects/Ai-Researcher
EVIDENCE=/jumbo/lisp/f004ndc/projects/Ai-Researcher-submission-evidence
TMPROOT=$(mktemp -d /tmp/ai-researcher-tests.XXXXXX)
trap 'rm -rf "$TMPROOT"' EXIT

cd "$REPO"
mkdir -p "$EVIDENCE/checks"

{
  date -u
  git remote get-url origin
  git rev-parse HEAD
  git status --porcelain=v2 --branch
  sha256sum uv.lock
  python --version
  uv --version
} | tee "$EVIDENCE/checks/environment.txt"

{ /usr/bin/time -p uv sync --frozen; } \
  2>&1 | tee "$EVIDENCE/checks/uv-sync.txt"

{ /usr/bin/time -p uv run python scripts/validate_bundle.py; } \
  2>&1 | tee "$EVIDENCE/checks/bundle-validation.txt"

{ /usr/bin/time -p uv run pytest; } \
  2>&1 | tee "$EVIDENCE/checks/project-tests.txt"

(
  cd harness
  TMPDIR="$TMPROOT" TEMP="$TMPROOT" TMP="$TMPROOT" \
    PYTHONPATH=. ../.venv/bin/python -m unittest discover -v \
      -s orchestrator_harness/tests -p 'test_*.py'
) 2>&1 | tee "$EVIDENCE/checks/harness-tests.txt"

{
  echo "compileall:"
  uv run python -m compileall -q \
    src scripts agents/research-director/tools/python
  echo "PASS"
  echo "git diff --check:"
  git diff --check
  echo "PASS"
  echo "git status --porcelain=v2 --branch:"
  git status --porcelain=v2 --branch
  test -z "$(git status --porcelain)"
  echo "clean-working-tree: PASS"
} 2>&1 | tee "$EVIDENCE/checks/compile-diff-status.txt"

(
  cd "$EVIDENCE/checks"
  sha256sum ./*.txt > SHA256SUMS
  sha256sum -c SHA256SUMS
)
)
```

### [ ] Task 2 — Configure Omnigent, a live provider, and the Harness

**Requires:** an authenticated Codex CLI for the Codex-backed director and
specialists, an authenticated provider CLI for the later bounded experiment
(which may also be Codex), OpenML network access, and an operator-approved cost
budget. Never place credentials in Git, prompts, task cards, captured
transcripts, or artifacts.

Run Omnigent setup:

```bash
(
set -euo pipefail
cd /jumbo/lisp/f004ndc/projects/Ai-Researcher
uv run omnigent setup
codex login status
)
```

Select and validate the bounded-experiment execution provider. This is
separate from the director's pinned Codex harness and writes only the
non-secret provider/model choice to the ignored `runtime/` directory:

```bash
(
set -euo pipefail
cd /jumbo/lisp/f004ndc/projects/Ai-Researcher
mkdir -p runtime

printf '%s\n' \
  'Choose a provider:' \
  '  codex' \
  '  claude-code' \
  '  qwen-code'
read -r -p 'Provider: ' PROVIDER
read -r -p 'Exact provider model identifier: ' MODEL

case "$PROVIDER" in
  codex)
    PROVIDER_CLI=codex
    PROVIDER_OPTIONS='{"reasoning_effort":"high","service_tier":"priority"}'
    ;;
  claude-code)
    PROVIDER_CLI=claude
    PROVIDER_OPTIONS='{"effort":"high"}'
    ;;
  qwen-code)
    PROVIDER_CLI=qwen
    PROVIDER_OPTIONS='{}'
    ;;
  *)
    echo 'Unsupported provider selection' >&2
    exit 1
    ;;
esac

test -n "$MODEL"
command -v "$PROVIDER_CLI"

python - "$PROVIDER" "$MODEL" "$PROVIDER_OPTIONS" <<'PY'
import json
import sys
from pathlib import Path

provider, model, raw_options = sys.argv[1:]
payload = {
    "provider": provider,
    "model": model,
    "provider_options": json.loads(raw_options),
}
Path("runtime/provider-selection.json").write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(json.dumps(payload, indent=2, sort_keys=True))
PY
)
```

Authenticate through the provider's own supported login flow before
continuing. Do not paste a token into this repository.

Create the ignored Harness configuration and perform setup without launching a
lane:

```bash
(
set -euo pipefail
cd /jumbo/lisp/f004ndc/projects/Ai-Researcher

ROOT=$(pwd -P)
mkdir -p harness/local-config

python - "$ROOT" <<'PY'
import json
import sys
from pathlib import Path

root = sys.argv[1]
Path("harness/local-config/harness-config.json").write_text(
    json.dumps(
        {
            "root_workspace": root,
            "managed_coordination": "enabled",
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
PY

cp harness/examples/resource-manifest.example.json \
  harness/local-config/resource-manifest.json

(
  cd harness
  TMPDIR=/tmp TEMP=/tmp TMP=/tmp PYTHONPATH=. \
    ../.venv/bin/python -m orchestrator_harness.operator_launch \
      --json harness setup
)

git check-ignore harness/local-config/harness-config.json
git check-ignore harness/local-config/resource-manifest.json
)
```

**Done when:** Harness setup succeeds, the provider CLI is authenticated, the
model and provider options are explicit, and no secret or local configuration
is tracked by Git.

### [ ] Task 3 — Verify live OpenML identity, bytes, license, and privacy

**Requires:** network access to OpenML and an attributable human who can review
license, redistribution, privacy, and caching conditions.

Download the exact current task, metadata, and data bytes; validate identity
and OpenML's declared MD5; and record the SHA-256 used by all later authority:

```bash
(
set -euo pipefail
cd /jumbo/lisp/f004ndc/projects/Ai-Researcher

DATA_WORK=/tmp/ai-researcher-openml
EVIDENCE=/jumbo/lisp/f004ndc/projects/Ai-Researcher-submission-evidence
mkdir -p "$DATA_WORK" "$EVIDENCE/preflight"

uv run python - "$DATA_WORK" "$EVIDENCE/preflight" <<'PY'
import hashlib
import json
import shlex
import sys
import urllib.request
from pathlib import Path

work = Path(sys.argv[1])
evidence = Path(sys.argv[2])

def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=20) as response:
        return json.load(response)

task = get_json("https://www.openml.org/api/v1/json/task/59")
metadata = get_json("https://www.openml.org/api/v1/json/data/61")
description = metadata["data_set_description"]
url = description.get("url") or "https://openml.org/data/v1/download/61/iris.arff"

with urllib.request.urlopen(url, timeout=20) as response:
    raw = response.read()

task_body = task["task"]
source = next(item for item in task_body["input"] if item["name"] == "source_data")
source_data = source["data_set"]

assert str(task_body["task_id"]) == "59"
assert str(source_data["data_set_id"]) == "61"
assert source_data["target_feature"] == "class"
assert str(description["id"]) == "61"
assert str(description["version"]) == "1"
assert description["default_target_attribute"] == "class"
assert str(description.get("licence", "")).strip()

actual_md5 = hashlib.md5(raw, usedforsecurity=False).hexdigest()
declared_md5 = description.get("md5_checksum")
if declared_md5 and actual_md5 != declared_md5:
    raise SystemExit("OpenML data does not match its declared MD5")

sha256 = hashlib.sha256(raw).hexdigest()
(work / "dataset-61-v1.arff").write_bytes(raw)
(work / "task-59.json").write_text(
    json.dumps(task, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
(work / "dataset-61-metadata.json").write_text(
    json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)

for source_path in work.iterdir():
    if source_path.is_file():
        (evidence / source_path.name).write_bytes(source_path.read_bytes())

(work / "dataset.env").write_text(
    "\n".join(
        [
            f"OPENML_DATASET_SHA256={shlex.quote(sha256)}",
            f"OPENML_DATASET_URL={shlex.quote(url)}",
            f"OPENML_DECLARED_LICENSE={shlex.quote(str(description['licence']))}",
        ]
    )
    + "\n",
    encoding="utf-8",
)

print("OpenML task: 59")
print("OpenML dataset: 61")
print("OpenML dataset version: 1")
print("Data URL:", url)
print("SHA-256:", sha256)
print("Actual MD5:", actual_md5)
print("Declared MD5:", declared_md5)
print("Declared license:", description["licence"])
PY

cat "$DATA_WORK/dataset.env"
)
```

After personally reviewing the captured metadata and data, create the formal
governance attestation. The following command refuses to write `VERIFIED`
unless the operator types the explicit confirmation word:

```bash
(
set -euo pipefail
cd /jumbo/lisp/f004ndc/projects/Ai-Researcher
mkdir -p runtime

read -r -p 'Attributable human reviewer ID: ' VERIFIED_BY
read -r -p 'License/access/redistribution evidence note: ' LICENSE_EVIDENCE
read -r -p 'Privacy and public-data evidence note: ' PRIVACY_EVIDENCE

printf '%s\n' \
  'Confirm that you inspected the exact dataset and metadata,' \
  'that the license/access decision is acceptable for this run,' \
  'and that the privacy decision is acceptable for this run.'
read -r -p 'Type VERIFY to create the attestation: ' GOVERNANCE_CONFIRMATION
test "$GOVERNANCE_CONFIRMATION" = VERIFY

export VERIFIED_BY LICENSE_EVIDENCE PRIVACY_EVIDENCE
uv run python - <<'PY'
import json
import os
from datetime import UTC, datetime
from pathlib import Path

payload = {
    "license_status": "VERIFIED",
    "license_evidence": os.environ["LICENSE_EVIDENCE"],
    "privacy_status": "VERIFIED",
    "privacy_evidence": os.environ["PRIVACY_EVIDENCE"],
    "verified_by": os.environ["VERIFIED_BY"],
    "verified_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
}
Path("runtime/data-governance.json").write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(json.dumps(payload, indent=2, sort_keys=True))
PY
)
```

**Fallback:** with the current pinned implementation, the safe no-code
fallback is to stop the live scientific claim and use the checked-in fixture
only as a mechanical demonstration. A different scientific dataset requires a
new implementation target and new human confirmation.

### [ ] Task 4 — Start Omnigent and record human objective authority

**Requires:** the Task 3 digest and governance review, a real human identity,
and an attributable confirmation session. Prior conversation is not a substitute
for the journal record.

Start a fresh research-director session with the required opening instruction.
The explicit harness and model flags match every bundled specialist and prevent
Omnigent from selecting an unrelated configured credential. Do not resume a
session that failed provider authentication before creating a research record:

```bash
(
set -euo pipefail
cd /jumbo/lisp/f004ndc/projects/Ai-Researcher
source /tmp/ai-researcher-openml/dataset.env

# Omnigent validates uploaded bundles in temporary directories. Keep the
# client and both long-lived daemons off shared NFS temporary storage; otherwise
# delayed .nfs-file cleanup can surface as a false "invalid agent bundle" error.
export TMPDIR=/tmp TEMP=/tmp TMP=/tmp
uv run omnigent stop
uv run omnigent start --no-open
uv run omnigent host status
uv run omnigent server status

uv run omnigent run --harness codex --model gpt-5.6-sol \
  agents/research-director -p \
  "Propose a bounded live investigation of evidence-guided experiment selection on OpenML task 59, dataset 61 version 1, using the exact downloaded dataset SHA-256 $OPENML_DATASET_SHA256 from $OPENML_DATASET_URL. Use trials_to_threshold as the primary metric and accuracy only as its quality guard. Do not substitute the synthetic fixture. Stop and ask me to confirm the exact research objective, primary metric, dataset, risk tolerance, and consequential execution scope before treating the objective as active. Verify data/API access, license/privacy, identity, and compute feasibility. Prepare cited evidence, at least two experiment candidates, and an independent safety review. Stop again for exact-digest human approval before staging, and never launch without my explicit decision."
)
```

If the command previously failed with `[Errno 39] Directory not empty`, do not
resume that failed session. The stop/start sequence above replaces daemons that
inherited shared temporary storage, and the final command creates the required
fresh session.

The director must journal `research-question/v1` as a proposal and display its
question ID and record digest. In a second terminal, create and record the human
objective. The command below prompts for all run-specific and human-owned
fields, displays the complete packet, and requires explicit confirmation:

```bash
(
set -euo pipefail
cd /jumbo/lisp/f004ndc/projects/Ai-Researcher
source /tmp/ai-researcher-openml/dataset.env
mkdir -p runtime

read -r -p 'Research-question ID shown by Omnigent: ' QUESTION_ID
read -r -p 'Research-question record digest shown by Omnigent: ' QUESTION_DIGEST
read -r -p 'Attributable human ID: ' HUMAN_ID
read -r -p 'Attributable confirmation session ID: ' HUMAN_SESSION_ID

read -r -p 'Risk level [low]: ' RISK_LEVEL
RISK_LEVEL=${RISK_LEVEL:-low}
read -r -p 'Maximum total trials [8]: ' MAX_TRIALS
MAX_TRIALS=${MAX_TRIALS:-8}
read -r -p 'Maximum runtime in minutes [30]: ' MAX_RUNTIME_MINUTES
MAX_RUNTIME_MINUTES=${MAX_RUNTIME_MINUTES:-30}
read -r -p 'Maximum experiment cost in USD [1.0]: ' MAX_COST_USD
MAX_COST_USD=${MAX_COST_USD:-1.0}

DEFAULT_FALLBACK='Stop the live scientific claim and use the checked-in fixture only as a non-scientific mechanical demonstration.'
read -r -p "Named fallback [$DEFAULT_FALLBACK]: " FALLBACK
FALLBACK=${FALLBACK:-$DEFAULT_FALLBACK}

export QUESTION_ID QUESTION_DIGEST HUMAN_ID HUMAN_SESSION_ID FALLBACK
export RISK_LEVEL MAX_TRIALS MAX_RUNTIME_MINUTES MAX_COST_USD
export OPENML_DATASET_SHA256 OPENML_DATASET_URL

uv run python - <<'PY'
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from ai_researcher.journal import ResearchJournal

question = ResearchJournal("runtime/research-journal.sqlite3").get(
    os.environ["QUESTION_DIGEST"]
)
if question is None or question.get("schema") != "research-question/v1":
    raise SystemExit("question digest is not a journaled research question")
if question.get("question_id") != os.environ["QUESTION_ID"]:
    raise SystemExit("question ID does not match the journaled question digest")
if question.get("primary_metric") != "trials_to_threshold":
    raise SystemExit("journaled question has the wrong primary metric")

payload = {
    "schema": "objective-confirmation/v1",
    "objective_confirmation_id": f"objective-{os.environ['QUESTION_ID']}",
    "question_id": os.environ["QUESTION_ID"],
    "question_digest": os.environ["QUESTION_DIGEST"],
    "primary_metric": "trials_to_threshold",
    "dataset": {
        "identifier": "openml-task-59-dataset-61",
        "version": "1",
        "digest": os.environ["OPENML_DATASET_SHA256"],
        "source": os.environ["OPENML_DATASET_URL"],
    },
    "risk_tolerance": {
        "level": os.environ["RISK_LEVEL"],
        "allowed_risks": ["bounded compute overrun"],
        "prohibited_actions": ["data mutation", "undeclared network access"],
        "privacy_constraints": ["public non-personal data only"],
        "acceptable_failure_modes": ["inconclusive result"],
    },
    "execution_scope": {
        "max_trials": int(os.environ["MAX_TRIALS"]),
        "max_runtime_minutes": int(os.environ["MAX_RUNTIME_MINUTES"]),
        "max_cost_usd": float(os.environ["MAX_COST_USD"]),
        "compute": "local CPU",
        "network_access": "read-only-openml",
        "mutation_permissions": ["artifact directory only"],
    },
    "confirmed_by": os.environ["HUMAN_ID"],
    "confirmed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
}
Path("runtime/objective-confirmation.json").write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
Path("runtime/fallback.txt").write_text(os.environ["FALLBACK"] + "\n", encoding="utf-8")
print("EXACT JOURNALED RESEARCH QUESTION:")
print(question["question"])
print("\nOBJECTIVE CONFIRMATION PACKET:")
print(json.dumps(payload, indent=2, sort_keys=True))
print("\nNAMED FALLBACK:")
print(os.environ["FALLBACK"])
PY

printf '%s\n' \
  'Review the exact objective packet printed above.' \
  'It controls the metric, dataset, risk, and consequential execution scope.'
read -r -p 'Type CONFIRM_OBJECTIVE to record this authority: ' CONFIRMATION
test "$CONFIRMATION" = CONFIRM_OBJECTIVE

uv run python scripts/record_human_authority.py \
  --journal runtime/research-journal.sqlite3 \
  --record runtime/objective-confirmation.json \
  --parent-digest "$QUESTION_DIGEST" \
  --human-id "$HUMAN_ID" \
  --human-session-id "$HUMAN_SESSION_ID" \
  | tee runtime/objective-confirmation.stored.json
)
```

**Done when:** the stored output contains the objective record digest, and that
digest is used as the authority token in every later record. Any material
change requires a new, explicitly superseding confirmation.

### [ ] Task 5 — Complete the formal live feasibility gate

Return to the same Omnigent director session. Instruct it to call
`preflight_confirmed_objective` with the exact stored objective digest, OpenML
task 59, dataset 61, the contents of `runtime/data-governance.json`, an
attributable operator identity and time, the exact fallback stored in
`runtime/fallback.txt`, and `live=true`.

All six exact checks must pass:

1. Access
2. Identity
3. License
4. Privacy
5. API
6. Compute

The live SHA-256 must equal the human-confirmed dataset digest. If anything
fails, stop; resolve the failure or create a newly confirmed objective. Do not
silently switch data and do not treat the fixture as scientific evidence.

### [ ] Task 6 — Capture genuine parallel Omnigent evidence discovery

In the director session:

1. Define at least two independent, bounded evidence questions that can check a
   load-bearing claim independently.
2. Call `start_parallel_branch` for each branch.
3. Dispatch both `evidence-researcher` child sessions before waiting for either.
4. Require each child to call the provider start marker, perform at least one
   real `web_search`, capture claim-level citations, and call the provider end
   marker.
5. Finish each branch using its actual child-session ID.
6. Record distinct `evidence-package/v1` and `parallel-branch/v1` records.
7. Reconcile agreements, conflicts, coverage gaps, and unresolved questions.

Export each real child transcript with this copy/pasteable prompt loop:

```bash
(
set -euo pipefail
cd /jumbo/lisp/f004ndc/projects/Ai-Researcher

DEST=/jumbo/lisp/f004ndc/projects/Ai-Researcher-submission-evidence/omnigent
mkdir -p "$DEST"

while true; do
  read -r -p 'Child Omnigent session ID, or press Enter when finished: ' SESSION_ID
  test -n "$SESSION_ID" || break
  uv run omnigent session export \
    --id "$SESSION_ID" \
    --output "$DEST/$SESSION_ID.jsonl"
done
)
```

`parallel_status` may be `MET` only if provider-owned marker intervals strictly
overlap and the branches have distinct sessions, invocation IDs, and cited
packages. Otherwise record `UNMET` honestly.

Evidence must also support the significance narrative: why the bottleneck
matters, who benefits, and what larger breakthrough successful scaling could
enable.

### [ ] Task 7 — Generate hypotheses, compare experiments, and review safety

In Omnigent:

1. Send reconciled evidence IDs to `hypothesis-scientist`.
2. Require falsifiable predictions, falsification conditions, competing
   explanations, uncertainty, and resolvable evidence IDs.
3. Send the selected hypothesis, passing feasibility record, and confirmed
   scope to `experiment-designer`.
4. Require at least two genuinely distinct candidates and one rejection
   rationale per unselected candidate.
5. Require the selected live candidate to declare `search_candidates`,
   `baseline_order`, `evidence_guided_order`, `split_seed`, `threshold`,
   `max_trials_per_arm`, `max_seconds_per_arm`, and
   `quality_noninferiority_margin`.
6. Require both `trials_to_threshold` and `accuracy`, the exact dataset triplet,
   matched controls, and bounds no broader than human authority.
7. Preserve one creative but falsifiable and equally safe alternative.
8. Send the exact selected digest to the independent `safety-reviewer`.
9. Continue only on the appropriate `APPROVAL_REQUIRED` outcome; revise or stop
   on `REVISE` or `REJECT`.

**Done when:** the journal contains linked evidence, reconciliation,
hypothesis, candidate-comparison, selection, rejection-rationale, and
independent-safety records under the same objective digest.

### [ ] Task 8 — Record exact approval, stage, and launch separately

First have the director call `request_experiment_approval` and display the
objective digest, selected experiment digest, controls, prohibited actions, and
resource scope.

In a second terminal, create the separate human approval. This block prompts
for every run-specific identifier and refuses to record approval without the
explicit confirmation word:

```bash
(
set -euo pipefail
cd /jumbo/lisp/f004ndc/projects/Ai-Researcher
mkdir -p runtime

read -r -p 'Selected experiment ID: ' EXPERIMENT_ID
read -r -p 'Exact selected experiment digest: ' EXPERIMENT_DIGEST
read -r -p 'Exact objective-confirmation digest: ' OBJECTIVE_DIGEST
read -r -p 'Safety-review record digest: ' SAFETY_REVIEW_DIGEST
read -r -p 'Attributable approving human ID: ' HUMAN_ID
read -r -p 'Attributable approval session ID: ' HUMAN_SESSION_ID

export EXPERIMENT_ID EXPERIMENT_DIGEST OBJECTIVE_DIGEST HUMAN_ID

uv run python - <<'PY'
import json
import os
from datetime import UTC, datetime
from pathlib import Path

payload = {
    "schema": "human-approval/v1",
    "approval_id": f"approval-{os.environ['EXPERIMENT_ID']}",
    "experiment_id": os.environ["EXPERIMENT_ID"],
    "experiment_digest": os.environ["EXPERIMENT_DIGEST"],
    "objective_confirmation_digest": os.environ["OBJECTIVE_DIGEST"],
    "approved": True,
    "approved_by": os.environ["HUMAN_ID"],
    "approved_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    "scope": "execute-exact-experiment",
    "constraints": [],
}
Path("runtime/human-approval.json").write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(json.dumps(payload, indent=2, sort_keys=True))
PY

printf '%s\n' \
  'Review the exact experiment and authority digests printed above.' \
  'This authorizes only that experiment under the confirmed scope.'
read -r -p 'Type APPROVE_EXACT_EXPERIMENT to record approval: ' CONFIRMATION
test "$CONFIRMATION" = APPROVE_EXACT_EXPERIMENT

uv run python scripts/record_human_authority.py \
  --journal runtime/research-journal.sqlite3 \
  --record runtime/human-approval.json \
  --parent-digest "$SAFETY_REVIEW_DIGEST" \
  --human-id "$HUMAN_ID" \
  --human-session-id "$HUMAN_SESSION_ID" \
  | tee runtime/human-approval.stored.json
)
```

Then:

1. Have the director call `stage_approved_experiment` with the journaled
   approval digest. Staging must not launch.
2. Inspect and save the objective, experiment, approval, and task-card digests,
   lane ID, and task-card path.
3. End or detach the non-execution-enabled Omnigent process.
4. Reopen the same session with the environment gate scoped only to that
   process:

```bash
(
set -euo pipefail
cd /jumbo/lisp/f004ndc/projects/Ai-Researcher

read -r -p 'Root Omnigent session ID to resume: ' ROOT_SESSION_ID
AI_RESEARCHER_ENABLE_EXECUTION=1 \
  uv run omnigent run --resume "$ROOT_SESSION_ID" agents/research-director
)
```

In that resumed session, explicitly repeat the approval digest and instruct the
director to call `launch_approved_experiment` using the provider, model, and
options in `runtime/provider-selection.json`.

**Done when:** the durable binding reaches `LAUNCHED` with fixed lane and run
IDs. Staging alone does not count.

### [ ] Task 9 — Complete the entire live experiment lifecycle

Do not stop at launch. Through the director's declared tools:

1. Use `get_harness_experiment_status` and `wait_for_experiment` for the exact
   lane and run.
2. Make the worker run only the exact approved live OpenML experiment.
3. Capture source-digested measurements for both arms when genuinely observed:
   retrieval, planning, approval, preflight, agent/tool time, interventions,
   cost, and token usage.
4. Never invent zero for missing measurements. Missing telemetry remains
   unavailable and blocks an end-to-end speed claim.
5. Convert the outcome with `ExperimentOutcome.as_experiment_result`; decision
   latency must not be present yet.
6. Call `build_harness_result` and have the worker write its returned envelope
   unchanged as `RESULT.json`.
7. Have a distinct ROOT/operator call `review_experiment_completion`.
8. Accept only a scientifically valid `PASS`; repeat an `UNKNOWN` review and
   reject `FAIL` or `BLOCKED` completion evidence.
9. Call `read_experiment_terminal_evidence`.
10. Call `ingest_harness_experiment_result` with the real artifact base
    directory so every local artifact is rehashed.
11. If the run is stuck or cancelled, call `force_stop_experiment`, retain its
    cleanup receipt, and do not ingest it as a scientific result.

**Done when:** the accepted immutable `experiment-result/v1`, Harness review,
acceptance, terminal evidence, artifacts, and execution binding all agree.

### [ ] Task 10 — Record result-driven learning and honest acceleration

After accepted-result ingestion:

1. Delegate interpretation to the separate `results-analyst`.
2. Record `updated-decision/v1` linked to the exact result digest.
3. State what the result changed, the remaining uncertainty, and the next most
   informative experiment. Do not preselect the conclusion.
4. Let the journal add the acceptance-bound decision-timing artifact.
5. Build `acceleration-summary/v1` bound to both result and decision digests.
6. Preserve censoring and failed/time-out trial counts.
7. Make a positive overall speed claim only if both trial and inclusive
   wall-time ratios improve, quality non-inferiority passes, overhead is
   measured for both arms, and compute is available.
8. Separate observed results from conservative, expected, and optimistic
   path-to-10x forecasts.
9. Include remaining bottlenecks, parallelizable/automatable steps, evidence
   still needed, conditions for approaching 10x, and claim boundaries.
10. Call `get_learning_receipt` with `final=true`.
11. Call `retire_experiment` for accepted work.
12. Call `shutdown_research_harness` with the exact phrase
    `SHUTDOWN RESEARCH HARNESS`.

An inconclusive or negative result is still valid scientific evidence. Report
it exactly rather than rerunning until a positive outcome appears.

### [ ] Task 11 — Export and validate the complete submission evidence bundle

After the Harness has shut down, export the chain, receipt, result, and
acceleration record. This command prompts for the real question ID and rejects
missing or duplicate terminal records:

```bash
(
set -euo pipefail
cd /jumbo/lisp/f004ndc/projects/Ai-Researcher

read -r -p 'Exact research question ID to export: ' QUESTION_ID
export QUESTION_ID

uv run python - <<'PY'
import json
import os
from pathlib import Path

from ai_researcher.journal import ResearchJournal

question_id = os.environ["QUESTION_ID"]
journal = ResearchJournal("runtime/research-journal.sqlite3")
chain = journal.reconstruct_chain(question_id)
receipt = journal.learning_receipt(question_id, final=True)

output = Path("artifacts")
output.mkdir(parents=True, exist_ok=True)

def write(name: str, value: object) -> None:
    (output / name).write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

write("research-chain.json", chain)
write("learning-receipt.json", receipt)

for schema, filename in {
    "experiment-result/v1": "experiment-result.json",
    "acceleration-summary/v1": "acceleration-summary.json",
}.items():
    records = [record for record in chain["records"] if record["schema"] == schema]
    if len(records) != 1:
        raise SystemExit(f"expected exactly one {schema}; found {len(records)}")
    write(filename, records[0])

print("Exported final chain and receipt:", receipt["receipt_digest"])
PY
)
```

Create the rubric evidence mapping interactively. Every entered path must exist;
the command never infers a status from an expected filename:

```bash
(
set -euo pipefail
cd /jumbo/lisp/f004ndc/projects/Ai-Researcher

uv run python - <<'PY'
import json
from pathlib import Path

allowed = {"MET", "PARTIAL", "UNMET", "UNAVAILABLE"}
criteria = (
    "omnigent_orchestration",
    "breakthrough_potential",
    "discovery_acceleration_and_learning",
    "scientific_rigor",
    "creativity_and_responsibility",
)

rubric = {}
for criterion in criteria:
    while True:
        status = input(f"{criterion} status {sorted(allowed)}: ").strip().upper()
        if status in allowed:
            break
        print("Invalid status")
    raw_paths = input(
        "Comma-separated evidence paths that actually exist, or blank: "
    ).strip()
    paths = [item.strip() for item in raw_paths.split(",") if item.strip()]
    missing = [item for item in paths if not Path(item).exists()]
    if missing:
        raise SystemExit(f"missing claimed evidence paths: {missing}")
    notes = input("Short claim-boundary note: ").strip()
    rubric[criterion] = {
        "status": status,
        "artifacts": paths,
        "notes": notes,
    }

chain = json.loads(Path("artifacts/research-chain.json").read_text())
receipt = json.loads(Path("artifacts/learning-receipt.json").read_text())
wrapper = {
    "research_chain": chain,
    "learning_receipt": receipt,
    "rubric_evidence": rubric,
}
Path("artifacts/report-input.json").write_text(
    json.dumps(wrapper, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

uv run python scripts/render_research_report.py \
  artifacts/report-input.json \
  --rubric-output artifacts/rubric-artifact-map.json \
  | tee artifacts/terminal-report.txt
)
```

Copy the ignored live evidence into the external submission bundle and hash it:

```bash
(
set -euo pipefail
cd /jumbo/lisp/f004ndc/projects/Ai-Researcher

EVIDENCE=/jumbo/lisp/f004ndc/projects/Ai-Researcher-submission-evidence
mkdir -p "$EVIDENCE/live-run"

cp -a artifacts "$EVIDENCE/live-run/"
cp -a runtime/research-journal.sqlite3 "$EVIDENCE/live-run/"

find "$EVIDENCE/live-run" -type f -print0 \
  | sort -z \
  | xargs -0 sha256sum \
  > "$EVIDENCE/live-run-SHA256SUMS.txt"
)
```

Also retain the dataset metadata, Omnigent exports, task card, Harness lane/run
records, `RESULT.json`, completion review, acceptance, terminal evidence,
provider transcript, telemetry sources, trial logs, limitations, and next
experiment. Review the bundle for secrets before sharing it.

### [ ] Task 12 — Run two clean rehearsals

The conservative acceptance interpretation is one retained official live run
plus two additional complete rehearsals. If the organizers explicitly allow
the official run to count as a rehearsal, document that ruling rather than
assuming it.

Create two fresh, exact-commit rehearsal checkouts:

```bash
(
set -euo pipefail

SOURCE_URL=https://github.com/buh07/Ai-Researcher.git
COMMIT=8a814084041a3a3051bcb751552474c8242f623b
BASE=/jumbo/lisp/f004ndc/projects/Ai-Researcher-rehearsals

mkdir -p "$BASE"

for NUMBER in 1 2; do
  DEST="$BASE/rehearsal-$NUMBER"
  if test -e "$DEST"; then
    echo "Refusing to overwrite existing rehearsal directory: $DEST" >&2
    exit 1
  fi
  git clone "$SOURCE_URL" "$DEST"
  git -C "$DEST" checkout --detach "$COMMIT"
  (
    cd "$DEST"
    uv sync --frozen
    uv run python scripts/validate_bundle.py
    uv run pytest
  )
done
)
```

For each checkout, repeat Tasks 2 through 11 with a new journal, Harness epoch,
human sessions, agent sessions, lane/run identity, and evidence directory.

A rehearsal passes only when it needs no hand-edited SQLite, task-card, run-ID,
or Harness state and visibly includes both human gates, live feasibility, real
specialists, overlap or honest `UNMET`, cited evidence, two candidates,
independent safety, bounded execution, immutable result ingestion,
result-driven replanning, receipt reconstruction, rubric mapping, retirement,
and shutdown. Record commands, duration, cost, skips, and any failure.

### [ ] Task 13 — Record and package the two-minute demo

`DEMO.md` is the script, not the completed demo. Use the best retained live run
and show, in order:

1. Human-owned objective and feasibility
2. Specialist handoffs and measured branch overlap
3. Evidence-backed hypothesis
4. Two candidates and the selection rationale
5. Independent safety review
6. Exact human approval and launch boundary
7. Immutable experiment result
8. What changed and the next experiment
9. Observed acceleration, lower bound, or honest non-improvement
10. Assumption-bounded path toward 10x
11. Final receipt and rubric-to-artifact map

Keep the video or accepted live-demo format within two minutes. Clearly label
fixture output, forecasts, unavailable values, and single-task limitations.

### [ ] Task 14 — Assemble and audit the final submission

The final submission must include:

- Public repository URL and exact submission commit
- Agent definitions, policies, permissions, and consolidated contracts
- Attributable human objective and approval records
- Feasibility, dataset identity, digest, license, privacy, and access evidence
- Cited evidence packages and Omnigent provider/session identities
- Hypotheses, candidates, selection and rejection rationales, and safety review
- Task-card and launch authority digests
- Experiment code, immutable result, logs, and artifact digests
- Updated decision and next experiment
- Acceleration summary and conservative/expected/optimistic scaling scenarios
- Final learning receipt and research chain
- Rubric map whose claimed paths all exist
- Test logs, live-run evidence, and rehearsal evidence
- Limitations and future validation
- Two-minute demo

Update `docs/SUBMISSION_CHECKLIST.md` only after inspecting each referenced
artifact. Do not check an item because code, a fixture, or an expected path
exists.

If the submission service requires results inside Git, create a deliberately
sanitized `submission-evidence/` directory and review it for secrets before
committing. Do not force-add raw `runtime/` or provider configuration. Any new
commit becomes a new submission identity and requires Task 1 again.

## Longer-term scientific validation

These items do not block the current software release, but they remain necessary
before broad scientific or 10x-acceleration claims.

### [ ] Repeat across seeds

Predeclare multiple split seeds, run separately authorized matched experiments,
retain every failed/timed-out run, and report distributions and uncertainty
rather than selecting the best result.

### [ ] Extend beyond OpenML task 59

Generalize the pinned dataset configuration, add dataset-specific fixtures and
tests, complete new license/privacy checks, obtain new human authority, and
repeat the matched protocol on tasks with different sizes and structures.

### [ ] Conduct prospective domain validation

Choose a real scientific domain with costly experiment selection, define
domain-specific safety and outcome criteria, compare against expert selection,
and validate whether fewer computational tests translate into better scientific
decisions.

### [ ] Run ablations

Compare evidence-guided ordering against fixed, random, and expert ordering;
parallel versus serial retrieval; reviewed-failure memory on/off; and different
providers, models, and agent topologies under matched budgets.

### [ ] Measure the path to 10x

Instrument all remaining bottlenecks, vary safe concurrency, measure scaling,
and confirm that scientific quality, safety, and reproducibility do not regress.
Treat conservative, expected, and optimistic scenarios as forecasts until they
are prospectively observed.

### [ ] Complete production hardening

Add OS/container isolation, network and billing enforcement, multi-tenant
authorization, managed secret storage, independent security review, and
external reproducibility replication before regulated or hostile-environment
deployment.
