import { parseCanonicalTrajectory } from "./repeatedMeasuresViewModel";

export function Trajectory({ context }: { context: unknown }) {
  const trajectory = parseCanonicalTrajectory(context);
  if (trajectory === null) return null;
  return (
    <section aria-label="lmm-group-trajectory">
      <h3>组别轨迹</h3>
      <table>
        <thead>
          <tr><th>组别</th><th>时间</th><th>观测均值</th><th>拟合均值</th></tr>
        </thead>
        <tbody>
          {trajectory.groups.flatMap((group) => trajectory.time.map((time, index) => (
            <tr key={`${group.label}-${time}`}>
              <td>{group.label}</td><td>{time}</td>
              <td>{group.observed_mean[index]}</td><td>{group.fitted_mean[index]}</td>
            </tr>
          )))}
        </tbody>
      </table>
    </section>
  );
}
