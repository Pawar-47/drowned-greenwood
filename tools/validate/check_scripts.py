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


def check_json(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            json.load(handle)
    except json.JSONDecodeError as exc:
        return "%s:%s: %s" % (path, exc.lineno, exc.msg)
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
    return None


def check_shader(path):
    """Catch the shader mistakes that are checkable without a compiler.

    Only hints are checked here. Everything else about a shader needs Godot to compile it,
    which is what the Godot shader probe is for; this is the cheap first pass.
    """
    import re

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            source = handle.read()
    except OSError as exc:
        return "%s: cannot read (%s)" % (path, exc)

    for line_number, line in enumerate(source.splitlines(), start=1):
        if "uniform sampler" not in line or ":" not in line:
            continue
        hint = line.split(":", 1)[1].strip().split()[0].rstrip(";")
        if hint in WRONG_SAMPLER_HINTS:
            return "%s:%s: %r is not a Godot hint; use %r" % (
                path,
                line_number,
                hint,
                WRONG_SAMPLER_HINTS[hint],
            )
        if hint.startswith("hint_") and hint not in VALID_SAMPLER_HINTS:
            return "%s:%s: unknown sampler hint %r" % (path, line_number, hint)
    return None


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
        "checked: %d python, %d shell, %d json, %d shader, %d workflow yaml"
        % (
            counts["python"],
            counts["shell"],
            counts["json"],
            counts["shader"],
            counts["yaml"],
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

    if problems:
        print("static checks failed:", file=sys.stderr)
        for problem in problems:
            print("  - " + problem, file=sys.stderr)
        return 1

    print("static checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
