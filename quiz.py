#!/usr/bin/env python3
"""Quiz CLI for spaced-repetition scheduling and clipboard handoff to AI."""

import json
import random
import subprocess
from pathlib import Path
from typing import Any

ITEMS_PATH = Path("items.json")
VALID_TYPES = {"quote", "concept", "scenario"}
VALID_STATUSES = {"unseen", "learning", "review"}
REQUIRED_ITEM_KEYS = {
    "id",
    "type",
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
    if not isinstance(item_id, str) or not item_id.strip():
        issues.append(f"{location}: id must be a non-empty string")

    item_type = item.get("type")
    if item_type not in VALID_TYPES:
        issues.append(f"{location}: invalid type {item_type!r}")

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
    seen_ids: set[str] = set()
    duplicate_ids: set[str] = set()

    for idx, item in enumerate(data):
        issues.extend(collect_item_issues(item, idx))
        if not isinstance(item, dict):
            continue

        item_id = item.get("id")
        if isinstance(item_id, str) and item_id.strip():
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
    # Use compact JSON to keep clipboard payload small
    return json.dumps(item, ensure_ascii=False, separators=(",", ":"))


def find_item_index(items: list[dict[str, Any]], item_id: str) -> int:
    for index, item in enumerate(items):
        if str(item["id"]) == item_id:
            return index
    raise SystemExit(f"Current item id not found in items.json: {item_id}")


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
    due_now = [item for item in items if int(item["next_due"]) == 0]
    if due_now:
        return random.choice(due_now)

    unseen = [item for item in items if str(item["status"]) == "unseen"]
    if unseen:
        return random.choice(unseen)

    raise SystemExit(
        "No available items to ask (no due items and no unseen items)."
    )


def cmd_question(items_path: Path) -> str:
    items = load_items(items_path)
    chosen = select_next_item(items)
    item_id = str(chosen["id"])
    payload = build_payload(chosen)
    copy_to_clipboard(payload)

    print(f"payload copied to clipboard for id: {item_id}")
    print(f"type: {chosen['type']}")
    print(f"status: {chosen['status']}")
    print(f"streak: {chosen['streak']}")

    return item_id


def cmd_grade(
        items_path: Path,
        current_item_id: str | None, is_correct: bool
    ) -> str:
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


def print_help() -> None:
    print("Commands:")
    print("  q      Select next item and copy to clipboard")
    print("  y      Mark active item correct, then auto-copy next item")
    print("  n      Mark active item incorrect, then auto-copy next item")
    print("  reset  Reset all items to unseen and due now")
    print("  check  Validate items and print summary stats")
    print("  help   Show this help")
    print("  exit   Quit the application")


def main() -> int:
    print("Quiz CLI (interactive)")
    print("Type 'help' for commands.")

    current_item_id: str | None = None
    while True:
        try:
            raw = input("> ")
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print()
            return 0

        command = raw.strip().lower()
        if not command:
            continue

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
        elif command in {"help", "h", "?"}:
            print_help()
        elif command in {"exit", "quit"}:
            return 0
        else:
            print(f"Unknown command: {command}")
            print("Type 'help' for available commands.")


if __name__ == "__main__":
    raise SystemExit(main())
