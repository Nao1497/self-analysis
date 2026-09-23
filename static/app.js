// TagClip の画面で使う小さな補助機能

// タグ候補の絞り込み（文字で絞る入力欄と、★だけ／☆だけのボタン）
function applyTagFilter(container) {
  const word = (container.dataset.word || "").toLowerCase();
  const mark = container.dataset.mark || "";
  container.querySelectorAll("[data-name]").forEach((el) => {
    const name = el.dataset.name;
    el.hidden = (word !== "" && !name.includes(word)) || (mark !== "" && !name.startsWith(mark));
  });
}

document.querySelectorAll(".tag-filter").forEach((input) => {
  const container = document.querySelector(input.dataset.target);
  if (!container) return;
  input.addEventListener("input", () => {
    container.dataset.word = input.value.trim();
    applyTagFilter(container);
  });
  // 入力欄でEnterを押してもフォームが送信されないようにする
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") e.preventDefault();
  });
});

document.querySelectorAll(".mark-toggle").forEach((group) => {
  const container = document.querySelector(group.dataset.target);
  if (!container) return;
  group.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      group.querySelectorAll("button").forEach((b) => b.classList.toggle("is-on", b === button));
      container.dataset.mark = button.dataset.mark;
      applyTagFilter(container);
    });
  });
});

// 登録画面：タグを選んでから ★ か ☆ を選ぶ
(function markPicker() {
  const picker = document.getElementById("mark-picker");
  if (!picker) return;
  const list = document.getElementById("selected-marks");
  const empty = document.getElementById("selected-empty");
  const input = document.getElementById("mark-input");
  const selected = []; // { name, mark }

  const find = (name) => selected.findIndex((s) => s.name.toLowerCase() === name.toLowerCase());
  const clean = (text) => text.trim().replace(/^[★☆#＃\s]+/, "").trim();

  function render() {
    list.innerHTML = "";
    selected.forEach((item, i) => {
      const li = document.createElement("li");

      const name = document.createElement("span");
      name.className = "name " + (item.mark === "★" ? "mark-star" : "mark-hollow");
      name.textContent = item.mark + item.name;
      li.appendChild(name);

      const seg = document.createElement("span");
      seg.className = "mark-choice";
      ["★", "☆"].forEach((m) => {
        const b = document.createElement("button");
        b.type = "button";
        b.textContent = m;
        b.className = (m === "★" ? "mark-star" : "mark-hollow") + (item.mark === m ? " is-on" : "");
        b.setAttribute("aria-pressed", item.mark === m);
        b.setAttribute("aria-label", `${item.name} に ${m} を付ける`);
        b.addEventListener("click", () => { item.mark = m; render(); });
        seg.appendChild(b);
      });
      li.appendChild(seg);

      const del = document.createElement("button");
      del.type = "button";
      del.className = "remove";
      del.textContent = "✕";
      del.setAttribute("aria-label", `${item.name} を外す`);
      del.addEventListener("click", () => { selected.splice(i, 1); render(); });
      li.appendChild(del);

      const hidden = document.createElement("input");
      hidden.type = "hidden";
      hidden.name = "mark_tag";
      hidden.value = item.mark + item.name;
      li.appendChild(hidden);

      list.appendChild(li);
    });
    empty.hidden = selected.length > 0;
    // 候補ボタンは、選んだものを色付きで表示する
    picker.querySelectorAll(".cand").forEach((b) => {
      const i = find(b.dataset.name);
      b.classList.toggle("mark-star", i >= 0 && selected[i].mark === "★");
      b.classList.toggle("mark-hollow", i >= 0 && selected[i].mark === "☆");
      b.setAttribute("aria-pressed", i >= 0);
    });
  }

  function add(name, mark) {
    name = clean(name);
    if (!name || find(name) >= 0) return;
    selected.push({ name, mark: mark || "★" });
    render();
  }

  // 候補をタップ：選ぶ（前回と同じ印で）／もう一度タップで外す
  picker.querySelectorAll(".cand").forEach((b) => {
    b.addEventListener("click", () => {
      const i = find(b.dataset.name);
      if (i >= 0) { selected.splice(i, 1); render(); }
      else add(b.dataset.name, b.dataset.mark);
    });
  });

  // 入力して追加（Enterキーでも追加）
  const addTyped = () => {
    input.value.split(/[,、，]/).forEach((t) => add(t));
    input.value = "";
    input.focus();
  };
  document.getElementById("mark-add").addEventListener("click", addTyped);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); addTyped(); }
  });

  // エラーで画面が戻ってきたときは、選んでいたタグを復元する
  try {
    JSON.parse(picker.dataset.initial || "[]").forEach((t) => add(t.slice(1), t[0]));
  } catch (e) { /* 何もしない */ }
  render();
})();

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
