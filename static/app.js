// TagClip の画面で使う小さな補助機能

// タグ候補をキーワードで絞り込む（入力欄の data-target で対象を指定）
document.querySelectorAll(".tag-filter").forEach((input) => {
  const container = document.querySelector(input.dataset.target);
  if (!container) return;
  input.addEventListener("input", () => {
    const word = input.value.trim().toLowerCase();
    container.querySelectorAll("[data-name]").forEach((el) => {
      el.hidden = word !== "" && !el.dataset.name.includes(word);
    });
  });
  // 入力欄でEnterを押してもフォームが送信されないようにする
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") e.preventDefault();
  });
});

// 取得待ちの件数を数秒ごとに確認して、画面上部に表示する
(function watchStatus() {
  const bar = document.getElementById("status-bar");
  if (!bar || Number(bar.dataset.pending) === 0) return;
  const text = document.getElementById("status-text");
  const reload = document.getElementById("status-reload");

  const timer = setInterval(async () => {
    try {
      const res = await fetch("/api/status");
      const data = await res.json();
      if (data.pending > 0) {
        text.textContent = `⏳ タグを取得中… 残り ${data.pending} 件`;
      } else {
        clearInterval(timer);
        text.textContent =
          data.error > 0 ? `✔ 取得が終わりました（エラーの記事：全${data.error}件）` : "✔ 取得が終わりました";
        reload.hidden = false;
      }
    } catch (e) {
      // アプリが停止している場合など。次の確認で再試行する
    }
  }, 3000);
})();
