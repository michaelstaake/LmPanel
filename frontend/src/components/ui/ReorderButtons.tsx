type ReorderButtonsProps = {
  onMoveUp: () => void;
  onMoveDown: () => void;
  canMoveUp: boolean;
  canMoveDown: boolean;
  disabled?: boolean;
};

export default function ReorderButtons({
  onMoveUp,
  onMoveDown,
  canMoveUp,
  canMoveDown,
  disabled = false,
}: ReorderButtonsProps) {
  const buttonClassName =
    "cursor-pointer border border-white/15 bg-white/10 px-2 py-1 text-sand/70 transition hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-40";

  return (
    <div className="flex flex-col gap-0.5">
      <button
        type="button"
        aria-label="Move up"
        onClick={onMoveUp}
        disabled={disabled || !canMoveUp}
        className={buttonClassName}
      >
        <i className="bi bi-chevron-up text-xs leading-none" aria-hidden="true" />
      </button>
      <button
        type="button"
        aria-label="Move down"
        onClick={onMoveDown}
        disabled={disabled || !canMoveDown}
        className={buttonClassName}
      >
        <i className="bi bi-chevron-down text-xs leading-none" aria-hidden="true" />
      </button>
    </div>
  );
}
