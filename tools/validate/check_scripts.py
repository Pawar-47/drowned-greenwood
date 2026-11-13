#!/usr/bin/env python3
"""Static checks on every script in the repository, before anything expensive runs.

Run:
    python tools/validate/check_scripts.py

Why this exists: Phase 0 burned over two hours of CI on probe iterations, and a share of those
runs died on things a syntax check catches in seconds — a Python indentation error, a shell
quoting mistake, a malformed workflow YAML. Blender and Infinigen are far too slow to use as a
syntax checker.

What it checks:
  * every .py file parses (ast.parse) — catches syntax and indentation errors
  * every .sh file passes `bash -n` — catches shell syntax without executing it
  * every workflow .yml parses as YAML and has the keys GitHub requires
  * every .json file in the repository parses

What it deliberately does not check: logic, imports, or anything needing Blender. This only
guarantees that a run gets to start.
"""

import ast
import json
import os
import re
import subprocess
import sys

SKIP_DIRS = {
    ".git",
    "node_modules",
    "vendor",
    "__pycache__",
    ".godot",
    "extracted",
    "artifacts",
    "downloaded",
}
WORKFLOW_DIR = os.path.join(".github", "workflows")

# The concurrency policy, per workflow file. This replaced a single rule — "every workflow shares
# the group ci-serial" — that was wrong in a way worth recording.
#
# A concurrency group is itself the mechanism that DROPS runs: GitHub keeps one running and one
# pending per group, and a newer arrival replaces the pending one. A shared group therefore let a
# push-triggered validate replace a queued manual Phase 0 or history-purge dispatch, and the
# manual run was never created at all. Sharing one group across every workflow made that worse
# than it needed to be.
#
# So the policy is now per workflow, and a workflow that is not listed here FAILS the check:
# adding one forces a deliberate decision about what happens when two runs collide.
#
#   None                     -> the workflow must declare no concurrency block at all, so every
#                               dispatch executes. For runs that must never be dropped.
#   cancel_in_progress True  -> superseded runs are cancelled mid-way. Only correct when the
#                               answer is worthless once a newer commit exists.
#   cancel_in_progress False -> a running run always finishes; a second waits.
CONCURRENCY_POLICY = {
    # Answers "does this tree pass?". A run superseded by a newer commit on the same branch has
    # no value, and cancelling is visible in the UI rather than silent.
    "validate.yml": {"cancel_in_progress": True},
    # A gate. A run killed half way is a run wasted, which is how 120 minutes were burned before.
    "phase0-tool-evaluation.yml": {"cancel_in_progress": False},
    # Rewrites history and force-pushes. A dropped apply would look like it did nothing, so every
    # dispatch must execute. Two applies at once are prevented by an explicit in-flight check in
    # the workflow itself, not by a group that can drop runs.
    "history-purge.yml": None,
}

# Every group seen, so two workflows sharing one can be caught: that is the failure this policy
# exists to prevent, and it is invisible in review because each file looks correct alone.
CONCURRENCY_GROUPS = {}

# Sampler hints Godot 4 actually accepts, from its shading-language reference. `hint_black`
# looks plausible and is not a hint at all; it fails to compile. A static check catches that in
# seconds instead of waiting for a Godot run.
VALID_SAMPLER_HINTS = {
    "source_color",
    "hint_normal",
    "hint_default_white",
    "hint_default_black",
    "hint_default_transparent",
    "hint_anisotropy",
    "hint_screen_texture",
    "hint_depth_texture",
    "hint_normal_roughness_texture",
    "hint_roughness",
    "hint_roughness_r",
    "hint_roughness_g",
    "hint_roughness_b",
    "hint_roughness_a",
    "hint_roughness_normal",
    "hint_roughness_gray",
}

# Hints known to be wrong, kept explicit so the error message can say what to use instead.
WRONG_SAMPLER_HINTS = {
    "hint_black": "hint_default_black",
    "hint_white": "hint_default_white",
    "hint_transparent": "hint_default_transparent",
}

# Samplers that may legitimately clamp instead of repeat, keyed by name, each with the reason it is
# safe to clamp.
#
# Empty, and it should stay that way for a while: every sampler in this project is sampled with a
# UV that leaves 0..1 — a world-space UV crosses 1.0 at 100 m, and a time-driven one within a
# second — and a clamped sample there freezes the surface with no error anywhere. That is a shader
# that compiles, renders, and is simply wrong. Widening this needs a reason, not a name.
CLAMPED_SAMPLERS = {}

# `uniform sampler2D <name> : <hints>;` — used only for the repeat rule below. The per-line hint
# loop above cannot see the sampler's name, and reading it out of the line with string replaces
# turned `sampler2DArray` into `Array`.
SAMPLER_DECL = re.compile(
    r"uniform\s+(sampler[A-Za-z0-9]*)\s+(\w+)\s*:([^;]*);"
)


def walk(extension):
    """Yield paths ending in `extension`, skipping dependencies, build output and caches.

    Only `.git` itself is skipped by exact name. A prefix test would also skip `.github`,
    which is where the workflows live — the check would then silently validate no YAML at all.
    """
    for root, dirs, files in os.walk("."):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            if name.endswith(extension):
                yield os.path.join(root, name)


def check_python(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            source = handle.read()
    except OSError as exc:
        return "%s: cannot read (%s)" % (path, exc)
    try:
        ast.parse(source, filename=path)
    except SyntaxError as exc:
        return "%s:%s: %s" % (path, exc.lineno, exc.msg)
    return None


def check_shell(path):
    try:
        result = subprocess.run(["bash", "-n", path], capture_output=True, text=True)
    except FileNotFoundError:
        return None  # no bash available: skip rather than fail
    if result.returncode != 0:
        return "%s: %s" % (path, result.stderr.strip().replace("\n", " | ")[:300])
    return None


# GitHub's `${{ ... }}` expression syntax is not shell, and bash rejects it as a bad
# substitution. It is blanked out before the syntax check so that a valid workflow is not
# reported as a broken script. An expression with a brace inside it (fromJSON('{"a":1}')) is
# the one case this leaves behind, and it fails loudly rather than passing quietly.
WORKFLOW_EXPRESSION = re.compile(r"\$\{\{[^{}]*\}\}")

# Which workflow steps had their shell checked, so main() can refuse to report success if the
# check never ran. A checker that silently checks nothing is the failure mode in LESSONS #3.
RUN_BLOCKS_CHECKED = []


def check_run_block(step, path, job_name):
    """`bash -n` the shell a workflow step will actually run.

    The `run:` blocks were the one scripts in this repository that nothing syntax-checked: the
    .sh files were, and the YAML was, but the shell inline in a workflow was not. A quoting
    mistake there surfaces only when the runner reaches that step, minutes or hours in — which
    is the failure mode this whole file exists to move earlier. GitHub runs these with
    `bash -e {0}` by default, so `bash -n` is the right check for them.
    """
    script = step.get("run")
    if not isinstance(script, str) or not script.strip():
        return None
    shell = step.get("shell") or ""
    if shell and not str(shell).startswith("bash"):
        return None  # python, pwsh and friends are not bash
    RUN_BLOCKS_CHECKED.append("%s:%s" % (path, job_name))
    stripped = WORKFLOW_EXPRESSION.sub("EXPR", script)
    try:
        result = subprocess.run(["bash", "-n"], input=stripped, capture_output=True, text=True)
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        detail = result.stderr.strip().replace("\n", " | ")[:300]
        return "%s: job %s: run block is not valid shell (%s)" % (path, job_name, detail)
    return None


# A third-party action must be referenced by a 40-character commit SHA, not by a tag.
#
# A tag is mutable: `@v4` is a pointer its owner can repoint at different code, and this
# repository would then run code that nobody reviewed and nothing recorded. A commit SHA is
# immutable, so the action that runs is the one that was checked. The version is kept in a
# trailing comment so a human can still see what it is, and so Dependabot can bump it.
ACTION_SHA = re.compile(r"^[^@]+@[0-9a-f]{40}$")
ACTIONS_PINNED = []


def check_action_pin(step, path, job_name):
    uses = step.get("uses")
    if not isinstance(uses, str) or not uses.strip():
        return None
    target = uses.strip()
    # Local actions (`./.github/actions/x`) and Docker images are not tag-pinned actions.
    if target.startswith("./") or target.startswith("docker://"):
        return None
    if ACTION_SHA.match(target.split()[0]):
        ACTIONS_PINNED.append(target.split()[0])
        return None
    return (
        "%s: job %s: %r is not pinned to a commit SHA; a tag can be repointed at different "
        "code. Use <owner>/<repo>@<40-hex-sha> # <tag>" % (path, job_name, target)
    )


def no_duplicate_keys(pairs):
    """Reject a JSON object that repeats a key.

    Valid JSON, and silently wrong: the loader keeps the last value and drops the rest, so a
    second "note" in a manifest group vanishes without a word. This was found by writing one.
    """
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError("duplicate key %r in one object" % key)
        seen[key] = value
    return seen


def check_json(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            json.load(handle, object_pairs_hook=no_duplicate_keys)
    except json.JSONDecodeError as exc:
        return "%s:%s: %s" % (path, exc.lineno, exc.msg)
    except ValueError as exc:
        return "%s: %s" % (path, exc)
    except OSError as exc:
        return "%s: cannot read (%s)" % (path, exc)
    return None


def check_workflow(path):
    """Parse a workflow and check the keys GitHub needs to accept it at all."""
    try:
        import yaml
    except ImportError:
        return None  # no PyYAML: skip rather than fail
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        return "%s: invalid YAML (%s)" % (path, str(exc).replace("\n", " | ")[:300])

    if not isinstance(data, dict):
        return "%s: not a mapping" % path

    # PyYAML reads the bare key `on` as the boolean True, so it is looked up under both
    # spellings rather than assuming a string.
    if "on" not in data and True not in data:
        return "%s: no trigger ('on') block" % path
    if "jobs" not in data or not isinstance(data["jobs"], dict):
        return "%s: no jobs mapping" % path

    for job_name, job in data["jobs"].items():
        if not isinstance(job, dict):
            return "%s: job %s is not a mapping" % (path, job_name)
        # Step names are scoped to their job: two jobs may both have a "Static checks" step.
        step_names = set()
        if "runs-on" not in job:
            return "%s: job %s has no runs-on" % (path, job_name)
        if "steps" not in job and "uses" not in job:
            return "%s: job %s has neither steps nor uses" % (path, job_name)
        for step in job.get("steps") or []:
            if not isinstance(step, dict):
                return "%s: job %s has a step that is not a mapping" % (path, job_name)
            if "uses" not in step and "run" not in step:
                return "%s: job %s has a step with neither uses nor run (%r)" % (
                    path,
                    job_name,
                    str(step)[:60],
                )
            # A step is `uses` or `run`, never both. Both means two steps were merged by an edit.
            if "uses" in step and "run" in step:
                return (
                    "%s: job %s has a step with both `uses` and `run` — a workflow step is one or "
                    "the other, so two steps were merged" % (path, job_name)
                )
            step_name = step.get("name")
            if isinstance(step_name, str) and step_name.strip():
                if step_name in step_names:
                    return (
                        "%s: job %s has two steps named %r; the second replaces the first in the "
                        "job's log and in the report" % (path, job_name, step_name)
                    )
                step_names.add(step_name)
            error = check_run_block(step, path, job_name)
            if error:
                return error
            error = check_action_pin(step, path, job_name)
            if error:
                return error

    name = os.path.basename(path)
    if name not in CONCURRENCY_POLICY:
        return (
            "%s: no concurrency policy for this workflow. Add it to CONCURRENCY_POLICY in "
            "tools/validate/check_scripts.py so the decision about colliding runs is deliberate "
            "rather than inherited" % path
        )

    concurrency = data.get("concurrency")
    expected = CONCURRENCY_POLICY[name]

    if expected is None:
        if concurrency is not None:
            return (
                "%s: must declare NO concurrency block. This workflow's runs must never be "
                "dropped, and a group is what drops them: GitHub keeps one pending run per group "
                "and a newer arrival replaces it" % path
            )
        return None

    if not isinstance(concurrency, dict):
        return "%s: no concurrency block, but its policy expects one" % path
    group = concurrency.get("group")
    if not group:
        return "%s: concurrency block has no group" % path
    # A group shared with another workflow is the bug this policy replaced: it makes one
    # workflow able to replace another's queued run.
    if group in CONCURRENCY_GROUPS:
        return (
            "%s: concurrency group %r is already used by %s. Sharing a group across workflows "
            "lets one replace another's queued run" % (path, group, CONCURRENCY_GROUPS[group])
        )
    CONCURRENCY_GROUPS[group] = name
    # PyYAML reads `false` as Python False. Anything else — including the string "false" — is a
    # non-empty value GitHub treats as true.
    want = expected["cancel_in_progress"]
    if concurrency.get("cancel-in-progress") is not want:
        return (
            "%s: cancel-in-progress must be %s for this workflow's policy, got %r"
            % (path, "true" if want else "false", concurrency.get("cancel-in-progress"))
        )
    return None


def check_shader(path):
    """Catch the shader mistakes that are checkable without a compiler.

    Only hints are checked here. Everything else about a shader needs Godot to compile it,
    which is what the Godot shader probe is for; this is the cheap first pass.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            source = handle.read()
    except OSError as exc:
        return "%s: cannot read (%s)" % (path, exc)

    for line_number, line in enumerate(source.splitlines(), start=1):
        # Strip comments first. A commented-out declaration is not a declaration, and a trailing
        # `// note` after a valid hint would otherwise be read as part of the hint name:
        #   uniform sampler2D x : hint_default_black; // albedo
        # would have produced the "hint" "hint_default_black; // albedo" and been rejected.
        code = line.split("//", 1)[0]
        if "uniform sampler" not in code or ":" not in code:
            continue

        # A uniform can carry several hints, separated by commas:
        #   uniform sampler2D noise : hint_default_black, filter_linear, repeat_enable;
        # Reading only the first whitespace-delimited token leaves the comma attached, so
        # "hint_default_black," looked like an unknown hint and a perfectly valid shader was
        # rejected. Split on commas and check each hint on its own.
        declaration = code.split(":", 1)[1].strip().rstrip(";")
        for raw_hint in declaration.split(","):
            hint = raw_hint.strip()
            # A default value ("= ...") follows the hints; it is not one.
            hint = hint.split("=", 1)[0].strip()
            if not hint:
                continue
            if hint in WRONG_SAMPLER_HINTS:
                return "%s:%s: %r is not a Godot hint; use %r" % (
                    path,
                    line_number,
                    hint,
                    WRONG_SAMPLER_HINTS[hint],
                )
            if hint in VALID_SAMPLER_HINTS:
                continue
            # filter_* and repeat_* are documented hint families with open-ended suffixes
            # (filter_linear_mipmap_anisotropic, repeat_disable, ...), so a prefix check is
            # correct for them and an allowlist would go stale.
            if hint.startswith(("filter_", "repeat_")):
                continue
            if hint.startswith("hint_"):
                return "%s:%s: unknown sampler hint %r" % (path, line_number, hint)

    # Every sampler must repeat. This is the one hint whose absence compiles, renders, and then
    # quietly stops working: a clamped sample of a world-space or time-driven UV freezes to an edge
    # texel. A shader cannot be inspected for its UVs by a static check, so the rule is the
    # conservative one — repeat, unless the sampler is argued into CLAMPED_SAMPLERS with a reason.
    #
    # Comments are stripped first: the wind include documents this exact rule in prose, and prose
    # is not a declaration.
    code_only = "\n".join(line.split("//", 1)[0] for line in source.splitlines())
    for match in SAMPLER_DECL.finditer(code_only):
        name = match.group(2)
        if name in CLAMPED_SAMPLERS:
            continue
        hints = [h.strip().split("=", 1)[0].strip() for h in match.group(3).split(",")]
        # Exactly `repeat_enable`. `repeat_disable` is the opposite and must not satisfy this.
        if "repeat_enable" in hints:
            continue
        return (
            "%s: sampler %r does not declare repeat_enable. Every sampler here is sampled with a "
            "UV that leaves 0..1 — world-space crosses it at 100 m, time-driven within a second — "
            "and a clamped sample freezes the surface with no error anywhere. Add repeat_enable, "
            "or add %r to CLAMPED_SAMPLERS in tools/validate/check_scripts.py with the reason it "
            "is safe to clamp" % (path, name, name)
        )
    return None


def check_repo_hygiene():
    """Guard the two limits git itself enforces, before a push discovers them.

    GitHub blocks a file over 100 MB outright and warns at 50 MB, and the brief sets 20 MB as
    this project's own ceiling. A binary that slips in is also permanent: it stays in history
    after a later commit deletes it. Catching it here costs a second; catching it after the push
    costs a history rewrite.

    The source-artifact extensions are here because they must never be committed at all: a
    `.blend` is the authoring file, and `.hdr`/`.exr` are the pre-bake sources. The pipeline
    bakes them down; committing them would multiply the repository size for no shipped benefit.
    """
    problems = []
    max_file = 20 * 1024 * 1024
    forbidden = (".blend", ".blend1", ".blend2", ".hdr", ".exr")
    largest = (0, "")
    total = 0
    count = 0

    for root, dirs, files in os.walk("."):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in files:
            path = os.path.join(root, name)
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            count += 1
            total += size
            if size > largest[0]:
                largest = (size, path)
            if size > max_file:
                problems.append(
                    "%s is %.1f MB, over the 20 MB per-file limit; move it to a Release pack"
                    % (path, size / (1024 * 1024))
                )
            if name.lower().endswith(forbidden):
                problems.append(
                    "%s is a source artifact that must never be committed" % path
                )

    print(
        "repository: %d files, %.1f MB total, largest %.1f MB (%s)"
        % (count, total / (1024 * 1024), largest[0] / (1024 * 1024), largest[1] or "none")
    )
    return problems


def main():
    problems = []
    counts = {"python": 0, "shell": 0, "json": 0, "yaml": 0, "shader": 0}

    for path in walk(".py"):
        counts["python"] += 1
        error = check_python(path)
        if error:
            problems.append(error)

    for path in walk(".sh"):
        counts["shell"] += 1
        error = check_shell(path)
        if error:
            problems.append(error)

    for path in walk(".json"):
        counts["json"] += 1
        error = check_json(path)
        if error:
            problems.append(error)

    # Shader includes: the wind and wetness files, and anything else in shaders/.
    for extension in (".gdshaderinc", ".gdshader"):
        for path in walk(extension):
            counts["shader"] += 1
            error = check_shader(path)
            if error:
                problems.append(error)

    # Workflows only, not every YAML in the tree.
    workflows_dir = os.path.abspath(WORKFLOW_DIR)
    for path in walk(".yml"):
        if os.path.dirname(os.path.abspath(path)) != workflows_dir:
            continue
        counts["yaml"] += 1
        error = check_workflow(path)
        if error:
            problems.append(error)

    print(
        "checked: %d python, %d shell, %d json, %d shader, %d workflow yaml, %d run block, "
        "%d pinned action"
        % (
            counts["python"],
            counts["shell"],
            counts["json"],
            counts["shader"],
            counts["yaml"],
            len(RUN_BLOCKS_CHECKED),
            len(ACTIONS_PINNED),
        )
    )

    # A checker that finds nothing to check is the bug from docs/LESSONS.md #3: it would pass
    # silently forever. Refuse to report success unless it actually examined something,
    # including the workflows, which a bad directory filter once skipped entirely.
    if counts["python"] == 0 or counts["shell"] == 0:
        problems.append(
            "the walker found no %s files; it is looking in the wrong place"
            % ("python" if counts["python"] == 0 else "shell")
        )
    if counts["yaml"] == 0:
        problems.append("the walker found no workflow YAML; the workflow filter is wrong")
    if counts["shader"] == 0:
        problems.append("the walker found no shaders; the shader filter is wrong")
    if counts["yaml"] and not RUN_BLOCKS_CHECKED:
        problems.append(
            "no workflow run block was shell-checked; the run-block check is not running"
        )
    # A policy entry for a workflow that no longer exists means a workflow was renamed and its
    # concurrency decision was silently lost. The missing-policy case is reported per file above,
    # so it is not duplicated here.
    on_disk = {
        os.path.basename(path)
        for path in walk(".yml")
        if os.path.dirname(os.path.abspath(path)) == os.path.abspath(WORKFLOW_DIR)
    }
    stale = sorted(set(CONCURRENCY_POLICY) - on_disk)
    if stale:
        problems.append(
            "concurrency policies for workflows that do not exist: %s" % stale
        )

    if counts["yaml"] and not ACTIONS_PINNED:
        problems.append(
            "no workflow action was SHA-pinned; the action-pin check is not running"
        )

    problems.extend(check_repo_hygiene())

    if problems:
        print("static checks failed:", file=sys.stderr)
        for problem in problems:
            print("  - " + problem, file=sys.stderr)
        return 1

    print("static checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
