<script>
  import SlideshowEditor from './SlideshowEditor.svelte';
  let key = $state(localStorage.getItem('re_key') || '');
  let authed = $state(false);
  let channel = $state('');
  let gateErr = $state('');
  let view = $state('compose');
  let blocks = $state([]);
  let editing = $state(null);
  let chat = $state('');
  let foreignId = $state('');
  let result = $state('');
  let posts = $state([]);
  let banner = $state('');
  let bannerErr = $state(false);
  let bannerTimer = null;

  function displayBanner(msg, isErr = false) {
    banner = msg;
    bannerErr = !!isErr;
    clearTimeout(bannerTimer);
    bannerTimer = setTimeout(() => {
      banner = '';
    }, 4000);
  }

  const NAMES = { p: 'Абзац', h: 'Заголовок', slideshow: 'Слайдшоу', divider: 'Розділювач' };

  function esc(s) {
    return (s || '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
  }

  function md(t) {
    let o = esc(t);
    o = o
      .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
      .replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, '<i>$1</i>')
      .replace(/`(.+?)`/g, '<code>$1</code>')
      .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2">$1</a>');
    return o.replace(/\n/g, '<br>');
  }

  function img(photo) {
    return photo.url + '?key=' + encodeURIComponent(key);
  }

  async function api(path, method, body, form) {
    const headers = { 'X-Auth-Key': key };
    const opts = { method: method || 'GET', headers };
    if (form) opts.body = form;
    else if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    return (await fetch(path, opts)).json();
  }

  async function login() {
    key = key.trim();
    localStorage.setItem('re_key', key);
    const r = await api('/api/config');
    if (r.ok) {
      authed = true;
      gateErr = '';
      channel = r.channel;
      chat = r.channel;
      if (!blocks.length) add('slideshow');
    } else {
      gateErr = 'Невірний ключ';
    }
  }

  function add(t) {
    const b = { t };
    if (t === 'p') b.text = '';
    if (t === 'h') {
      b.level = 2;
      b.text = '';
    }
    if (t === 'slideshow') {
      b.photos = [];
      b.caption = '';
    }
    blocks.push(b);
  }

  function del(i) {
    blocks.splice(i, 1);
  }

  function mv(i, d) {
    const j = i + d;
    if (j < 0 || j >= blocks.length) return;
    [blocks[i], blocks[j]] = [blocks[j], blocks[i]];
  }

  async function up(bi, files) {
    for (const f of files) {
      const fd = new FormData();
      fd.append('photo', f);
      const r = await api('/api/upload', 'POST', null, fd);
      if (r.ok) blocks[bi].photos.push({ up: r.upload_id, url: r.preview_url });
      else displayBanner(r.description, true);
    }
  }

  async function send() {
    const r = await api('/api/send', 'POST', { chat, blocks });
    result = r.ok
      ? `Опубліковано: <a target="_blank" href="${r.link}">${r.link}</a>`
      : 'Помилка: ' + r.description;
  }

  async function saveEdit() {
    const b = { blocks };
    if (editing) b.post_id = editing;
    else if (foreignId.trim()) b.message_id = +foreignId.trim();
  else {
    displayBanner('Нема чого правити: відкрий пост зі списку або введи message_id', true);
    return;
  }
    b.chat = chat;
    const r = await api('/api/edit', 'POST', b);
    result = r.ok
      ? `Збережено: <a target="_blank" href="${r.link}">${r.link}</a>`
      : 'Помилка: ' + r.description;
  }

  async function loadPosts() {
    const r = await api('/api/posts');
    posts = r.ok ? r.posts : [];
  }

  async function editPost(p) {
    const q = await api('/api/posts/' + p.id);
    if (q.ok) {
      blocks = q.post.blocks;
      editing = p.id;
      view = 'compose';
    }
  }

  async function removePost(p) {
    if (confirm('Видалити пост #' + p.message_id + '?')) {
      await api('/api/delete', 'POST', { post_id: p.id });
      loadPosts();
    }
  }

  function logout() {
    key = '';
    localStorage.removeItem('re_key');
    authed = false;
    editing = null;
    banner = '';
  }

  function show(tab) {
    view = tab;
    if (tab === 'posts') loadPosts();
  }

  if (key) login();
</script>

{#if !authed}
  <div class="auth-layout">
    <div class="auth-card">
      <h2 style="margin-bottom: 0.5rem; color: var(--primary);">Rich-редактор</h2>
      <p style="color: var(--pico-muted-color); margin-bottom: 2rem;">
        Дописи в канал без Premium: текст — абзацами, фото — слайдшоу.
      </p>
      <form onsubmit={(e) => { e.preventDefault(); login(); }}>
        <input
          type="password"
          bind:value={key}
          autocomplete="off"
          placeholder="ADMIN_KEY"
          aria-label="ADMIN_KEY"
        />
        <button type="submit">Увійти</button>
      </form>
      <p style="margin-top: 1.5rem; font-size: 0.85rem; color: var(--pico-muted-color);">
        Ключ зберігається тільки в цьому браузері.
      </p>
      <p><small>{gateErr}</small></p>
    </div>
  </div>
{:else}
  <div class="dashboard-layout">
    <aside class="sidebar">
      <div class="sidebar-header">Rich-редактор</div>
      <nav>
        <ul>
          <li><a class:active={view === 'compose'} onclick={() => show('compose')}>Допис</a></li>
          <li><a class:active={view === 'posts'} onclick={() => show('posts')}>Надіслані</a></li>
        </ul>
      </nav>
      <div class="sidebar-footer"><span class="badge">{channel}</span></div>
    </aside>
    <div class="main-content">
      <div class="topbar">
        <span></span>
        <div style="display: flex; gap: 0.5rem; align-items: center;">
          {#if editing}<span class="badge">Правка #{editing}</span>{/if}
          <span class="badge active">{channel || '…'}</span>
          <button
            type="button"
            class="secondary outline"
            style="border-radius: 99px; margin: 0; padding: 0.35rem 1rem; font-size: 0.85rem;"
            onclick={logout}
          >
            Вийти
          </button>
        </div>
      </div>
      <div class="content-area">
        {#if view === 'compose'}
          <article>
            <h2>Блоки</h2>
            {#each blocks as b, i}
              <article style="margin: 0 0 0.75rem;">
                <div class="block-head">
                  <strong>{NAMES[b.t]}</strong>
                  <div class="actions">
                    <button type="button" class="secondary" onclick={() => mv(i, -1)}>↑</button>
                    <button type="button" class="secondary" onclick={() => mv(i, 1)}>↓</button>
                    <button type="button" class="secondary" onclick={() => del(i)}>✕</button>
                  </div>
                </div>
                {#if b.t === 'p'}
                  <textarea bind:value={b.text} placeholder="Текст абзацу"></textarea>
                {:else if b.t === 'h'}
                  <div class="grid">
                    <label>Рівень 1–6<input bind:value={b.level} /></label>
                    <label>Текст<textarea bind:value={b.text}></textarea></label>
                  </div>
                {:else if b.t === 'slideshow'}
                  <SlideshowEditor
                    bind:photos={b.photos}
                    authKey={key}
                    onupload={(f) => up(i, f)}
                  />
                  <label style="margin-top: 0.5rem;">
                    Короткий підпис (можна порожньо)
                    <input bind:value={b.caption} />
                  </label>
                {/if}
              </article>
            {/each}
            <div role="group">
              <button type="button" class="secondary" onclick={() => add('p')}>+ Абзац</button>
              <button type="button" class="secondary" onclick={() => add('h')}>+ Заголовок</button>
              <button type="button" class="secondary" onclick={() => add('slideshow')}>+ Слайдшоу</button>
              <button type="button" class="secondary" onclick={() => add('divider')}>+ Розділювач</button>
            </div>
            <p><small>Розмітка: **жирний**, *курсив*, `код`, [текст](https://url). Довгий текст — абзацами, а не підписом.</small></p>
          </article>

          <article>
            <h2>Як побачать читачі</h2>
            {#each blocks as b}
              {#if b.t === 'p'}
                <div class="bubble">{@html md(b.text || '…')}</div>
              {:else if b.t === 'h'}
                <div class="bubble"><h3>{@html md(b.text || '…')}</h3></div>
              {:else if b.t === 'divider'}
                <hr />
              {:else if b.t === 'slideshow'}
                <div class="bubble">
                  <div class="grid">
                    {#each b.photos as p}
                      <img src={img(p)} alt="" />
                    {/each}
                  </div>
                  {#if b.caption}<small>{@html md(b.caption)}</small>{/if}
                </div>
              {/if}
            {:else}
              <small>Порожньо.</small>
            {/each}
          </article>

          <article>
            <h2>Публікація</h2>
            <div class="grid">
              <label>Канал<input bind:value={chat} /></label>
              <label>message_id для правки чужого<input bind:value={foreignId} placeholder="порожньо — свій" /></label>
            </div>
            <div role="group">
              <button type="button" onclick={send}>Надіслати новий</button>
              <button type="button" class="secondary" onclick={saveEdit}>Зберегти правку</button>
            </div>
            <p>{@html result}</p>
          </article>
        {:else}
          <div class="page-header">
            <div>
              <h2 style="margin: 0;">Надіслані дописи</h2>
              <p style="color: var(--pico-muted-color); margin: 0;">Опубліковане в каналі.</p>
            </div>
            <button
              type="button"
              style="border-radius: 99px; padding: 0.5rem 1.5rem; margin: 0;"
              onclick={loadPosts}
            >
              Оновити
            </button>
          </div>
          {#if posts.length === 0}
            <article
              style="text-align: center; padding: 3rem; background-color: transparent; border: 2px dashed var(--pico-muted-border-color); box-shadow: none;"
            >
              <p style="color: var(--pico-muted-color); margin: 0;">Поки порожньо.</p>
            </article>
          {:else}
            <div class="card-grid">
              {#each posts as p}
                <article class="card">
                  <header>
                    <a target="_blank" href={p.link}>#{p.message_id}</a>
                  </header>
                  <div class="content">
                    <span class="badge">{p.chat}</span>
                    <div class="moh-meta">{p.created_at.slice(0, 16).replace('T', ' ')}</div>
                    <div class="moh-meta">{p.excerpt}</div>
                  </div>
                  <footer>
                    <button
                      type="button"
                      class="secondary outline"
                      style="border-radius: 99px; margin: 0; padding: 0.35rem 1rem; font-size: 0.85rem;"
                      onclick={() => editPost(p)}
                    >
                      Правити
                    </button>
                    <button
                      type="button"
                      class="secondary outline"
                      style="border-radius: 99px; margin: 0; padding: 0.35rem 1rem; font-size: 0.85rem; color: var(--pico-del-color); border-color: var(--pico-del-color);"
                      onclick={() => removePost(p)}
                    >
                      Видалити
                    </button>
                  </footer>
                </article>
              {/each}
            </div>
          {/if}
        {/if}
      </div>
    </div>
  </div>
  {#if banner}
    <div class="app-banner" class:app-error={bannerErr}>{banner}</div>
  {/if}
{/if}
