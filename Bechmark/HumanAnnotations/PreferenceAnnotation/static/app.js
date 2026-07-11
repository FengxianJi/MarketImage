const state = {
  annotator: localStorage.getItem("emergingart.annotator") || "anonymous",
  dataset: localStorage.getItem("emergingart.dataset") || "Overall",
  groupId: Number(localStorage.getItem("emergingart.groupId") || 0),
  groupLimit: localStorage.getItem("emergingart.groupLimit") || "",
  datasets: [],
  groups: [],
  items: [],
  notes: "",
  dragId: null,
  startedAt: Date.now(),
  existingCompleted: false,
};

const els = {
  annotatorInput: document.getElementById("annotatorInput"),
  datasetSelect: document.getElementById("datasetSelect"),
  exportButton: document.getElementById("exportButton"),
  statusLine: document.getElementById("statusLine"),
  progressText: document.getElementById("progressText"),
  remainingText: document.getElementById("remainingText"),
  progressFill: document.getElementById("progressFill"),
  groupFilter: document.getElementById("groupFilter"),
  limitInput: document.getElementById("limitInput"),
  firstPendingButton: document.getElementById("firstPendingButton"),
  groupList: document.getElementById("groupList"),
  groupTitle: document.getElementById("groupTitle"),
  groupMeta: document.getElementById("groupMeta"),
  prevButton: document.getElementById("prevButton"),
  nextButton: document.getElementById("nextButton"),
  rankBoard: document.getElementById("rankBoard"),
  notesInput: document.getElementById("notesInput"),
  reloadButton: document.getElementById("reloadButton"),
  saveButton: document.getElementById("saveButton"),
  saveNextButton: document.getElementById("saveNextButton"),
  modal: document.getElementById("modal"),
  modalTitle: document.getElementById("modalTitle"),
  modalSubtitle: document.getElementById("modalSubtitle"),
  modalImage: document.getElementById("modalImage"),
  modalClose: document.getElementById("modalClose"),
};

function setStatus(message) {
  els.statusLine.textContent = message;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : {};
  if (!response.ok) {
    throw new Error(payload.error || response.statusText);
  }
  return payload;
}

function encodeQuery(params) {
  return new URLSearchParams(params).toString();
}

function persistBasics() {
  localStorage.setItem("emergingart.annotator", state.annotator);
  localStorage.setItem("emergingart.dataset", state.dataset);
  localStorage.setItem("emergingart.groupId", String(state.groupId));
  localStorage.setItem("emergingart.groupLimit", state.groupLimit);
}

function scopedQuery(extra = {}) {
  const query = {
    annotator: state.annotator,
    ...extra,
  };
  if (state.groupLimit) {
    query.limit = state.groupLimit;
  }
  return encodeQuery(query);
}

async function loadDatasets() {
  const query = scopedQuery();
  const data = await api(`/api/datasets?${query}`);
  state.datasets = data.datasets || [];

  const names = state.datasets.map((item) => item.name);
  if (!names.includes(state.dataset)) {
    state.dataset = names.includes("Overall") ? "Overall" : names[0];
  }

  els.datasetSelect.replaceChildren();
  for (const dataset of state.datasets) {
    const option = document.createElement("option");
    option.value = dataset.name;
    const scopeText = state.groupLimit ? `${dataset.total_groups}/${dataset.dataset_groups}` : `${dataset.total_groups}`;
    option.textContent = `${dataset.name} (${dataset.completed_groups}/${scopeText})`;
    els.datasetSelect.append(option);
  }
  els.datasetSelect.value = state.dataset;
}

function syncGroupSelection({ preferPending = false } = {}) {
  if (!state.groups.length) {
    state.groupId = 0;
    return;
  }
  const pending = state.groups.find((group) => !group.completed);
  const exists = state.groups.some((group) => group.group_id === state.groupId);
  if (preferPending && pending) {
    state.groupId = pending.group_id;
  } else if (!exists) {
    state.groupId = pending?.group_id ?? state.groups[0].group_id;
  }
}

async function loadGroups(options = {}) {
  const query = scopedQuery({ dataset: state.dataset });
  const data = await api(`/api/groups?${query}`);
  state.groups = data.groups || [];
  syncGroupSelection(options);
  renderProgress();
  renderGroupList();
}

async function loadGroup() {
  if (!state.dataset && state.datasets.length) {
    state.dataset = state.datasets[0].name;
  }
  const query = scopedQuery({ dataset: state.dataset, group_id: state.groupId });
  const data = await api(`/api/group?${query}`);
  state.items = data.items || [];
  state.notes = data.existing_annotation?.notes || "";
  state.existingCompleted = Boolean(data.existing_annotation?.completed);
  state.startedAt = Date.now();
  els.notesInput.value = state.notes;
  renderGroupHeader(data.existing_annotation);
  renderBoard();
  renderGroupList();
  persistBasics();
}

function renderProgress() {
  const total = state.groups.length;
  const done = state.groups.filter((group) => group.completed).length;
  const percentage = total ? Math.round((done / total) * 100) : 0;
  els.progressText.textContent = `${done} / ${total}`;
  const limitText = state.groupLimit ? `, limit ${state.groupLimit}` : "";
  els.remainingText.textContent = `${Math.max(total - done, 0)} left${limitText}`;
  els.progressFill.style.width = `${percentage}%`;
}

function renderGroupList() {
  const filter = els.groupFilter.value.trim();
  els.groupList.replaceChildren();
  for (const group of state.groups) {
    const label = String(group.group_id);
    if (filter && !label.includes(filter)) continue;

    const button = document.createElement("button");
    button.type = "button";
    button.className = "groupButton";
    button.textContent = label;
    button.title = `Group ${label}, data order ${group.group_order}`;
    if (group.group_id === state.groupId) button.classList.add("active");
    if (group.completed) button.classList.add("done");
    button.addEventListener("click", () => selectGroup(group.group_id));
    els.groupList.append(button);
  }
}

function renderGroupHeader(existing) {
  const index = state.groups.findIndex((group) => group.group_id === state.groupId);
  const group = state.groups[index];
  const total = state.groups.length;
  const completedText = existing?.completed ? `Saved ${existing.updated_at || ""}` : "Not saved";
  els.groupTitle.textContent = `${state.dataset} / Group ${state.groupId}`;
  const orderText = group ? `data order ${group.group_order}` : "data order ?";
  els.groupMeta.textContent = `${index + 1} of ${total} groups, ${orderText}, ${state.items.length} images, ${completedText}`;
  els.prevButton.disabled = index <= 0;
  els.nextButton.disabled = index < 0 || index >= total - 1;
  setStatus(completedText);
}

function renderBoard() {
  els.rankBoard.replaceChildren();
  if (!state.items.length) {
    const empty = document.createElement("div");
    empty.className = "emptyState";
    empty.textContent = "No images";
    els.rankBoard.append(empty);
    return;
  }

  state.items.forEach((item, index) => {
    const card = document.createElement("article");
    card.className = "card";
    card.draggable = true;
    card.dataset.folderId = item.folder_id;

    card.addEventListener("dragstart", (event) => {
      state.dragId = item.folder_id;
      card.classList.add("dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", item.folder_id);
    });
    card.addEventListener("dragend", () => {
      state.dragId = null;
      document.querySelectorAll(".dropTarget").forEach((node) => node.classList.remove("dropTarget"));
      card.classList.remove("dragging");
    });
    card.addEventListener("dragover", (event) => {
      event.preventDefault();
      if (state.dragId && state.dragId !== item.folder_id) {
        card.classList.add("dropTarget");
      }
    });
    card.addEventListener("dragleave", () => card.classList.remove("dropTarget"));
    card.addEventListener("drop", (event) => {
      event.preventDefault();
      card.classList.remove("dropTarget");
      const sourceId = event.dataTransfer.getData("text/plain") || state.dragId;
      moveBefore(sourceId, item.folder_id);
    });

    const imageButton = document.createElement("button");
    imageButton.className = "imageButton";
    imageButton.type = "button";
    imageButton.addEventListener("click", () => openModal(item, index));

    const image = document.createElement("img");
    image.src = item.image_url;
    image.alt = `Artwork ${item.folder_id}`;
    image.loading = "lazy";
    imageButton.append(image);

    const rank = document.createElement("div");
    rank.className = "rankBadge";
    rank.textContent = `#${index + 1}`;

    const body = document.createElement("div");
    body.className = "cardBody";

    const title = document.createElement("p");
    title.className = "cardTitle";
    const titleText = document.createElement("span");
    titleText.textContent = `ID ${item.folder_id}`;
    const sourceOrder = document.createElement("span");
    sourceOrder.className = "sourceOrder";
    sourceOrder.textContent = `Data #${item.source_order}`;
    title.append(titleText, sourceOrder);

    body.append(title);

    const controls = document.createElement("div");
    controls.className = "cardControls";
    controls.append(
      controlButton("Top", () => moveTo(item.folder_id, 0), index === 0),
      controlButton("Up", () => moveBy(item.folder_id, -1), index === 0),
      controlButton("Down", () => moveBy(item.folder_id, 1), index === state.items.length - 1),
      controlButton("View", () => openModal(item, index), false),
    );

    card.append(imageButton, rank, body, controls);
    els.rankBoard.append(card);
  });
}

function controlButton(label, onClick, disabled) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary";
  button.textContent = label;
  button.disabled = disabled;
  button.addEventListener("click", onClick);
  return button;
}

function moveBefore(sourceId, targetId) {
  if (!sourceId || !targetId || sourceId === targetId) return;
  const sourceIndex = state.items.findIndex((item) => item.folder_id === sourceId);
  const targetIndex = state.items.findIndex((item) => item.folder_id === targetId);
  if (sourceIndex < 0 || targetIndex < 0) return;
  const [item] = state.items.splice(sourceIndex, 1);
  const adjustedTarget = state.items.findIndex((candidate) => candidate.folder_id === targetId);
  state.items.splice(adjustedTarget, 0, item);
  renderBoard();
}

function moveBy(folderId, delta) {
  const index = state.items.findIndex((item) => item.folder_id === folderId);
  const nextIndex = Math.max(0, Math.min(state.items.length - 1, index + delta));
  moveTo(folderId, nextIndex);
}

function moveTo(folderId, targetIndex) {
  const index = state.items.findIndex((item) => item.folder_id === folderId);
  if (index < 0 || index === targetIndex) return;
  const [item] = state.items.splice(index, 1);
  state.items.splice(targetIndex, 0, item);
  renderBoard();
}

async function selectGroup(groupId) {
  state.groupId = Number(groupId);
  persistBasics();
  setStatus("Loading group");
  await loadGroup();
}

function currentGroupIndex() {
  return state.groups.findIndex((group) => group.group_id === state.groupId);
}

async function goToOffset(delta) {
  const index = currentGroupIndex();
  const target = state.groups[index + delta];
  if (!target) return;
  await selectGroup(target.group_id);
}

async function goToFirstPending() {
  const pending = state.groups.find((group) => !group.completed);
  if (pending) {
    await selectGroup(pending.group_id);
  }
}

async function saveAnnotation({ goNext = false } = {}) {
  if (!state.items.length) return;
  const payload = {
    annotator: state.annotator,
    dataset: state.dataset,
    group_id: state.groupId,
    group_limit: state.groupLimit || null,
    ranked_folder_ids: state.items.map((item) => item.folder_id),
    notes: els.notesInput.value,
    duration_ms: Date.now() - state.startedAt,
  };
  els.saveButton.disabled = true;
  els.saveNextButton.disabled = true;
  setStatus("Saving");
  try {
    const result = await api("/api/annotation", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.existingCompleted = true;
    const current = state.groups.find((group) => group.group_id === state.groupId);
    if (current) current.completed = true;
    renderProgress();
    renderGroupList();
    await loadDatasets();
    setStatus(`Saved ${result.updated_at}`);
    if (goNext) {
      const index = currentGroupIndex();
      const nextPending = state.groups.slice(index + 1).find((group) => !group.completed);
      const fallback = state.groups[index + 1];
      const target = nextPending || fallback;
      if (target) await selectGroup(target.group_id);
    }
  } finally {
    els.saveButton.disabled = false;
    els.saveNextButton.disabled = false;
  }
}

function openModal(item, index) {
  els.modalTitle.textContent = `Rank ${index + 1} / ID ${item.folder_id}`;
  els.modalSubtitle.textContent = state.dataset ? `${state.dataset} group ${state.groupId}` : "";
  els.modalImage.src = item.image_url;
  els.modalImage.alt = `Artwork ${item.folder_id}`;
  els.modal.hidden = false;
}

function closeModal() {
  els.modal.hidden = true;
  els.modalImage.removeAttribute("src");
}

function bindEvents() {
  els.annotatorInput.value = state.annotator;
  els.limitInput.value = state.groupLimit;
  els.annotatorInput.addEventListener("change", async () => {
    state.annotator = els.annotatorInput.value.trim() || "anonymous";
    persistBasics();
    setStatus("Switching annotator");
    await loadDatasets();
    await loadGroups({ preferPending: true });
    await loadGroup();
  });

  els.datasetSelect.addEventListener("change", async () => {
    state.dataset = els.datasetSelect.value;
    state.groupId = 0;
    persistBasics();
    setStatus("Switching dataset");
    await loadDatasets();
    await loadGroups({ preferPending: true });
    await loadGroup();
  });

  els.limitInput.addEventListener("change", async () => {
    const nextLimit = els.limitInput.value.trim();
    state.groupLimit = nextLimit;
    persistBasics();
    setStatus("Changing group limit");
    await loadDatasets();
    await loadGroups({ preferPending: true });
    await loadGroup();
  });

  els.groupFilter.addEventListener("input", renderGroupList);
  els.firstPendingButton.addEventListener("click", goToFirstPending);
  els.prevButton.addEventListener("click", () => goToOffset(-1));
  els.nextButton.addEventListener("click", () => goToOffset(1));
  els.reloadButton.addEventListener("click", loadGroup);
  els.saveButton.addEventListener("click", () => saveAnnotation());
  els.saveNextButton.addEventListener("click", () => saveAnnotation({ goNext: true }));
  els.exportButton.addEventListener("click", () => {
    const query = encodeQuery({ annotator: state.annotator });
    window.open(`/api/export?${query}`, "_blank", "noopener");
  });

  els.modalClose.addEventListener("click", closeModal);
  els.modal.addEventListener("click", (event) => {
    if (event.target === els.modal) closeModal();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !els.modal.hidden) closeModal();
  });
}

async function init() {
  bindEvents();
  try {
    await loadDatasets();
    await loadGroups({ preferPending: true });
    await loadGroup();
    setStatus("Ready");
  } catch (error) {
    console.error(error);
    setStatus(error.message);
    els.rankBoard.replaceChildren();
    const empty = document.createElement("div");
    empty.className = "emptyState";
    empty.textContent = error.message;
    els.rankBoard.append(empty);
  }
}

init();
