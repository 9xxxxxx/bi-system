import { useEffect, useRef } from "react";
import { GridStack } from "gridstack";
import "gridstack/dist/gridstack.min.css";

export default function GridStackCandidate() {
  const hostRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!hostRef.current) return;
    const grid = GridStack.init({ column: 6, cellHeight: 46, margin: 8, float: true }, hostRef.current);
    return () => {
      grid.destroy(false);
    };
  }, []);

  return (
    <section className="candidate-block" aria-labelledby="gridstack-title">
      <h3 id="gridstack-title">候选 B · GridStack 12.6.0</h3>
      <p>命令式 DOM 适配层；拖动下面的项目验证交互。</p>
      <div className="grid-stack" ref={hostRef}>
        {[
          ["g1", 0, 0, 2, 1],
          ["g2", 2, 0, 2, 1],
          ["g3", 4, 0, 2, 1],
        ].map(([id, x, y, w, h]) => (
          <div className="grid-stack-item" key={id} gs-id={id} gs-x={x} gs-y={y} gs-w={w} gs-h={h}>
            <div className="grid-stack-item-content">{id}</div>
          </div>
        ))}
      </div>
    </section>
  );
}
