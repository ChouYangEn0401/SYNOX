# 驗證機能不能為了沙盒驗證安裝 bubblewrap／podman／Docker Desktop

狀態：待處理（要擁有者決定；沒決定＝不裝，只用那台本來就有的）

## 問題一句話

驗證機上沒有 bubblewrap（Linux）或 podman／Docker Desktop 時，接手的 session 可不可以自己用套件管理員裝，好把清單第五節與 4.4、4.5 做完？

## 脈絡

- 清單第五節（L-1～L-5，Linux 的 bwrap 與 podman）、4.4／4.5（容器）、S2-c 都需要這些工具；沒有就只能寫略過，那幾項的驗收就留著。
- 這些都是作業系統套件庫或官方發佈的軟體，但安裝要管理員權限（`sudo apt install bubblewrap podman`、Docker Desktop 的安裝程式），會改那台電腦的系統。
- rootless podman 有時還要設定 subuid／subgid；這類系統設定交辦單已經寫「不要做」。
- Docker Desktop 在 Windows 上會開 WSL 2 或 Hyper-V、會常駐背景服務；而且有授權條款的問題（商用情境）。
- 拉映像是另一個題目：[驗證機能不能拉官方 Python 容器映像](20261119-134610-verification-container-image.md)。

## 選項

| 選項 | 一句話 | 建議 |
|---|---|---|
| A | 不裝：只用那台本來就有的；沒有的項目寫「略過：沒有 XXX」 | 沒決定時的預設 |
| B | Linux 驗證機可以用發行版的套件庫裝 `bubblewrap` 與 `podman`（不設定 subuid、不改 cgroup；裝不起來就停）；Windows 不裝 Docker Desktop | ✅ 建議 |
| C | B 再加上 Windows 驗證機可以裝 Docker Desktop（擁有者先確認授權與那台的用途） | |

## 驗收

- 選 A：沒有的項目都是「略過：沒有 XXX」，第六節備註寫擁有者接受。
- 選 B／C：回報裡寫裝了什麼、版本、用什麼指令裝；驗完要不要移除由擁有者在這裡註明（沒註明＝保留，回報裡列出來）。

## 不要做的事

- 不要改 subuid／subgid、cgroup、群組原則、防火牆。
- 不要從套件庫以外的地方（別人的腳本、`curl | sh`）裝。
- 不要在擁有者平常用的開發機上裝。
