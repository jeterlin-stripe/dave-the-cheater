"""Traditional Chinese / English strings for the local control panel."""
TRANSLATIONS = {
    "啟動遊戲": "Launch game",
    "遊戲已在執行中。": "The game is already running.",
    "尚有未套用的設定": "Unapplied changes",
    "目前變更尚未套用。要使用先前已套用的設定啟動遊戲嗎？": "Your changes have not been applied. Launch the game with the previously applied settings?",
    "已向 Steam 發送啟動請求。": "Launch request sent to Steam.",
    "無法啟動遊戲": "Could not launch the game",
    "無限貨物無人機": "Infinite cargo drone",
    "無人機開啟後不扣搬運次數；已零次時可能需要先重新潛水。": "Cargo drone uses will not decrease. If already at zero, you may need a new dive first.",
    "Dave the Cheater": "Dave the Cheater",
    "修改遊戲檔案 · 套用後重新啟動生效": "Edit game files · Restart the game after applying",
    "選擇遊戲資料夾": "Game folder",
    "無限彈藥": "Infinite ammo",
    "無敵": "Invincible",
    "水下移動速度倍率": "Swimming speed multiplier",
    "1 = 原始速度；可輸入 0.1–20，例如 3.5。\n氧氣補丁會保留目前狀態；無敵關閉後仍會受傷。": "1 = Original speed. Enter 0.1–20, for example 3.5.\nThe current oxygen setting is preserved. Turn off Invincible to take damage.",
    "套用設定": "Apply settings",
    "讀取目前設定": "Read current settings",
    "還原全部原始設定": "Restore all defaults",
    "彈藥涵蓋共用潛水槍械流程；尚未驗證所有 DLC／特殊武器。\n遊戲更新或其他模組造成版本不同時，工具會拒絕覆寫。": "Ammo covers shared diving gun logic; not every DLC or special weapon is verified.\nThe tool refuses to overwrite updated or otherwise modified game files.",
    "正在讀取目前設定…": "Reading current settings…",
    "設定尚未套用。請先關閉遊戲，再按「套用設定」。": "Changes are not applied. Close the game, then click Apply settings.",
    "選擇含有 DaveTheDiver.exe 的資料夾": "Select the folder containing DaveTheDiver.exe",
    "已讀取檔案設定。氧氣補丁：開啟。": "Settings read from game files. Oxygen patch: ON.",
    "已讀取檔案設定。氧氣補丁：關閉。": "Settings read from game files. Oxygen patch: OFF.",
    "讀取失敗：": "Could not read settings: ",
    "套用成功，已讀回核對。請重新啟動遊戲。": "Settings applied and verified. Restart the game.",
    "未能套用；請查看錯誤訊息。": "Could not apply settings. See the error message.",
    "套用失敗": "Could not apply settings",
    "還原原始設定": "Restore original settings",
    "將還原原始速度、彈藥、無人機與受傷規則，也會關閉氧氣補丁。是否繼續？": "Restore original speed, ammo, cargo drone and damage rules, and turn off the oxygen patch?",
    "已還原全部原始檔案，並完成核對。": "All original files restored and verified.",
    "還原失敗": "Could not restore defaults",
    "無法確認遊戲是否執行中；未套用任何變更。": "Cannot check whether the game is running. No changes applied.",
    "無法讀取程序清單。": "Cannot read the process list.",
    "程序清單讀取不完整。": "Could not read the complete process list.",
    "原始備份校驗失敗，請保留檔案並停止操作。": "Original backup verification failed. Keep the files and stop here.",
    "遊戲程式版本或修改內容不符合；未覆寫。": "Game version or patch contents do not match. Nothing overwritten.",
    "遊戲程式已有更新或其他修改；本工具拒絕覆寫。": "Game program has been updated or modified. Refusing to overwrite it.",
    "速度資源版本不符合；未覆寫。": "Speed asset version does not match. Nothing overwritten.",
    "速度資源結構不符合。": "Speed asset structure does not match.",
    "速度資源包含其他修改；本工具拒絕覆寫。": "Speed asset contains other changes. Refusing to overwrite it.",
    "無法辨識速度數值。": "Cannot identify the speed value.",
    "倍率請輸入 0.1 至 20 之間的數字。": "Enter a speed multiplier between 0.1 and 20.",
    "請先完全關閉 DAVE THE DIVER，再按套用。": "Close DAVE THE DIVER completely before applying settings.",
    "遊戲剛剛啟動，已取消套用。": "The game just started. Applying settings was cancelled.",
    "檔案在檢查後發生變更，已取消套用。": "Files changed after verification. Applying settings was cancelled.",
    "寫入後校驗失敗。": "File verification failed after writing.",
    "還原校驗失敗": "Restore verification failed",
    "套用失敗，且自動還原不完整。請勿啟動遊戲。": "Applying settings failed and rollback is incomplete. Do not start the game.",
    "未能套用，已保留／還原先前版本。": "Could not apply settings. The previous version was kept or restored.",
    "讀回的設定與預期不同。": "Read-back settings do not match.",
    "請先選擇遊戲資料夾。": "Select the game folder first.",
    "找不到所需檔案：": "Required file not found: ",
    "無法存取檔案，請確認檔案未被佔用且目前帳號有寫入權限。": "Cannot access the file. Check that it is not in use and your account has write access.",
    "語言偏好無法儲存；本次切換仍已生效。": "Language changed, but the preference could not be saved.",
}


def translate(text, language):
    text = str(text)
    if language != "en":
        return text
    if text in TRANSLATIONS:
        return TRANSLATIONS[text]
    # Composite error messages can include translated context plus OS details.
    for source in sorted(TRANSLATIONS, key=len, reverse=True):
        if source != TRANSLATIONS[source]:
            text = text.replace(source, TRANSLATIONS[source])
    return text
