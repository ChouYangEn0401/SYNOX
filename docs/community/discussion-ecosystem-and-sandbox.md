<!--
給維護者（貼到 GitHub 之前刪掉這一段）：
- 這是 GitHub Discussions 的貼文草稿。建議分類：💡 Ideas（對應 .github/DISCUSSION_TEMPLATE/ideas.yml），標題用下面的「標題」。
- 先到 repo 的 Settings → General → Features 打開 Discussions。
- 下面的連結指向 dev 分支；這份與 docs/sandbox-roadmap.md 合進 dev 並推上 GitHub 之後才點得開。
- 不要在貼文裡點名任何人（@帳號）；要感謝的專案用名字與連結就好。
-->

# 標題：SYNOX 的生態相容與沙盒計畫：想聽聽大家的意見 / Ecosystem compatibility & sandboxing in SYNOX — we'd love your input

## 繁體中文

大家好！👋

**SYNOX** 是一個住在你自己電腦裡的 AI 助理：在 Telegram、Discord 或本機網頁跟它講話，它幫你記帳、記事、提醒，
功能用一個個「工具」（pack）加上去。我們的目標族群是**不開終端機的一般使用者**，所以特別在意兩件事：容易安裝，以及裝了別人的工具也不會出事。

我們正在規劃兩件事，設計文件都公開了，想先聽聽大家的意見再動手：

1. **匯入其他生態的技能，用我們自己的檢查**
   很多很棒的技能是為 [OpenClaw](https://github.com/openclaw/openclaw)、[Hermes Agent](https://github.com/NousResearch/hermes-agent)
   等專案寫的，而且它們都採用同一份公開的 [Agent Skills](https://agentskills.io) 格式（`SKILL.md`）。我們想做一個**匯入器**：
   把這個格式的技能、以及 MCP 伺服器的設定，轉成 SYNOX 的 pack，再走 SYNOX 原本的安裝檢查（給人看報告、按確認、鎖住檔案）。
   我們**不打算**重新實作別的專案的核心，也不會用它們的名字當套件名；做法是靠公開標準（Agent Skills＋MCP）來相容。
2. **沙盒**
   讓每個工具只碰得到自己的資料夾、只連得到它申請的網站。老實說：現在只有 Linux 伺服器版有隔離後端，而且還沒在真機驗證；
   **Windows 目前沒有隔離**。Windows 有幾條候選的路（MXC、AppContainer、專用帳號＋防火牆過濾…），各有取捨，我們需要真機的資料才能決定。

**先說清楚：這是相容，不是比較。** OpenClaw 與 Hermes Agent 的團隊與社群做了非常多開創性的工作，
而且把技能格式、威脅模型與安全文件都公開寫得很清楚——我們的研究有一大半是讀他們的文件學來的（例如 Hermes 的「信任等級 × 掃描結果」表、
OpenClaw 對第三方技能的提醒）。兩個專案的信任模型是針對它們自己的使用情境設計的；SYNOX 的使用情境不同，所以要在匯入這一端多做一些檢查，
這不代表誰比較安全。如果我們的文件有任何地方寫錯、過時、或語氣不妥，請直接告訴我們，我們會改。

### 想請教大家的問題

1. **你最想在 SYNOX 裡用哪些現有的技能或 MCP 伺服器？** 這會決定匯入器先支援什麼。
2. **只有文字的技能**（沒有附程式）要怎麼呈現給一般使用者看？我們打算在安裝前把「AI 會讀到的全文」給人看，你覺得這樣夠嗎？
3. **附程式的技能**，我們打算只在工具作者或工具庫維護者那一端轉換（人補上每個指令的危險程度），不在使用者電腦上自動轉。你覺得合理嗎？
4. **Windows 沙盒**：你有沒有用過 AppContainer、MXC、或「專用帳號＋防火牆過濾」？踩過什麼坑？
   「第一次按一次系統管理員同意」對一般使用者可以接受嗎？
5. **願意在你的 Windows 上跑我們的唯讀探測腳本嗎？** 特別想要 Windows 10 Home、Windows 11 Home、Windows 11 Pro 的結果。
   步驟與要回報什麼寫在沙盒路線圖裡。
6. 你是 OpenClaw、Hermes Agent 或其他 Agent Skills 生態的作者或維護者嗎？**有什麼我們應該知道的慣例**（例如 `metadata` 的欄位、授權標示、署名方式），
   讓匯入的技能對原作者更友善？

### 文件

- 沙盒路線圖（現況、Windows 的候選路線、探測腳本、徵求協助的任務與驗收條件）：[docs/sandbox-roadmap.md](https://github.com/ChouYangEn0401/SYNOX/blob/dev/docs/sandbox-roadmap.md)
- 設計提案 ADR 0022（還沒核准）：[docs/adr/0022-ecosystem-bridge-and-sandbox.md](https://github.com/ChouYangEn0401/SYNOX/blob/dev/docs/adr/0022-ecosystem-bridge-and-sandbox.md)
- 研究（每一條都附來源）：[docs/lab/2026-11-13-ecosystem-security-research.md](https://github.com/ChouYangEn0401/SYNOX/blob/dev/docs/lab/2026-11-13-ecosystem-security-research.md)
- 實作計畫：[docs/lab/2026-11-13-ecosystem-implementation-plan.md](https://github.com/ChouYangEn0401/SYNOX/blob/dev/docs/lab/2026-11-13-ecosystem-implementation-plan.md)
- 怎麼貢獻：[CONTRIBUTING.md](https://github.com/ChouYangEn0401/SYNOX/blob/dev/CONTRIBUTING.md)

⚠️ **發現安全漏洞請不要貼在這裡**，照 [SECURITY.md](https://github.com/ChouYangEn0401/SYNOX/blob/dev/SECURITY.md) 私下寄信給我們。
探測腳本的結果（某個 Windows 機制不照文件運作）不算 SYNOX 的漏洞，可以直接貼在這串。

謝謝你花時間看！🙏

---

## English

Hi everyone! 👋

**SYNOX** is an AI assistant that lives on your own computer: you talk to it over Telegram, Discord, or a local web page,
and it keeps notes, tracks spending and sends reminders. Features come as small add-on tools ("packs").
We build for **people who never open a terminal**, so two things matter a lot to us: easy installation, and staying safe
when you install tools written by someone else.

We are planning two things. The design documents are public, and we'd like your input before we write any code:

1. **Importing skills from other ecosystems, with our own checks.**
   Many great skills were written for projects such as [OpenClaw](https://github.com/openclaw/openclaw) and
   [Hermes Agent](https://github.com/NousResearch/hermes-agent), and they share the open [Agent Skills](https://agentskills.io)
   format (`SKILL.md`). We want to build an **importer** that turns skills in this format, plus MCP server configs, into
   SYNOX packs. Those packs then go through SYNOX's usual install checks: a report for a person to read, a confirmation,
   and locked files. We do **not** plan to reimplement other projects' cores or to use their names as package names.
   Compatibility comes from the open standards (Agent Skills + MCP).
2. **Sandboxing.**
   The goal is that each tool can only touch its own folder and reach the hosts it declared. To be honest about where we
   are: today only the Linux server edition has isolation backends, and they haven't been verified on real hardware yet.
   **Windows has no isolation yet.** There are several candidate approaches (MXC, AppContainer, a dedicated account plus
   firewall filtering, and others). Each has trade-offs, and we need data from real machines to choose.

**To be clear, this is about compatibility, not comparison.** The OpenClaw and Hermes Agent teams and communities have done
a lot of pioneering work, and they document their skill formats, threat models and security guidance openly and clearly.
Much of our research comes from reading their docs. Two examples: Hermes's "trust level × scan verdict" table and
OpenClaw's guidance on third-party skills. Each project's trust model fits its own use case. SYNOX's use case is different,
so we add more checks on the import side. That doesn't make anyone "safer" than anyone else. If you spot anything in our
docs that is wrong, out of date, or unfair in tone, please tell us and we'll fix it.

### Questions we'd love your input on

1. **Which existing skills or MCP servers would you most like to use in SYNOX?** Your answers decide what the importer supports first.
2. **Text-only skills** (no code): how should we present them to non-technical users? We plan to show "everything the AI
   will read" before installation. Is that enough?
3. **Skills that ship code**: we plan to convert them only on the tool author's or library maintainer's side, where a person
   fills in each command's risk level. We don't plan to auto-convert them on the user's machine. Does that sound reasonable?
4. **Windows sandboxing**: have you used AppContainer, MXC, or a "dedicated account + WFP filtering" setup? What went
   wrong? Would a one-time administrator (UAC) prompt be acceptable for non-technical users?
5. **Would you run our read-only probe scripts on your Windows PC?** Results from Windows 10 Home, Windows 11 Home and
   Windows 11 Pro would help most. The sandbox roadmap explains the steps and what to share.
6. Do you author or maintain skills for OpenClaw, Hermes Agent or another Agent Skills ecosystem? **Are there conventions we
   should know about**, such as `metadata` fields, license notices or attribution, so that imported skills treat their
   original authors well?

### Documents

- Sandbox roadmap (current state, Windows options, probe scripts, help-wanted tasks with acceptance criteria): [docs/sandbox-roadmap.md](https://github.com/ChouYangEn0401/SYNOX/blob/dev/docs/sandbox-roadmap.md)
- Design proposal ADR 0022 (not yet approved): [docs/adr/0022-ecosystem-bridge-and-sandbox.md](https://github.com/ChouYangEn0401/SYNOX/blob/dev/docs/adr/0022-ecosystem-bridge-and-sandbox.md)
- Research (every claim has a source): [docs/lab/2026-11-13-ecosystem-security-research.md](https://github.com/ChouYangEn0401/SYNOX/blob/dev/docs/lab/2026-11-13-ecosystem-security-research.md)
- Implementation plan: [docs/lab/2026-11-13-ecosystem-implementation-plan.md](https://github.com/ChouYangEn0401/SYNOX/blob/dev/docs/lab/2026-11-13-ecosystem-implementation-plan.md)
- How to contribute: [CONTRIBUTING.md](https://github.com/ChouYangEn0401/SYNOX/blob/dev/CONTRIBUTING.md)

⚠️ **Please don't post security vulnerabilities here.** Report them privately as described in
[SECURITY.md](https://github.com/ChouYangEn0401/SYNOX/blob/dev/SECURITY.md). Probe results are fine to post in this thread:
if a Windows mechanism doesn't behave as documented, that isn't a SYNOX vulnerability.

Thanks for reading! 🙏
