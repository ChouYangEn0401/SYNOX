# 文件盤點：哪些已公開、哪些還沒

盤點日期：2026-11-14。**「公開」＝這個檔案的這個版本，已經存在於 GitHub（`origin`）上任何一條分支**；SYNOX 的 GitHub 是公開的，所以等於全世界看得到。
補充：`feat/secure-apps`（到 cc65d41 為止）已合進本機 dev，但**還沒 push**，所以它帶來的文件在下面仍算「未公開」，要等 push 才公開；那 7 張 handoff 票不在這次合併內。
範圍：`docs/**` 與根目錄的 `*.md`，涵蓋所有本機分支與遠端分支。

| 分類 | 份數 |
|---|---|
| 未公開（只在本機分支） | 57 |
| 已公開，但本機另有未公開的新版 | 21 |
| 已公開 | 105 |

- 「含擁有者原話」＝檔內有「擁有者原話」字樣。這類檔案合進 dev／main（會被推上公開 GitHub）前要先過目；原版另存一份在私有備份庫（見下）。7 張 handoff 票（`docs/handoffs/20261114-051342-*`）已決定不進 dev／main。
- 備份位置：`SYNOX_Plans\from-synox-unpublished-20261114\<原路徑>`（私有庫，不推送）。未公開與「有未公開新版」的檔案全部備份。
- 已公開的檔案裡有 11 份含「擁有者原話」字樣（見第 3 節的標記）：它們早已在 GitHub 上，之後要不要處理由擁有者決定。

## 1. 未公開（57 份）

| 文件 | 在哪 | 含擁有者原話 | 備份 |
|---|---|---|---|
| `docs/adr/0023-tool-apps-services.md` | 只在本機：feat/tool-apps | 是 | Plans 已備份 |
| `docs/adr/0024-tool-apps-services.md` | 只在本機：feat/secure-apps | 是 | Plans 已備份 |
| `docs/adr/0025-guard-core-and-stepup.md` | 只在本機：feat/remote-access、feat/secure-apps |  | Plans 已備份 |
| `docs/adr/0026-remote-tool-apps.md` | 只在本機：feat/remote-access、feat/secure-apps |  | Plans 已備份 |
| `docs/apps-api.md` | 只在本機：feat/secure-apps |  | Plans 已備份 |
| `docs/handoffs/20261114-051342-console-cookie-local-gap.md` | 只在本機：feat/secure-apps | 是 | Plans 已備份 |
| `docs/handoffs/20261114-051342-encrypted-export.md` | 只在本機：feat/secure-apps | 是 | Plans 已備份 |
| `docs/handoffs/20261114-051342-g1-remote-real-test.md` | 只在本機：feat/secure-apps | 是 | Plans 已備份 |
| `docs/handoffs/20261114-051342-merge-secure-apps.md` | 只在本機：feat/secure-apps | 是 | Plans 已備份 |
| `docs/handoffs/20261114-051342-remote-enable-flow.md` | 只在本機：feat/secure-apps | 是 | Plans 已備份 |
| `docs/handoffs/20261114-051342-shared-unlock.md` | 只在本機：feat/secure-apps | 是 | Plans 已備份 |
| `docs/handoffs/20261114-051342-stepup-when-vault-locked.md` | 只在本機：feat/secure-apps | 是 | Plans 已備份 |
| `docs/lab/2026-11-14-stepup-remote-plan.md` | 只在本機：feat/remote-access、feat/secure-apps |  | Plans 已備份 |
| `docs/lab/2026-11-14-tool-apps-implementation-plan.md` | 只在本機：feat/secure-apps、feat/tool-apps | 是 | Plans 已備份 |
| `docs/overview/archive/synox-plan-book-v2.html` | 只在本機：local-only/dev-with-docs | 是 | Plans 已備份 |
| `docs/overview/master-plan-src/core-summary.html` | 只在本機：local-only/dev-with-docs |  | Plans 已備份 |
| `docs/overview/master-plan-src/home-guide.html` | 只在本機：local-only/dev-with-docs |  | Plans 已備份 |
| `docs/overview/master-plan-src/home-now.html` | 只在本機：local-only/dev-with-docs |  | Plans 已備份 |
| `docs/overview/master-plan-src/packages.json` | 只在本機：local-only/dev-with-docs |  | Plans 已備份 |
| `docs/overview/master-plan-src/phase-dedupe.html` | 只在本機：local-only/dev-with-docs |  | Plans 已備份 |
| `docs/overview/master-plan-src/phase-deps.html` | 只在本機：local-only/dev-with-docs |  | Plans 已備份 |
| `docs/overview/master-plan-src/phase-packages.html` | 只在本機：local-only/dev-with-docs |  | Plans 已備份 |
| `docs/overview/master-plan-src/phase-plan.html` | 只在本機：local-only/dev-with-docs |  | Plans 已備份 |
| `docs/overview/master-plan-src/phase-timeline.html` | 只在本機：local-only/dev-with-docs |  | Plans 已備份 |
| `docs/overview/master-plan-src/questions.json` | 只在本機：local-only/dev-with-docs |  | Plans 已備份 |
| `docs/overview/master-plan-src/rules-index.html` | 只在本機：local-only/dev-with-docs |  | Plans 已備份 |
| `docs/overview/master-plan-src/rules-work.html` | 只在本機：local-only/dev-with-docs |  | Plans 已備份 |
| `docs/overview/master-plan-src/todo-actions.html` | 只在本機：local-only/dev-with-docs |  | Plans 已備份 |
| `docs/overview/master-plan-src/todo-gaps.html` | 只在本機：local-only/dev-with-docs |  | Plans 已備份 |
| `docs/overview/master-plan-src/todo-public-more.html` | 只在本機：local-only/dev-with-docs |  | Plans 已備份 |
| `docs/overview/master-plan-src/todo-public.html` | 只在本機：local-only/dev-with-docs |  | Plans 已備份 |
| `docs/overview/master-plan-src/todo-questions.html` | 只在本機：local-only/dev-with-docs |  | Plans 已備份 |
| `docs/overview/master-plan-src/todo-risks.html` | 只在本機：local-only/dev-with-docs |  | Plans 已備份 |
| `docs/overview/master-plan-src/todo-unverified.html` | 只在本機：local-only/dev-with-docs |  | Plans 已備份 |
| `docs/overview/master-plan-src/xref-health-ai.html` | 只在本機：local-only/dev-with-docs |  | Plans 已備份 |
| `docs/overview/master-plan-src/xref-health-core.html` | 只在本機：local-only/dev-with-docs |  | Plans 已備份 |
| `docs/overview/synox-automation-research.html` | 只在本機：local-only/dev-with-docs | 是 | Plans 已備份 |
| `docs/overview/synox-automation-research.md` | 只在本機：local-only/dev-with-docs | 是 | Plans 已備份 |
| `docs/overview/synox-conversation-research.html` | 只在本機：local-only/dev-with-docs |  | Plans 已備份 |
| `docs/overview/synox-conversation-research.md` | 只在本機：local-only/dev-with-docs |  | Plans 已備份 |
| `docs/overview/synox-ecosystem-research.html` | 只在本機：local-only/dev-with-docs |  | Plans 已備份 |
| `docs/overview/synox-ecosystem-research.md` | 只在本機：local-only/dev-with-docs | 是 | Plans 已備份 |
| `docs/overview/synox-fleet-research.md` | 只在本機：local-only/dev-with-docs | 是 | Plans 已備份 |
| `docs/overview/synox-harness-research.html` | 只在本機：local-only/dev-with-docs | 是 | Plans 已備份 |
| `docs/overview/synox-harness-research.md` | 只在本機：local-only/dev-with-docs | 是 | Plans 已備份 |
| `docs/overview/synox-industry-research.html` | 只在本機：local-only/dev-with-docs | 是 | Plans 已備份 |
| `docs/overview/synox-industry-research.md` | 只在本機：local-only/dev-with-docs | 是 | Plans 已備份 |
| `docs/overview/synox-overview.html` | 只在本機：local-only/dev-with-docs |  | Plans 已備份 |
| `docs/overview/synox-plan-book.html` | 只在本機：local-only/dev-with-docs | 是 | Plans 已備份 |
| `docs/overview/synox-secure-channel-research.html` | 只在本機：local-only/dev-with-docs |  | Plans 已備份 |
| `docs/overview/synox-secure-channel-research.md` | 只在本機：local-only/dev-with-docs | 是 | Plans 已備份 |
| `docs/overview/synox-sentinel-iot-research.html` | 只在本機：local-only/dev-with-docs | 是 | Plans 已備份 |
| `docs/overview/synox-sentinel-iot-research.md` | 只在本機：local-only/dev-with-docs |  | Plans 已備份 |
| `docs/overview/synox-tool-health-research.html` | 只在本機：local-only/dev-with-docs | 是 | Plans 已備份 |
| `docs/overview/synox-tool-health-research.md` | 只在本機：local-only/dev-with-docs | 是 | Plans 已備份 |
| `docs/security/web-threats.md` | 只在本機：feat/remote-access、feat/secure-apps |  | Plans 已備份 |
| `docs/tool-apps.md` | 只在本機：feat/secure-apps |  | Plans 已備份 |

## 2. 已公開，但本機另有未公開的新版（21 份）

| 文件 | 在哪 | 含擁有者原話 | 備份 |
|---|---|---|---|
| `CHANGELOG.md` | main+dev；新版在本機：feat/remote-access、feat/secure-apps、local-only/dev-with-docs、research/safe-third-party-tools、research/tg-claw-bot-cc-open |  | Plans 已備份 |
| `QuestionToUser.md` | main；新版在本機：local-only/dev-with-docs | 是 | Plans 已備份 |
| `README.md` | main+dev；新版在本機：feat/remote-access、feat/secure-apps、local-only/dev-with-docs |  | Plans 已備份 |
| `docs/AGENT.md` | main+dev；新版在本機：feat/remote-access、feat/secure-apps、local-only/dev-with-docs |  | Plans 已備份 |
| `docs/README.md` | main+dev；新版在本機：feat/remote-access、feat/secure-apps、feat/tool-apps、local-only/dev-with-docs |  | Plans 已備份 |
| `docs/adr/0003-distribution-git-clone-and-installer.md` | main+dev；新版在本機：feat/remote-access、feat/secure-apps | 是 | Plans 已備份 |
| `docs/artifacts.json` | dev；新版在本機：feat/remote-access、feat/secure-apps |  | Plans 已備份 |
| `docs/handoff/clean-machine-test.md` | main+dev；新版在本機：feat/remote-access、feat/secure-apps |  | Plans 已備份 |
| `docs/install-packs.md` | main+dev；新版在本機：research/safe-third-party-tools、research/tg-claw-bot-cc-open |  | Plans 已備份 |
| `docs/installer/spec.html` | main+dev；新版在本機：feat/remote-access、feat/secure-apps |  | Plans 已備份 |
| `docs/lab/README.md` | main+dev；新版在本機：feat/secure-apps、feat/tool-apps |  | Plans 已備份 |
| `docs/lab/issues-to-open.md` | main+dev；新版在本機：feat/secure-apps |  | Plans 已備份 |
| `docs/landing/index.html` | main+dev；新版在本機：research/safe-third-party-tools、research/tg-claw-bot-cc-open |  | Plans 已備份 |
| `docs/landing/page.html` | main+dev；新版在本機：research/safe-third-party-tools、research/tg-claw-bot-cc-open |  | Plans 已備份 |
| `docs/pack-format.md` | main+dev；新版在本機：feat/secure-apps |  | Plans 已備份 |
| `docs/release-build.md` | dev；新版在本機：feat/remote-access、feat/secure-apps |  | Plans 已備份 |
| `docs/runtime-api.md` | main+dev；新版在本機：local-only/dev-with-docs |  | Plans 已備份 |
| `docs/sdk.md` | main+dev；新版在本機：feat/secure-apps |  | Plans 已備份 |
| `docs/security.md` | main+dev；新版在本機：feat/secure-apps |  | Plans 已備份 |
| `docs/tools.md` | main+dev；新版在本機：feat/secure-apps |  | Plans 已備份 |
| `docs/ui/preview.html` | main+dev；新版在本機：feat/secure-apps、local-only/dev-with-docs、research/safe-third-party-tools、research/tg-claw-bot-cc-open |  | Plans 已備份 |

## 3. 已公開（105 份）

| 文件 | 在哪 | 含擁有者原話 |
|---|---|---|
| `CONTRIBUTING.md` | main+dev |  |
| `GOVERNANCE.md` | main+dev |  |
| `LICENSING.md` | main+dev |  |
| `MAINTAINERS.md` | main+dev |  |
| `SECURITY.md` | main+dev |  |
| `TRADEMARK.md` | main+dev |  |
| `docs/QuestionToUser.md` | dev | 是 |
| `docs/adr/0001-runtime-loop-heartbeat-mother-session.md` | main+dev | 是 |
| `docs/adr/0002-soul-md-in-chat-assistant-prompt.md` | main+dev | 是 |
| `docs/adr/0004-activator-event-driven-rules.md` | main+dev |  |
| `docs/adr/0005-soul-ledger-memory-provenance-review.md` | main+dev |  |
| `docs/adr/0006-keep-awake-screen-may-sleep.md` | main+dev | 是 |
| `docs/adr/0007-local-llm-platform.md` | main+dev |  |
| `docs/adr/0008-completion-guard.md` | main+dev |  |
| `docs/adr/0009-leaked-tool-call-recovery.md` | main+dev |  |
| `docs/adr/0010-stop-words.md` | main+dev |  |
| `docs/adr/0011-cannot-do-exit.md` | main+dev |  |
| `docs/adr/0012-repeat-failure-and-step-limit-summary.md` | main+dev |  |
| `docs/adr/0013-tool-scenario-descriptions.md` | main+dev |  |
| `docs/adr/0014-per-turn-tool-cap.md` | main+dev |  |
| `docs/adr/0015-context-budget.md` | main+dev |  |
| `docs/adr/0016-tool-result-cap.md` | main+dev |  |
| `docs/adr/0017-tail-rules-and-time-last.md` | main+dev |  |
| `docs/adr/0018-goal-recitation.md` | main+dev |  |
| `docs/adr/0019-qwen3-no-think-sampling.md` | main+dev |  |
| `docs/adr/0020-eval-missing-tool-param-and-metrics.md` | main+dev |  |
| `docs/adr/0021-vlm-vision.md` | main+dev |  |
| `docs/adr/0022-ecosystem-bridge-and-sandbox.md` | main+dev |  |
| `docs/adr/0023-updates-and-hotfixes.md` | dev |  |
| `docs/advanced-install.md` | dev |  |
| `docs/artifacts/2026-11-09-synox-generalization-audit.html` | dev |  |
| `docs/artifacts/2026-11-10-synox-deploy-test-board.html` | dev |  |
| `docs/artifacts/2026-11-12-activator-handoff.html` | dev |  |
| `docs/artifacts/2026-11-12-handoff-report.html` | dev |  |
| `docs/artifacts/2026-11-12-local-model-integration.html` | dev |  |
| `docs/artifacts/2026-11-12-synox-link-handoff.html` | dev |  |
| `docs/artifacts/2026-11-12-synox-link-research.html` | dev |  |
| `docs/artifacts/2026-11-12-synox-memory-identity.html` | dev |  |
| `docs/artifacts/2026-11-12-synox-overview.html` | dev |  |
| `docs/artifacts/2026-11-12-synox-plan.html` | dev | 是 |
| `docs/artifacts/2026-11-13-cc-open-investigation.html` | dev |  |
| `docs/artifacts/2026-11-13-cloud-task-briefs.html` | dev |  |
| `docs/artifacts/2026-11-13-synox-ecosystem-survey.html` | dev |  |
| `docs/artifacts/2026-11-13-synox-third-party-tool-security.html` | dev |  |
| `docs/artifacts/README.md` | dev |  |
| `docs/artifacts/registry-archive.json` | dev |  |
| `docs/claude-code-cli.md` | main+dev |  |
| `docs/debug-notes.md` | main+dev |  |
| `docs/discord-concepts.md` | main+dev |  |
| `docs/discord.md` | main+dev |  |
| `docs/discussions/2026-11-10-isolation-howto.md` | main |  |
| `docs/discussions/2026-11-10-sandbox-and-skill-containers.md` | main |  |
| `docs/discussions/2026-11-12-link-architecture.html` | 其他遠端分支 |  |
| `docs/discussions/2026-11-12-link-implementation.html` | 其他遠端分支 |  |
| `docs/docker.md` | main+dev |  |
| `docs/ecosystem.md` | main+dev |  |
| `docs/guide/index.html` | dev |  |
| `docs/handoff/README.md` | main+dev |  |
| `docs/handoff/container-verification.md` | main+dev |  |
| `docs/handoff/discord-handoff.md` | main+dev |  |
| `docs/handoff/real-service-testing.md` | main+dev |  |
| `docs/handoffs/2026-11-12-isdtelekit-poller-lanes-and-429.md` | main | 是 |
| `docs/handoffs/2026-11-12-moneybook-synox-pack-0.18.md` | main | 是 |
| `docs/keep-awake-troubleshooting.md` | main+dev |  |
| `docs/lab/2026-11-13-ecosystem-implementation-plan.md` | main+dev |  |
| `docs/lab/2026-11-13-ecosystem-security-research.md` | main+dev |  |
| `docs/lab/2026-11-13-local-llm-ollama-test-record.md` | main+dev |  |
| `docs/lab/2026-11-13-onboarding-help-aliases-plan.md` | dev | 是 |
| `docs/lab/2026-11-13-subscription-login-research.md` | main+dev |  |
| `docs/lab/2026-11-13-vlm-vision-design.md` | main+dev |  |
| `docs/lab/HANDOFF-2026-11-13-round2.md` | main+dev |  |
| `docs/lab/HANDOFF-2026-11-13.md` | main+dev |  |
| `docs/lab/cross-repo/2026-11-12-isdtelekit-poller-lanes-and-429.md` | dev | 是 |
| `docs/lab/cross-repo/2026-11-12-moneybook-synox-pack-0.18.md` | dev | 是 |
| `docs/lab/design/2026-11-13-brand-explorations-share.html` | dev |  |
| `docs/lab/design/2026-11-13-brand-explorations.html` | main+dev |  |
| `docs/lab/discussions/2026-11-10-isolation-howto.md` | dev |  |
| `docs/lab/discussions/2026-11-10-sandbox-and-skill-containers.md` | dev |  |
| `docs/lab/research/2026-11-13-cn-harness-techniques.html` | main+dev |  |
| `docs/lab/research/2026-11-13-cn-harness-techniques.md` | main+dev |  |
| `docs/lab/slogan/index.html` | dev |  |
| `docs/lab/tools/local-llm-live/results/27b-native.json` | main+dev |  |
| `docs/lab/tools/local-llm-live/results/27b-text.json` | main+dev |  |
| `docs/lab/tools/local-llm-live/results/9b-native.json` | main+dev |  |
| `docs/lab/tools/local-llm-live/results/9b-text.json` | main+dev |  |
| `docs/lab/tools/windows-sandbox-probe/README.md` | main+dev |  |
| `docs/legacy/builtin-packs.md` | dev |  |
| `docs/legacy/connectors.md` | dev |  |
| `docs/link.md` | 其他遠端分支 |  |
| `docs/presentation.md` | main+dev |  |
| `docs/tool-health.md` | main+dev |  |
| `docs/tutorials-engine.md` | dev |  |
| `docs/tutorials/README.md` | main+dev |  |
| `docs/tutorials/discord/README.md` | main+dev |  |
| `docs/tutorials/discord/index.html` | main+dev |  |
| `docs/tutorials/telegram/README.md` | main+dev |  |
| `docs/tutorials/telegram/index.html` | main+dev |  |
| `docs/ui/cli-welcome.txt` | main+dev |  |
| `docs/ui/motion-notes.md` | main+dev | 是 |
| `docs/ui/preview-error.html` | main+dev |  |
| `docs/ui/preview-login.html` | main+dev |  |
| `docs/ui/preview-phone-dark.html` | main+dev |  |
| `docs/ui/preview-phone.html` | main+dev |  |
| `docs/ui/redesign-notes.md` | main+dev |  |
| `docs/versioning.md` | dev |  |
