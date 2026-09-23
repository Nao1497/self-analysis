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

// 編集画面：タグをタップ → ★ / ☆ / 印なし / 削除 を選ぶ
(function tagEditor() {
  const editor = document.getElementById("tag-editor");
  const textarea = document.getElementById("tags");
  if (!editor || !textarea) return;
  const chips = document.getElementById("edit-chips");
  const empty = document.getElementById("edit-empty");
  const action = document.getElementById("tag-action");
  const actionName = document.getElementById("action-name");
  const dirty = document.getElementById("edit-dirty");
  const addInput = document.getElementById("edit-add-input");
  let tags = [];
  let current = -1; // タップ中のタグの番号

  const baseName = (t) => t.replace(/^[★☆]\s*/, "");
  const markClass = (t) => (t.startsWith("★") ? "mark-star" : t.startsWith("☆") ? "mark-hollow" : "");
  const read = () => textarea.value.split("\n").map((t) => t.trim()).filter(Boolean);
  const write = () => {
    textarea.value = tags.join("\n");
    dirty.hidden = false;
  };

  function render() {
    chips.innerHTML = "";
    tags.forEach((t, i) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = `chip tag-btn ${markClass(t)}` + (i === current ? " is-current" : "");
      b.textContent = t;
      b.setAttribute("aria-pressed", i === current);
      b.addEventListener("click", () => open(i));
      chips.appendChild(b);
    });
    empty.hidden = tags.length > 0;
    action.hidden = current < 0;
    if (current >= 0) actionName.textContent = tags[current];
  }

  function open(i) {
    current = current === i ? -1 : i;
    render();
    if (current >= 0) action.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  function apply(set) {
    if (current < 0) return;
    if (set === "delete") {
      tags.splice(current, 1);
    } else if (set !== "cancel") {
      const target = tags[current];
      const base = baseName(target).toLowerCase();
      // 同じ名前のタグ（印だけ違うもの）がほかにあれば、重ならないようにそちらを外す
      tags = tags.filter((t, i) => i === current || baseName(t).toLowerCase() !== base);
      tags[tags.indexOf(target)] = set + baseName(target);
    }
    if (set !== "cancel") write();
    current = -1;
    render();
  }

  action.querySelectorAll("button[data-set]").forEach((b) => {
    b.addEventListener("click", () => apply(b.dataset.set));
  });

  function addTyped() {
    addInput.value.split(/[,、，]/).map((t) => t.trim()).filter(Boolean).forEach((t) => {
      if (!tags.some((x) => x.toLowerCase() === t.toLowerCase())) tags.push(t);
    });
    addInput.value = "";
    write();
    render();
  }
  document.getElementById("edit-add").addEventListener("click", addTyped);
  addInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); addTyped(); }
  });

  // テキストで直接編集したときも表示を合わせる
  textarea.addEventListener("input", () => {
    tags = read();
    current = -1;
    dirty.hidden = false;
    render();
  });

  tags = read();
  render();
})();
