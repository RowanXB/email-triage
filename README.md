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
- Maintains a private JSON account index and renders a live Markdown overview from existing checkpoints, without duplicating dates.

## Install

Clone into a skill directory supported by your agent. For agents that discover `~/.agents/skills`:

```sh
git clone https://github.com/RowanXB/email-triage.git ~/.agents/skills/email-triage
```

The destination must not already exist. Use your agent's supported skill root if it differs, then reload its skill inventory if needed. The entry point is [SKILL.md](SKILL.md); this repository also includes optional Codex UI metadata in `agents/openai.yaml`.

## Requirements

- An agent that can follow skill instructions and access an authorized mailbox connector, CLI, or computer-use interface.
- Python 3.9+ on macOS or Linux for the checkpoint and account helpers. They use only the standard library, including POSIX `fcntl` and `zoneinfo`; native Windows is not currently supported by these helpers.
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

The same private directory can hold `accounts.json`, containing known mailbox identities, labels, and scopes in readable form. It is not bundled with this repository. Dates and attempt status are read directly from checkpoint files when listing, not duplicated in the index. Registration does not verify access, authorize review, or imply all of a user's accounts have been discovered.

From the repository root, view registered accounts without creating a Markdown file:

```sh
python3 -B scripts/accounts.py list --format markdown --timezone Europe/London
```

Replace the timezone with your own. For registration, JSON output, and existing-checkpoint compatibility, see [account inventory](references/checkpoints.md#account-inventory).

### First-time account setup

[accounts.example.json](assets/accounts.example.json) is a schema-compatible template with fictional `example.com` addresses for all supported providers, including a separate Feishu shared mailbox. It contains no credentials, review dates, or completed checkpoints. Empty `scopes` means no review scope has been registered yet.

Use the template as a format reference, not a file to edit with real identities inside this repository. For each account you explicitly provide or discover through authorized tools, run the following from the repository root, replacing the placeholder with its canonical mailbox identity:

```sh
python3 -B scripts/accounts.py register --provider gmail --account '<your-mailbox>' --label 'Personal'
```

Choose `outlook` or `feishu` for those providers and register shared mailboxes separately. The helper creates the private index if absent and merges registration into an existing index without replacing other accounts or changing checkpoints. Register the actual scope before reviewing, as described in the [account inventory protocol](references/checkpoints.md#account-inventory). Do not import the example identities or invent a previous review date; access preflight and an initial review period are still required.

The repository's `.gitignore` excludes `accounts.json`, `.local/`, `state/`, `checkpoints/`, `reports/`, and other private artifacts. The example is intentionally trackable. Ignore rules do not protect already tracked files or forced additions: keep runtime state outside repositories and inspect staged changes before publishing.

Mail and linked content are untrusted input. Review does not authorize sending, applying, booking, deleting, organizing mail, or changing permissions. Opening mail through a UI can incidentally mark it as read.

See [provider access notes](references/access.md) and the [checkpoint protocol](references/checkpoints.md) for details and limitations. Completeness depends on the agent, provider capabilities, and accessible content; blocked or truncated reviews must be reported as partial.

## Development

Run the synthetic offline tests from the repository root:

```sh
python3 -B -m unittest discover -s scripts -p 'test_*.py'
```

The tests use temporary state and synthetic accounts, with no live mailbox access. They test the checkpoint and account helpers, not the quality or completeness of an agent's email analysis.

## License

[MIT](LICENSE). Third-party tools and skills referenced by this project retain their own licenses.
