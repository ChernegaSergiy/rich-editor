<script>
  import { dndzone } from 'svelte-dnd-action';

  let { photos = $bindable([]), authKey = '', onupload } = $props();

  let dndItems = $state([]);
  let fileEl = $state(null);
  const flipDurationMs = 200;

  $effect(() => {
    dndItems = photos.map((p) => ({ id: p.up }));
  });

  function handleDndConsider(e) {
    dndItems = e.detail.items;
  }

  function handleDndFinalize(e) {
    dndItems = e.detail.items;
    const byId = new Map(photos.map((p) => [p.up, p]));
    const next = [];
    for (const d of dndItems) {
      const ph = byId.get(d.id);
      if (ph) next.push(ph);
    }
    for (const p of photos) {
      if (!next.includes(p)) next.push(p);
    }
    photos = next;
  }

  function photoOf(id) {
    return photos.find((p) => p.up === id);
  }

  function srcOf(p) {
    return p ? p.url + '?key=' + encodeURIComponent(authKey) : '';
  }

  function removeById(id) {
    const k = photos.findIndex((p) => p.up === id);
    if (k >= 0) photos.splice(k, 1);
  }
</script>

<fieldset>
  <legend>Фото (перетягни, щоб змінити порядок)</legend>
  {#if dndItems.length > 0}
    <div
      class="media-grid"
      use:dndzone={{ items: dndItems, flipDurationMs }}
      onconsider={handleDndConsider}
      onfinalize={handleDndFinalize}
    >
      {#each dndItems as item (item.id)}
        <div>
          <div class="media-item">
            <img src={srcOf(photoOf(item.id))} alt="" draggable="false" />
          </div>
          <div class="media-controls">
            <button
              type="button"
              class="secondary outline"
              style="color: var(--pico-del-color); border-color: var(--pico-del-color);"
              onclick={() => removeById(item.id)}
            >
              Прибрати
            </button>
          </div>
        </div>
      {/each}
    </div>
  {/if}
  <input
    type="file"
    accept="image/*"
    multiple
    style="display: none;"
    bind:this={fileEl}
    onchange={(e) => onupload(e.currentTarget.files)}
  />
  <button type="button" class="secondary" style="border-radius: 99px; margin-bottom: 1rem;" onclick={() => fileEl.click()}>
    + Додати фото
  </button>
</fieldset>
