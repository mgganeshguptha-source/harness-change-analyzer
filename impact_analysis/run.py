"""
Control Plane CLI entrypoint.

Two modes:

  analyze  — story (+ registry) -> PROPOSED change set (YAML on disk)
             The Copilot SDK reasoning call must be wired in analyzer.py.

  manifest — APPROVED change set -> cross-repo manifest (YAML on disk)

Usage:
  python run.py analyze  --story-id BCBSM-1234 --title "..." \
                         --description "..." --owner MY-ORG \
                         --registry ../config/service-registry.yaml \
                         --out ../change-sets/BCBSM-1234.changeset.yaml

  python run.py manifest --change-set ../change-sets/BCBSM-1234.changeset.yaml \
                         --registry ../config/service-registry.yaml \
                         --out ../change-sets/BCBSM-1234.manifest.yaml
"""

from __future__ import annotations

import argparse
import sys

import yaml

from analyzer import analyze
from change_set import validate
from registry import ServiceRegistry


def cmd_analyze(args) -> int:
    from reasoning import get_reasoner
    from story_provider import get_provider

    provider = get_provider(args.story_source, stories_root=args.stories_root)
    try:
        story_input = provider.get(args.story_id)
    except (FileNotFoundError, ValueError) as e:
        print(f"[analyze] {e}", file=sys.stderr)
        return 2
    story = story_input.as_story_dict()

    reasoner = get_reasoner(args.reasoning)
    cs = analyze(story, args.registry, args.owner, reasoner=reasoner)
    with open(args.out, "w", encoding="utf-8") as fh:
        yaml.safe_dump(cs, fh, sort_keys=False)
    conf = cs["change_set"]["analysis"]["confidence"]
    print(f"[analyze] story '{args.story_id}' "
          f"(stream={story['stream']}, target={story['target_branch']})")
    print(f"[analyze] PROPOSED change set written: {args.out} "
          f"(confidence={conf})")
    print("[analyze] Review, set status: APPROVED (or edit consumers), "
          "then run 'manifest'.")
    return 0


def cmd_plan(args) -> int:
    from plan import generate_plan
    from reasoning import get_reasoner

    with open(args.change_set, "r", encoding="utf-8") as fh:
        cs = yaml.safe_load(fh)

    # validate the change set against the registry before planning
    reg = ServiceRegistry.load(args.registry)
    problems = validate(cs, reg)
    if problems:
        print("[plan] change set validation failed:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    reasoner = get_reasoner(args.reasoning)
    try:
        result = generate_plan(cs, stories_root=args.stories_root,
                               reasoner=reasoner)
    except ValueError as e:
        print(f"[plan] {e}", file=sys.stderr)
        return 1

    print(f"[plan] execution plan written: {result['plan_path']}")
    print("[plan] per-repo story files:")
    for repo, path in result["story_paths"].items():
        print(f"  - {repo}: {path}")
    print("[plan] Review the plan, then run SDLC-Harness manually per repo "
          "in the order shown.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="control-plane")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze")
    a.add_argument("--story-id", required=True,
                   help="story id; resolves to stories/<id>/story.md (PoC)")
    a.add_argument("--story-source", default=None,
                   choices=["repo"],
                   help="story source (PoC: repo folder; sharepoint/jira later)")
    a.add_argument("--stories-root", default="stories",
                   help="root folder holding story folders (PoC repo source)")
    a.add_argument("--owner", required=True, help="GitHub org/owner")
    a.add_argument("--registry", required=True)
    a.add_argument("--out", required=True)
    a.add_argument("--reasoning", choices=["mock", "copilot"], default=None,
                   help="reasoning backend (default: env HARNESS_REASONING or mock)")
    a.set_defaults(func=cmd_analyze)

    pl = sub.add_parser("plan")
    pl.add_argument("--change-set", required=True)
    pl.add_argument("--registry", required=True,
                    help="service registry (validates the change set)")
    pl.add_argument("--stories-root", default="stories",
                    help="root folder; per-repo stories + PLAN.md go under "
                         "<root>/<story>/per-repo/")
    pl.add_argument("--reasoning", choices=["mock", "copilot"], default=None,
                    help="reasoning backend for per-repo story drafting")
    pl.set_defaults(func=cmd_plan)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
