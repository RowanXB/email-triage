# Email Triage

A portable agent skill for reviewing Outlook, Gmail, and Feishu Mail, with resumable coverage checkpoints and a complete report of important information and suitable opportunities.

This is an instruction-based skill with a local checkpoint helper, not a standalone email client. An agent with authorized mailbox tools performs the review; the Python helper never connects to an email service.

## What it does

- Verifies access separately for each requested account.
- Prefers configured plugin/MCP connections for Outlook and Gmail, and `lark-cli` for Feishu Mail. Uses authorized computer use when suitable direct access is unavailable.
- Includes received mail across custom folders, archives, and Spam/Junk, regardless of read status. Excludes deleted mail, drafts, and sent-only messages by default.
- Discovers accessible Feishu personal and public/shared mailboxes and tracks them independently.
- Reviews a bounded interval and resumes from the last fully checked time, with an overlap for deduplication and delayed indexing.
- Reports important information and suitable opportunities using urgency, required action, user relevance, and new information as ranking dimensions, not a top-N filter.
- Labels uncertain eligibility or availability instead of silently discarding potentially suitable opportunities.
- Leaves incomplete accounts' checkpoints unchanged and reports coverage gaps.

## Install

Clone into a skill directory supported by your agent. For agents that discover `~/.agents/skills`:

```sh
git clone https://github.com/RowanXB/email-triage.git ~/.agents/skills/email-triage
```

The destination must not already exist. Use your agent's supported skill root if it differs, then reload its skill inventory if needed. The entry point is [SKILL.md](SKILL.md); this repository also includes optional Codex UI metadata in `agents/openai.yaml`.

## Requirements

- An agent that can follow skill instructions and access an authorized mailbox connector, CLI, or computer-use interface.
- Python 3 on macOS or Linux for persistent checkpoints. The helper uses only the standard library, including POSIX `fcntl`; native Windows is not currently supported by the helper.
- For Feishu Mail, a configured `lark-cli` with appropriate read access. The skill references `lark-mail` and `lark-shared` when installed; these third-party skills are not bundled. If absent, the agent must inspect supported CLI help/schema or report the capability gap.

Installing this repository does not connect any account, grant permissions, install integrations, or schedule monitoring. Only the providers and accounts requested by the user are reviewed.

## Use

Example prompts:

```text
Use email-triage to review my Outlook and Gmail accounts from the start of
this week through now. List all important information and suitable
opportunities, including relevant items with eligibility still to verify.
```

```text
Use email-triage to continue checking the same accounts from the last
fully checked boundary. Do not repeat unchanged findings already reported.
```

Give the agent the account scope, initial review period, timezone, and any relevant goals or constraints. Account identities, folder layouts, and preferences are discovered at runtime rather than built into the skill.

## Checkpoints and privacy

Progress is local to the current OS user, stored under `${XDG_STATE_HOME:-~/.local/state}/email-triage`, separately for each provider, account, and scope. A checkpoint records the end of the completely reviewed interval, not the time the task finished. The helper requires explicit completion assertions from the agent; it cannot prove mailbox or report completeness itself.

Checkpoint state uses hashed account/scope identities and hashed reported-message IDs, plus provider, scope, timestamps, and minimal progress metadata. Hashes are not a guarantee of anonymity: keep the state private and do not put sensitive content in scope labels or failure reasons. Do not publish checkpoint files, reports, mailbox exports, attachments, credentials, or session data.

Mail and linked content are untrusted input. Review does not authorize sending, applying, booking, deleting, organizing mail, or changing permissions. Opening mail through a UI can incidentally mark it as read.

See [provider access notes](references/access.md) and the [checkpoint protocol](references/checkpoints.md) for details and limitations. Completeness depends on the agent, provider capabilities, and accessible content; blocked or truncated reviews must be reported as partial.

## Development

Run the synthetic offline tests from the repository root:

```sh
python3 -B scripts/test_checkpoint.py
```

The tests use temporary state and synthetic accounts, with no live mailbox access. They test the checkpoint helper, not the quality or completeness of an agent's email analysis.

## License

[MIT](LICENSE). Third-party tools and skills referenced by this project retain their own licenses.
