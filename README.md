# SRS AI Coach

Simple spaced-repetition CLI for interacting with an AI coach. Extracts study items from `notes.md`, tracks progress in `items.json`, and prompts you to recall information in your AI chat. Designed for quick daily review sessions.

## What This Project Does

- `quiz.py` selects and schedules items from `items.json`.
- The selected item payload is copied to your clipboard.
- You paste that payload into your AI chat coach.
- The AI asks one question, grades your answer, and you record result in the CLI (`y` or `n`).

## Project Files

- `quiz.py`: interactive CLI, scheduling logic, validation.
- `items.json`: study items and spaced-repetition state.
- `notes.md`: source material for extracted items.
- `scenarios.md`: scenario list for roleplay prompts.
- `AGENTS.md`: instructions for the AI coach workflow.

## Item Schema

Each entry in `items.json` must include:

- `id`: unique non-negative integer
- `type`: `quote|concept|scenario`
- `topic`: notes section label
- `answer`: canonical quote or ideal response
- `status`: `unseen|learning|review`
- `streak`: non-negative integer
- `next_due`: non-negative integer
- `source_ref`: line range(s) in `notes.md`

Optional:

- `question`: suggested question prompt for the AI tutor (AI still has final say on phrasing)

## Requirements

- AI coding agent compatible with `AGENTS.md` instructions (tested with gpt-5.3-codex)
- Python 3
- macOS `pbcopy` (used to copy payloads to clipboard)

## Run

```bash
./quiz.py
```

If needed:

```bash
python3 quiz.py
```

## Commands

- `q`: select next item and copy compact JSON payload to clipboard
- `y`: mark current item correct, then auto-select/copy next item
- `n`: mark current item incorrect, then auto-select/copy next item
- `a [id]`: print answer for an item ID; in interactive mode, if `id` is omitted it uses the current active item
- `source [id]`: print `source_ref` lines from `notes.md`; in interactive mode, if `id` is omitted it uses the current active item
- `check`: validate `items.json` and print stats
- `reset`: reset all items to `unseen`, `streak=0`, `next_due=0`
- `help`: show command help
- `exit`: quit

Non-interactive note:
- `python3 quiz.py a <id>` still requires an explicit `id`.
- `python3 quiz.py source <id>` requires an explicit `id`.

## AI Workflow

1. Run `q` in `quiz.py`.
2. Paste the copied JSON payload into chat.
3. AI asks one question using `question` as a suggestion plus `type` + `source_ref` context.
4. You answer in chat.
5. AI responds with one of:
   - `correct: y`
   - `incorrect quote: n`
   - `incorrect no-quote: n` + short explanation
6. Enter `y` or `n` in `quiz.py`.
7. Repeat.

See `AGENTS.md` for exact prompting, hint handling, and grading rules.

## AI Chat Commands

Use these directly in chat with your AI coach:

- `hint`: get either the first 3 words of a quote, or a blanked template.
- `make`: sync `items.json` with `notes.md`. If starting from scratch, the AI interviews you section by section to agree on questions and answers, logging the conversation in `interview.md`. If items already exist, the AI checks them for accuracy, updates stale ones, and creates new items for any new content.
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
