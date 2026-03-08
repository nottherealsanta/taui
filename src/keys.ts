export function bindKeybindings(
  target: EventTarget,
  handlers: {
    selectNext: () => void;
    selectPrev: () => void;
    arrowLeft: () => void;
    arrowRight: () => void;
    toggleCollapse: () => void;
    cycleStatus: () => void;
  }
) {
  target.addEventListener('keydown', (event: Event) => {
    const keyEvent = event as KeyboardEvent;
    const key = keyEvent.key;

    // Skip if user is typing in an input or editor
    const targetElement = event.target as HTMLElement;
    if (targetElement.tagName === 'INPUT' || 
        targetElement.tagName === 'TEXTAREA' || 
        targetElement.closest('.ProseMirror') ||
        targetElement.isContentEditable) {
      return;
    }

    if (key === 'ArrowDown') {
      event.preventDefault();
      handlers.selectNext();
      return;
    }
    if (key === 'ArrowUp') {
      event.preventDefault();
      handlers.selectPrev();
      return;
    }
    if (key === 'ArrowLeft') {
      event.preventDefault();
      handlers.arrowLeft();
      return;
    }
    if (key === 'ArrowRight') {
      event.preventDefault();
      handlers.arrowRight();
      return;
    }
    if ((keyEvent.ctrlKey || keyEvent.metaKey) && key.toLowerCase() === 'c') {
      event.preventDefault();
      handlers.toggleCollapse();
      return;
    }
    if ((keyEvent.ctrlKey || keyEvent.metaKey) && key.toLowerCase() === 's') {
      event.preventDefault();
      handlers.cycleStatus();
    }
  });
}
