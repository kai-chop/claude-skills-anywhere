# claude-skills-anywhere

**Claude Code の skills を、他社の無料枠 CLI（Gemini CLI / Qwen Code / Codex）でもそのまま使うための機構。** Your skills are the part of your setup that took the longest to get right, and they are just Markdown — but the moment you delegate work to another vendor's CLI to stay inside a free tier, the agent on the other side has none of them. This repo mirrors one canon of skills into those CLIs and starts them so the skill bodies are actually readable.

Standard library Python, no dependencies, Linux/macOS/Windows.

## The two things that break

**1. Frontmatter that one CLI accepts and another rejects.** Codex refuses a whole `SKILL.md` when it meets a key it does not know (`Unexpected key(s) in SKILL.md frontmatter`), so a Claude skill carrying an extra key silently stops existing on that side. Gemini CLI and Qwen Code take the same file as-is.

**2. The destination directory is outside the workspace.** This one costs an afternoon. Link a skill into `~/.gemini/skills` and `gemini skills list` reports it as `[Enabled]` — the router sees it, the model tries to activate it, and reading the body fails with `Path not in workspace`. Both `~/.gemini/skills` and the canon live outside the workspace, and **copying instead of linking does not help, because the copy is outside too**. The fix is to put the canon root *into* the workspace at launch, which is all the shims do.

Measured 2026-08-24 with a controlled pair: same prompt, `--include-directories` present = the model quotes the skill body and exits 0; absent = `Path not in workspace`.

## Install

```sh
git clone https://github.com/kai-chop/claude-skills-anywhere
cd claude-skills-anywhere

python mirror_skills.py --dest gemini              # link every skill in the canon
python mirror_skills.py --dest all                 # gemini + qwen + codex
python mirror_skills.py --dest all --check         # report drift, exit 1, write nothing
python mirror_skills.py --dest codex --skills code-master,task-master
```

The canon defaults to `~/.claude/skills`; override with `--canon`.

| Destination | Where it lands | How | Why |
|---|---|---|---|
| `gemini` | `~/.gemini/skills` | symlink (junction on Windows) | Accepts Claude frontmatter, so one source of truth beats a copy |
| `qwen` | `~/.qwen/skills` | symlink (junction on Windows) | Same |
| `codex` | `$CODEX_HOME/skills` (default `~/.codex/skills`) | copy with the frontmatter filtered | It rejects unknown keys, so the file has to change on the way |

Then launch through a shim so the bodies are readable:

```sh
shims/gemini-skilled.sh -p "use code-master and review this diff"
shims/qwen-skilled.sh
```

```powershell
shims\gemini-skilled.ps1 -p "use code-master and review this diff"
shims\qwen-skilled.ps1
```

To make them ordinary commands, add a function or alias to your shell profile pointing at the shim — they pass every argument straight through.

## What it will not do

**It never deletes anything it did not create.** A copied skill carries a `.mirrored-from-claude` marker and a linked one resolves into the canon; pruning only touches those two. A skill you placed in the destination by hand is reported and left alone, and a name collision with something unmarked stops the run instead of overwriting it.

**It does not make the other model behave like Claude.** Skills are instructions, not capability. Gemini's router in particular did not activate skills on its own in testing (0/2 — it selects a small fast model and does not call `activate_skill` unless told); naming the skill in the prompt works. Treat mirrored skills as available, not as automatically applied.

**It only helps agents that have a tool loop.** A CLI that can read files and run commands can use a skill. A plain HTTP chat completion cannot — there is nothing there to *do* the procedure. For those lanes, a short knowledge-shaped prompt scaffold transfers; a procedural skill does not.

## Environment overrides

| Variable | Used by | Effect |
|---|---|---|
| `SKILLS_CANON` | both shims | Skill canon to add to the workspace (default `~/.claude/skills`) |
| `GEMINI_BIN` / `QWEN_BIN` | respective shim | Binary to launch (useful for testing) |
| `CODEX_HOME` | mirror | Where the codex destination lives |
| `DASHSCOPE_API_KEY` | qwen shim | Used only when `~/.qwen/oauth_creds.json` does not exist yet; exported for that one process, then restored |
| `QWEN_BASE_URL` / `QWEN_MODEL` | qwen shim | Override the OpenAI-compatible endpoint and model |

## Tests

```sh
python test_mirror_skills.py
```

15 tests over temporary directories: frontmatter filtering (including that a nested list under a dropped key travels with it, and that a `---` line in the body does not truncate the file), copy/link idempotence, binary assets byte-for-byte, the pruning boundary, and `--check` writing nothing.

## License

MIT
