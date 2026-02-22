#!/usr/bin/env python3
"""Quiz CLI for spaced-repetition scheduling and clipboard handoff to AI."""

import json
import random
import re
import subprocess
import shlex
import sys
from pathlib import Path
from typing import Any

ITEMS_PATH = Path("items.json")
NOTES_PATH = Path("notes.md")
VALID_TYPES = {"quote", "concept", "scenario"}
VALID_STATUSES = {"unseen", "learning", "review"}
REQUIRED_ITEM_KEYS = {
    "id",
    "type",
    "topic",
    "answer",
    "status",
    "streak",
    "next_due",
    "source_ref"
}


def is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def collect_item_issues(item: Any, index: int) -> list[str]:
    location = f"item[{index}]"
    issues: list[str] = []

    if not isinstance(item, dict):
        issues.append(f"{location}: expected object, got {type(item).__name__}")
        return issues

    missing = sorted(REQUIRED_ITEM_KEYS.difference(item.keys()))
    if missing:
        issues.append(f"{location}: missing keys {missing}")

    item_id = item.get("id")
    if not is_non_negative_int(item_id):
        issues.append(f"{location}: id must be a non-negative integer")

    item_type = item.get("type")
    if item_type not in VALID_TYPES:
        issues.append(f"{location}: invalid type {item_type!r}")

    if "question" in item:
        question = item.get("question")
        if not isinstance(question, str) or not question.strip():
            issues.append(
                f"{location}: question must be a non-empty string "
                "(suggested prompt for AI tutor) when provided"
            )

    topic = item.get("topic")
    if not isinstance(topic, str) or not topic.strip():
        issues.append(f"{location}: topic must be a non-empty string")

    status = item.get("status")
    if status not in VALID_STATUSES:
        issues.append(f"{location}: invalid status {status!r}")

    answer = item.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        issues.append(f"{location}: answer must be a non-empty string")

    source_ref = item.get("source_ref")
    if not isinstance(source_ref, str) or not source_ref.strip():
        issues.append(f"{location}: source_ref must be a non-empty string")

    streak = item.get("streak")
    if not is_non_negative_int(streak):
        issues.append(f"{location}: streak must be a non-negative integer")

    next_due = item.get("next_due")
    if not isinstance(next_due, int) or isinstance(next_due, bool):
        issues.append(f"{location}: next_due must be an integer")
    elif next_due < 0:
        issues.append(f"{location}: next_due must be >= 0")

    return issues


def collect_validation_issues(data: list[Any]) -> list[str]:
    issues: list[str] = []
    seen_ids: set[int] = set()
    duplicate_ids: set[int] = set()

    for idx, item in enumerate(data):
        issues.extend(collect_item_issues(item, idx))
        if not isinstance(item, dict):
            continue

        item_id = item.get("id", -1)
        if is_non_negative_int(item_id):
            if item_id in seen_ids:
                duplicate_ids.add(item_id)
            seen_ids.add(item_id)

    for dup_id in sorted(duplicate_ids):
        issues.append(f"duplicate id: {dup_id}")

    return issues


def load_items(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise SystemExit(f"Missing items file: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise SystemExit(f"Expected a JSON array in {path}")

    issues = collect_validation_issues(data)
    if issues:
        preview = "\n".join(f"- {issue}" for issue in issues[:20])
        remaining = len(issues) - 20
        suffix = f"\n... and {remaining} more issue(s)." if remaining > 0 else \
            ""
        raise SystemExit(f"Invalid items in {path}:\n{preview}{suffix}")

    return data


def save_items(path: Path, items: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)
        f.write("\n")


def copy_to_clipboard(text: str) -> None:
    try:
        subprocess.run(["pbcopy"], input=text, text=True, check=True)
    except FileNotFoundError as exc:
        raise SystemExit(
            "Clipboard error: 'pbcopy' was not found on this machine."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            f"Clipboard error: 'pbcopy' failed with exit code {exc.returncode}."
        ) from exc


def build_payload(item: dict[str, Any]) -> str:
    # Redact answer to avoid leaking it in chat payloads.
    payload = dict(item)
    payload.pop("answer", None)
    # Use compact JSON to keep clipboard payload small.
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def find_item_index(items: list[dict[str, Any]], item_id: int) -> int:
    for index, item in enumerate(items):
        if int(item["id"]) == item_id:
            return index
    raise SystemExit(f"Item id not found in items.json: {item_id}")


def parse_item_id(raw_value: str) -> int:
    raw = raw_value.strip()
    if not raw:
        raise SystemExit("item_id must be a non-negative integer")
    try:
        value = int(raw, 10)
    except ValueError as exc:
        raise SystemExit("item_id must be a non-negative integer") from exc
    if value < 0:
        raise SystemExit("item_id must be a non-negative integer")
    return value


def parse_source_ref_ranges(source_ref: str) -> list[tuple[int, int]]:
    parts = [part.strip() for part in source_ref.split(",") if part.strip()]
    if not parts:
        raise SystemExit(f"Invalid source_ref: {source_ref!r}")

    ranges: list[tuple[int, int]] = []
    for part in parts:
        match = re.fullmatch(r"(\d+)(?:\s*-\s*(\d+))?", part)
        if match is None:
            raise SystemExit(f"Invalid source_ref segment: {part!r}")

        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else start
        if start < 1 or end < 1:
            raise SystemExit(f"source_ref line numbers must be >= 1: {part!r}")
        if start > end:
            raise SystemExit(
                f"source_ref range start must be <= end: {part!r}"
            )
        ranges.append((start, end))
    return ranges


def decrement_due_counters(items: list[dict[str, Any]]) -> None:
    for item in items:
        due = int(item["next_due"])
        if due > 0:
            item["next_due"] = due - 1


def schedule_interval_for_correct(streak: int) -> int:
    if streak in {1, 2}:
        return random.randint(8, 15)
    if streak == 3:
        return random.randint(20, 35)
    if streak == 4:
        return random.randint(50, 80)
    return random.randint(120, 200)


def select_next_item(items: list[dict[str, Any]]) -> dict[str, Any]:
    due_reviews = [
        item for item in items
        if int(item["next_due"]) == 0 and str(item["status"]) in {"learning", "review"}
    ]
    if due_reviews:
        return random.choice(due_reviews)

    unseen = [
        item for item in items
        if str(item["status"]) == "unseen"
    ]
    if unseen:
        return random.choice(unseen)

    raise SystemExit(
        "No available items to ask (no due items and no unseen items)."
    )


def cmd_question(items_path: Path) -> int:
    items = load_items(items_path)
    chosen = select_next_item(items)
    item_id = int(chosen["id"])
    payload = build_payload(chosen)
    print(payload)
    copy_to_clipboard(payload)
    print("copied to clipboard")
    return item_id


def cmd_grade(
        items_path: Path,
        current_item_id: int | None, is_correct: bool
    ) -> int:
    if current_item_id is None:
        raise SystemExit("No active item. Run 'question' first.")

    items = load_items(items_path)
    item_index = find_item_index(items, current_item_id)

    decrement_due_counters(items)
    item = items[item_index]

    if is_correct:
        new_streak = int(item["streak"]) + 1
        item["streak"] = new_streak
        item["next_due"] = int(item["next_due"]) + \
            schedule_interval_for_correct(new_streak)
        item["status"] = "learning" if new_streak == 1 else "review"
        print("Correct")
    else:
        item["streak"] = 0
        item["status"] = "learning"
        item["next_due"] = int(item["next_due"]) + random.randint(3, 6)
        print("Incorrect")

    save_items(items_path, items)
    return cmd_question(items_path)


def cmd_reset(items_path: Path) -> None:
    items = load_items(items_path)
    for item in items:
        item["streak"] = 0
        item["status"] = "unseen"
        item["next_due"] = 0
    save_items(items_path, items)
    print(f"Reset complete: {len(items)} items updated.")


def cmd_check(items_path: Path) -> None:
    if not items_path.exists():
        raise SystemExit(f"Missing items file: {items_path}")

    try:
        with items_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {items_path}: {exc}") from exc

    if not isinstance(data, list):
        raise SystemExit(f"Expected a JSON array in {items_path}")

    issues = collect_validation_issues(data)
    status_counts = {status: 0 for status in VALID_STATUSES}
    type_counts = {item_type: 0 for item_type in VALID_TYPES}
    due_now = 0
    due_soon = 0
    due_later = 0
    invalid_due = 0

    for item in data:
        if not isinstance(item, dict):
            continue

        item_type = item.get("type")
        if item_type in VALID_TYPES:
            type_counts[item_type] += 1

        status = item.get("status")
        if status in VALID_STATUSES:
            status_counts[status] += 1

        next_due = item.get("next_due", -1)
        if not is_non_negative_int(next_due):
            invalid_due += 1
        elif next_due == 0:
            due_now += 1
        elif next_due <= 6:
            due_soon += 1
        else:
            due_later += 1

    print("Check Report")
    print(f"Total items: {len(data)}")
    print(
        "Due buckets: "
        f"now={due_now}, soon(1-6)={due_soon}, later(7+)={due_later}, "
        f"invalid={invalid_due}"
    )
    print(
        "Status counts: "
        f"unseen={status_counts['unseen']}, "
        f"learning={status_counts['learning']}, "
        f"review={status_counts['review']}"
    )
    print(
        "Type counts: "
        f"quote={type_counts['quote']}, "
        f"concept={type_counts['concept']}, "
        f"scenario={type_counts['scenario']}"
    )

    if issues:
        print(f"Issues found: {len(issues)}")
        for issue in issues:
            print(f"- {issue}")
    else:
        print("Issues found: 0")


def cmd_answer(items_path: Path, item_id: int) -> None:
    items = load_items(items_path)
    item_index = find_item_index(items, item_id)
    item = items[item_index]
    print(str(item["answer"]))


def cmd_source(items_path: Path, notes_path: Path, item_id: int) -> None:
    items = load_items(items_path)
    item_index = find_item_index(items, item_id)
    source_ref = str(items[item_index]["source_ref"]).strip()
    ranges = parse_source_ref_ranges(source_ref)

    if not notes_path.exists():
        raise SystemExit(f"Missing notes file: {notes_path}")
    lines = notes_path.read_text(encoding="utf-8").splitlines()

    for start, end in ranges:
        if end > len(lines):
            raise SystemExit(
                f"source_ref out of bounds for {notes_path}: "
                f"{start}-{end} (file has {len(lines)} lines)"
            )
        for line_no in range(start, end + 1):
            print(f"{line_no}:{lines[line_no - 1]}")


def print_help() -> None:
    print("Commands:")
    print("  q      Select next item and copy to clipboard")
    print("  y      Mark active item correct, then auto-copy next item")
    print("  n      Mark active item incorrect, then auto-copy next item")
    print("  a [ID] Print answer for item id (or active item in interactive mode)")
    print("  source [ID] Print source_ref lines from notes.md for item id")
    print("  reset  Reset all items to unseen and due now")
    print("  check  Validate items and print summary stats")
    print("  help   Show this help")
    print("  exit   Quit the application")


def run_single_command(command: str, args: list[str]) -> int:
    if command in {"question", "q"}:
        cmd_question(ITEMS_PATH)
        return 0
    if command in {"y", "n"}:
        if len(args) != 1:
            raise SystemExit(f"Usage: {command} <item_id>")
        item_id = parse_item_id(args[0])
        is_correct = command == "y"
        cmd_grade(ITEMS_PATH, item_id, is_correct)
        return 0
    if command == "reset":
        cmd_reset(ITEMS_PATH)
        return 0
    if command == "check":
        cmd_check(ITEMS_PATH)
        return 0
    if command in {"answer", "a"}:
        if len(args) != 1:
            raise SystemExit("Usage: a <item_id> (non-interactive mode)")
        item_id = parse_item_id(args[0])
        cmd_answer(ITEMS_PATH, item_id)
        return 0
    if command == "source":
        if len(args) != 1:
            raise SystemExit("Usage: source <item_id> (non-interactive mode)")
        item_id = parse_item_id(args[0])
        cmd_source(ITEMS_PATH, NOTES_PATH, item_id)
        return 0
    if command in {"help", "h", "?"}:
        print_help()
        return 0
    raise SystemExit(f"Unknown command: {command}")


def run_interactive() -> int:
    print("Quiz CLI (interactive)")
    print("Type 'help' for commands.")

    current_item_id: int | None = None
    while True:
        try:
            raw = input("> ")
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print()
            return 0

        raw = raw.strip()
        if not raw:
            continue
        try:
            parts = shlex.split(raw)
        except ValueError as exc:
            print(f"Invalid command syntax: {exc}")
            continue
        if not parts:
            continue

        command = parts[0].lower()
        args = parts[1:]

        if command in {"question", "q"}:
            try:
                current_item_id = cmd_question(ITEMS_PATH)
            except SystemExit as exc:
                print(exc)
        elif command in {"y", "n"}:
            is_correct = command == "y"
            try:
                current_item_id = cmd_grade(
                    ITEMS_PATH,
                    current_item_id,
                    is_correct
                )
            except SystemExit as exc:
                print(exc)
        elif command == "reset":
            try:
                cmd_reset(ITEMS_PATH)
                current_item_id = None
            except SystemExit as exc:
                print(exc)
        elif command == "check":
            try:
                cmd_check(ITEMS_PATH)
            except SystemExit as exc:
                print(exc)
        elif command in {"answer", "a"}:
            if len(args) > 1:
                print("Usage: a [item_id]")
                continue
            try:
                if len(args) == 0:
                    if current_item_id is None:
                        print("No active item. Run 'q' first or use: a <item_id>")
                        continue
                    item_id = current_item_id
                else:
                    item_id = parse_item_id(args[0])
                cmd_answer(ITEMS_PATH, item_id)
            except SystemExit as exc:
                print(exc)
        elif command == "source":
            if len(args) > 1:
                print("Usage: source [item_id]")
                continue
            try:
                if len(args) == 0:
                    if current_item_id is None:
                        print(
                            "No active item. Run 'q' first or use: source <item_id>"
                        )
                        continue
                    item_id = current_item_id
                else:
                    item_id = parse_item_id(args[0])
                cmd_source(ITEMS_PATH, NOTES_PATH, item_id)
            except SystemExit as exc:
                print(exc)
        elif command in {"help", "h", "?"}:
            print_help()
        elif command in {"exit", "quit"}:
            return 0
        else:
            print(f"Unknown command: {command}")
            print("Type 'help' for available commands.")


def main() -> int:
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        args = sys.argv[2:]
        try:
            return run_single_command(command, args)
        except SystemExit as exc:
            print(exc)
            return 1

    return run_interactive()


if __name__ == "__main__":
    raise SystemExit(main())
