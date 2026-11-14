# 提燈（範例外觀包）

測試與 docs/themes.md 用的範例：`kind: "theme"`，沒有任何程式。

- `pack.json`：顏色 token（淺色、深色各一套）、換掉的位置（slot）、`theme.css`
- `slots/*.svg`：吉祥物（平常／在想／開心／注意）、開場、字標、分頁圖示
- `theme.css`：每條規則都在 `[data-slot]` 裡面；`@keyframes` 都是 `th-` 開頭

打包：`python scripts/pack_zip.py tests/fixtures/theme_pack`（或直接把這個資料夾壓成 zip、副檔名改 .synoxpack）。
