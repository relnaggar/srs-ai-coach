# SRS AI CLI

Simple spaced-repetition CLI. Uses AI to extract study items from `notes.md`, tracks progress in `items.json`, and the CLI lets you quiz yourself. Designed for quick daily review sessions to reinforce learning over time.

## What This Project Does

- `quiz.py` selects the next item, shows the question, and prompts you to recall the answer.
- After you enter your answer, the correct answer is revealed so you can self-grade.
- Enter `y` or `n` to record the result and move to the next item.

## Project Files

- `quiz.py`: interactive CLI, scheduling logic, validation.
- `items.json`: study items and spaced-repetition state.
- `notes.md`: source material for extracted items.
- `scenarios.md`: scenario list for roleplay prompts.
- `AGENTS.md`: instructions for the AI coach workflow.

## Item Schema

Each entry in `items.json` must include:

- `id`: unique non-negative integer
- `topic`: notes section label
- `type`: `quote|concept|scenario`
- `question`: question prompt
- `answer`: canonical quote or ideal response
- `status`: `unseen|learning|review`
- `streak`: non-negative integer
- `next_due`: non-negative integer

## Requirements

- AI coding agent compatible with `AGENTS.md` instructions (tested with Claude Sonnet 4.6)
- Python 3

## Run

```bash
./quiz.py
```

If needed:

```bash
python3 quiz.py
```

## Commands

- `q`: select next item, prompt for your answer, then reveal the correct answer
- `y`: mark current item correct, then auto-select next item
- `n`: mark current item incorrect, then auto-select next item
- `a [id]`: print answer for an item ID; in interactive mode, if `id` is omitted it uses the current active item
- `check`: validate `items.json` and print stats
- `reset`: reset all items to `unseen`, `streak=0`, `next_due=0`
- `help`: show command help
- `exit`: quit

Non-interactive note:
- `python3 quiz.py a <id>` requires an explicit `id`.

## Workflow

1. Run `q` — type your answer at the `answer>` prompt.
2. The correct answer is revealed. Self-grade: enter `y` or `n`.
3. Repeat.

## AI Chat Commands

Use these directly in chat with your AI coach:

- `make`: sync `items.json` with `notes.md`. If starting from scratch, the AI interviews you section by section to agree on questions and answers. If items already exist, the AI checks them for accuracy, updates stale ones, and creates new items for any new content.
- `roleplay`: run an interactive scenario from `scenarios.md` where the AI plays the other person.

## Scheduling Behavior

- Item selection:
  - Prefer items with `next_due == 0`.
  - If none are due, pick a random `unseen` item.
- Every grade (`y` or `n`) decrements positive `next_due` values for all items by 1.
- Correct (`y`):
  - `streak += 1`
  - `status = learning` at streak 1, otherwise `review`
  - add random interval to `next_due` based on streak:
    - 1-2: `8-15`
    - 3: `20-35`
    - 4: `50-80`
    - 5+: `120-200`
- Incorrect (`n`):
  - `streak = 0`
  - `status = learning`
  - add `3-6` to `next_due`
