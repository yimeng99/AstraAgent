import { onUnmounted, ref, watch } from "vue";

export function useStreamingText(content: () => string, active: () => boolean) {
  const displayed = ref(content());
  let frame = 0;
  function tick() {
    const target = content();
    const remaining = target.length - displayed.value.length;
    // 突发的大段数据加速追赶，避免显示长期落后于服务端。
    const count = Math.max(1, Math.ceil(remaining / 6));
    displayed.value = target.slice(0, displayed.value.length + count);
    frame = displayed.value.length < target.length ? requestAnimationFrame(tick) : 0;
  }
  watch([content, active], ([text, streaming]) => {
    if (!streaming || !text.startsWith(displayed.value)) {
      cancelAnimationFrame(frame);
      frame = 0;
      displayed.value = text;
    } else if (!frame && text !== displayed.value) {
      frame = requestAnimationFrame(tick);
    }
  });
  onUnmounted(() => cancelAnimationFrame(frame));
  return displayed;
}
