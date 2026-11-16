"""Checks that the pieces of the automation agree with each other.

These are the things that break silently: rename a dropdown option and the
area label stops being applied, delete a label and a form quietly creates
none. Run in CI by lint.yml; needs PyYAML.
"""
import json
import pathlib
import re
import sys

import yaml

GITHUB = pathlib.Path(__file__).resolve().parents[2]
problems: list[str] = []


def check(ok: bool, message: str) -> None:
    if not ok:
        problems.append(message)


def load_yaml(path: pathlib.Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


config = json.loads((GITHUB / "automation.json").read_text())
label_defs = json.loads((GITHUB / "labels.json").read_text())
label_names = [d["name"] for d in label_defs]
known = set(label_names)

# --- labels.json itself ------------------------------------------------------
check(len(label_names) == len(set(label_names)), "labels.json has duplicate names")
for d in label_defs:
    check(bool(re.fullmatch(r"[0-9a-f]{6}", d["color"])), f"label {d['name']!r}: colour must be 6 hex digits")
    check(len(d.get("description", "")) <= 100, f"label {d['name']!r}: description over 100 characters")

# --- automation.json ---------------------------------------------------------
check(bool(config["maintainers"]), "automation.json: maintainers is empty")
for key, name in config["labels"].items():
    check(name in known, f"automation.json labels.{key} = {name!r} is not in labels.json")
for option, name in config["areas"].items():
    check(name in known, f"automation.json areas[{option!r}] -> {name!r} is not in labels.json")

# --- issue forms -------------------------------------------------------------
area_field = config["form"]["areaField"]
allowed_areas = set(config["areas"]) | set(config["noAreaOptions"])
forms = sorted((GITHUB / "ISSUE_TEMPLATE").glob("*.yml"))
check(any(f.name != "config.yml" for f in forms), "no issue forms found")

for path in forms:
    data = load_yaml(path)
    if path.name == "config.yml":
        check(data.get("blank_issues_enabled") is False, "config.yml: blank issues should be disabled")
        continue
    for label in data.get("labels", []):
        check(label in known, f"{path.name}: label {label!r} is not in labels.json")
    headings = []
    for item in data.get("body", []):
        if item["type"] == "markdown":
            continue
        heading = item["attributes"]["label"]
        headings.append(heading)
        if item["type"] == "dropdown" and heading == area_field:
            options = set(item["attributes"]["options"])
            check(
                options <= allowed_areas,
                f"{path.name}: area options not mapped in automation.json: {sorted(options - allowed_areas)}",
            )
            check(
                set(config["areas"]) <= options,
                f"{path.name}: area options missing from the form: {sorted(set(config['areas']) - options)}",
            )
    if path.name == "bug_report.yml":
        check(area_field in headings, f"bug_report.yml has no {area_field!r} field")
        for field in config["form"]["evidenceFields"]:
            check(field in headings, f"bug_report.yml has no {field!r} field (triage looks for it)")
    else:
        # Only the bug form may carry the evidence fields, or triage would
        # hold feature requests and questions for logs.
        check(
            not set(config["form"]["evidenceFields"]) <= set(headings),
            f"{path.name} has all evidence fields, so triage would treat it as a bug report",
        )

# --- labeler, dependabot, release notes --------------------------------------
for name in load_yaml(GITHUB / "labeler.yml"):
    check(name in known, f"labeler.yml: label {name!r} is not in labels.json")
for update in load_yaml(GITHUB / "dependabot.yml")["updates"]:
    for name in update.get("labels", []):
        check(name in known, f"dependabot.yml: label {name!r} is not in labels.json")
for category in load_yaml(GITHUB / "release.yml")["changelog"]["categories"]:
    for name in category["labels"]:
        check(name == "*" or name in known, f"release.yml: label {name!r} is not in labels.json")

# --- workflows only call scripts that exist ----------------------------------
for workflow in sorted((GITHUB / "workflows").glob("*.yml")):
    for script in re.findall(r"require\('\./\.github/scripts/([\w.-]+)'\)", workflow.read_text()):
        check((GITHUB / "scripts" / script).is_file(), f"{workflow.name}: scripts/{script} does not exist")

if problems:
    print("Configuration problems:")
    for p in problems:
        print(f"  - {p}")
    sys.exit(1)
print("ok: forms, labels, labeler, dependabot, release notes and workflows are consistent")
