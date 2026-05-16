/**
 * Insert a placeholder string at the current cursor position in a textarea.
 * Falls back to appending at the end if the textarea is not found.
 */
export function insertPlaceholderAtCursor(
  textareaId: string,
  placeholder: string,
  currentValue: string,
  onUpdate: (newValue: string) => void
) {
  const textarea = document.getElementById(textareaId) as HTMLTextAreaElement;
  if (textarea) {
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const newValue =
      currentValue.slice(0, start) + placeholder + currentValue.slice(end);
    onUpdate(newValue);
    setTimeout(() => {
      textarea.focus();
      textarea.setSelectionRange(
        start + placeholder.length,
        start + placeholder.length
      );
    }, 0);
  } else {
    onUpdate(currentValue + placeholder);
  }
}
