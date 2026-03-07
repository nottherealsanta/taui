export function bindKeybindings(target, handlers) {
  target.addEventListener("keydown", (event) => {
    const key = event.key;

    if (key === "ArrowDown") {
      event.preventDefault();
      handlers.selectNext();
      return;
    }
    if (key === "ArrowUp") {
      event.preventDefault();
      handlers.selectPrev();
      return;
    }
    if (key === "ArrowLeft") {
      event.preventDefault();
      handlers.arrowLeft();
      return;
    }
    if (key === "ArrowRight") {
      event.preventDefault();
      handlers.arrowRight();
      return;
    }
    if (key === "Escape") {
      handlers.stopEditing();
      return;
    }
    if (key === "F2") {
      event.preventDefault();
      handlers.startEditing();
      return;
    }
    if (key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handlers.enter();
      return;
    }
    if ((event.ctrlKey || event.metaKey) && key.toLowerCase() === "c") {
      event.preventDefault();
      handlers.toggleCollapse();
      return;
    }
    if ((event.ctrlKey || event.metaKey) && key.toLowerCase() === "s") {
      event.preventDefault();
      handlers.cycleStatus();
    }
  });
}
