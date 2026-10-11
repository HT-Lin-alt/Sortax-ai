import { useEffect, useLayoutEffect, useRef } from "react";

export function useAutoScroll(dependency: unknown) {
  const containerRef = useRef<HTMLElement>(null);
  const nearBottomRef = useRef(true);

  useEffect(() => {
    const element = containerRef.current;
    if (element === null) return;
    const update = () => {
      nearBottomRef.current = element.scrollHeight - element.scrollTop - element.clientHeight < 96;
    };
    element.addEventListener("scroll", update, { passive: true });
    return () => { element.removeEventListener("scroll", update); };
  }, []);

  useLayoutEffect(() => {
    const element = containerRef.current;
    if (element !== null && nearBottomRef.current) {
      element.scrollTo({ top: element.scrollHeight, behavior: "smooth" });
    }
  }, [dependency]);

  return containerRef;
}
