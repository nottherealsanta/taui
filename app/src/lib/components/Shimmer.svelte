<!--
  Shimmer.svelte
  Shared animated shimmer bar used on tool cards, minion cards,
  agent tabs, and any other "in-progress" indicator surfaces.
-->
<script lang="ts">
  interface Props {
    /** Position: 'bottom' (default) or 'top' */
    position?: 'top' | 'bottom'
    /** Bar height in pixels (default: 2) */
    height?: number
    /** Custom color (defaults to --fg-accent) */
    color?: string
  }
  const {
    position = 'bottom',
    height = 2,
    color,
  }: Props = $props()
</script>

<div
  class="shimmer-bar"
  class:top={position === 'top'}
  style:height="{height}px"
  style:--shimmer-color={color ?? 'var(--fg-accent)'}
></div>

<style lang="postcss">
  .shimmer-bar {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    background: linear-gradient(
      90deg,
      transparent 0%,
      var(--shimmer-color) 50%,
      transparent 100%
    );
    background-size: 200% 100%;
    animation: shimmer 1.5s ease-in-out infinite;
    pointer-events: none;
  }

  .shimmer-bar.top {
    bottom: auto;
    top: 0;
  }

  @keyframes shimmer {
    0% { background-position: -200% 0; }
    100% { background-position: 200% 0; }
  }
</style>
